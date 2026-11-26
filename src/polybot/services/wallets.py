"""Polymarket-only alerts: new wallets with big bets (US6), followed wallets (US7), YES sum < 1 (US3)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot.bot.alerts import render_followed, render_whale, render_yes_sum
from polybot.data import repo, wallets_repo
from polybot.data.polymarket import NegRiskEvent
from polybot.data.tables import Subscription
from polybot.logic.alerts import AlertType
from polybot.logic.fees import FeeModel, NoFee, PolymarketTakerFee
from polybot.logic.models import PriceLevel
from polybot.logic.wallets import NewWalletRule, WalletHistory, WalletTrade, big_trades, is_new_wallet
from polybot.logic.yes_sum import OutcomeBook, best_plan
from polybot.settings import Settings

log = logging.getLogger(__name__)


class UsersSource(Protocol):
    async def big_trades(self, min_usdc: Decimal, limit: int = 200) -> list[WalletTrade]: ...

    async def wallet_trades(self, wallet: str, limit: int = 50) -> list[WalletTrade]: ...

    async def history(self, wallet: str, limit: int = 50) -> WalletHistory: ...

    async def aclose(self) -> None: ...


class EventsSource(Protocol):
    async def neg_risk_events(self, max_events: int = 200) -> list[NegRiskEvent]: ...

    async def asks(self, token_ids: list[str]) -> dict[str, tuple[PriceLevel, ...]]: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class TickResult:
    whales: int = 0
    followed: int = 0
    yes_sum: int = 0


def _fee(rate: Decimal, exponent: Decimal) -> FeeModel:
    return PolymarketTakerFee(rate, exponent) if rate > 0 else NoFee()


class WalletWatcher:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        users: UsersSource | None = None,
        events: EventsSource | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        if users is None:
            from polybot.data.polymarket_users import PolymarketUsersClient

            users = PolymarketUsersClient()
        if events is None:
            from polybot.data.polymarket import PolymarketAdapter

            events = PolymarketAdapter({}, fee_rate=settings.polymarket_fee_rate)
        self.users, self.events = users, events
        self.rule = NewWalletRule(
            settings.whale_min_usdc, settings.whale_max_prior_trades, timedelta(days=settings.whale_max_age_days)
        )
        self._history: dict[str, tuple[datetime, WalletHistory]] = {}
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ helpers
    async def _subscribers(self) -> tuple[list[Subscription], bool]:
        async with self.sessions() as s:
            subs = await repo.active_subscriptions(s)
            paused = await repo.get_flag(s, repo.PUBLISHING_PAUSED) == "1"
        return subs, paused

    async def _wallet_history(self, wallet: str, now: datetime) -> WalletHistory:
        cached = self._history.get(wallet)
        if cached and now - cached[0] < timedelta(minutes=30):
            return cached[1]
        history = await self.users.history(wallet, limit=self.rule.max_prior_trades + 5)
        self._history[wallet] = (now, history)
        return history

    # ------------------------------------------------------------------ US6 + US7
    async def check_trades(self, now: datetime | None = None) -> TickResult:
        now = now or datetime.now(UTC)
        result = TickResult()
        subs, _ = await self._subscribers()
        limit = self.settings.free_alert_limit()
        trades = big_trades(await self.users.big_trades(self.rule.min_usdc), self.rule.min_usdc)
        async with self.sessions() as s, s.begin():
            fresh = await wallets_repo.claim_new(s, (f"whale:{t.key}" for t in trades), now)
        for t in trades:
            if f"whale:{t.key}" not in fresh:
                continue
            history = await self._wallet_history(t.wallet, now)
            if not is_new_wallet(history, now, self.rule):
                continue
            async with self.sessions() as s, s.begin():
                result.whales += await wallets_repo.send_alert(
                    s, subs, "whale", AlertType.WHALES, render_whale(t, history), t.key, now, limit
                )
        async with self.sessions() as s:
            followers = await wallets_repo.followers_by_wallet(s)
        by_chat = {sub.chat_id: sub for sub in subs}
        for wallet, rows in followers.items():
            for t in await self.users.wallet_trades(wallet, limit=20):
                if now - t.at > timedelta(hours=1):
                    continue  # only fresh activity; older trades were there before the follow
                async with self.sessions() as s, s.begin():
                    if f"wallet:{t.key}" not in await wallets_repo.claim_new(s, [f"wallet:{t.key}"], now):
                        continue
                    for row in rows:
                        sub = by_chat.get(row.chat_id)
                        if sub is None or t.usdc < row.min_usdc:
                            continue
                        result.followed += await wallets_repo.send_alert(
                            s, [sub], "wallet", AlertType.WALLETS, render_followed(t, row.label), t.key, now, limit
                        )
        return result

    # ------------------------------------------------------------------ US3
    async def check_yes_sum(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        events = await self.events.neg_risk_events(self.settings.yes_sum_max_events)
        asks = await self.events.asks([o.token_id for e in events for o in e.outcomes])
        subs, _ = await self._subscribers()
        queued = 0
        for e in events:
            books = [
                OutcomeBook(o.label, o.token_id, asks.get(o.token_id, ()), _fee(o.fee_rate, o.fee_exponent), o.min_size)
                for o in e.outcomes
            ]
            plan = best_plan(e.title, e.url, books, self.settings.yes_sum_budget)
            if plan is None or plan.profit < self.settings.yes_sum_min_profit:
                continue
            # one alert per event and price level: a new alert only when the opportunity changes materially
            dedup = f"{e.id}:{plan.top_sum:.3f}:{plan.shares:.0f}"
            async with self.sessions() as s, s.begin():
                queued += await wallets_repo.send_alert(
                    s,
                    subs,
                    "yes_sum",
                    AlertType.YES_SUM,
                    render_yes_sum(plan, len(books)),
                    dedup,
                    now,
                    self.settings.free_alert_limit(),
                    ttl=timedelta(minutes=10),
                )
        return queued

    # ------------------------------------------------------------------ loops
    async def run(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        if self.settings.wallets_enabled:
            tasks.append(asyncio.create_task(self._loop(self.check_trades, self.settings.wallets_interval_s)))
        if self.settings.yes_sum_enabled:
            tasks.append(asyncio.create_task(self._loop(self.check_yes_sum, self.settings.yes_sum_interval_s)))
        tasks.append(asyncio.create_task(self._loop(self._purge, 3600)))
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.users.aclose()
            await self.events.aclose()

    async def _purge(self) -> None:
        async with self.sessions() as s, s.begin():
            await wallets_repo.purge_seen(s, datetime.now(UTC) - timedelta(days=7))

    async def _loop(self, job: Any, interval: int) -> None:
        while True:
            try:
                await job()
            except Exception:  # one failing API call must not stop the watcher
                log.exception("wallet watcher job failed", extra={"job": getattr(job, "__name__", "?")})
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._stop.set()


def plans_for(events: Sequence[NegRiskEvent], asks: dict[str, tuple[PriceLevel, ...]], budget: Decimal) -> list[Any]:
    """Helper for ``polybot probe``: profitable YES-sum plans for already fetched events."""
    out = []
    for e in events:
        books = [
            OutcomeBook(o.label, o.token_id, asks.get(o.token_id, ()), _fee(o.fee_rate, o.fee_exponent), o.min_size)
            for o in e.outcomes
        ]
        plan = best_plan(e.title, e.url, books, budget)
        if plan is not None:
            out.append(plan)
    return out
