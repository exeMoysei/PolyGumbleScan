"""Wallet watcher end to end on the database: whales, followed wallets, YES sum, alert types, notifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from polybot.bot.notifier import Notifier
from polybot.data import repo, wallets_repo
from polybot.data.polymarket import parse_neg_risk_event
from polybot.data.polymarket_users import parse_history, parse_trade
from polybot.data.tables import Outbox, Subscription
from polybot.logic.alerts import AlertType, toggle
from polybot.logic.models import PriceLevel
from polybot.services.wallets import WalletWatcher
from polybot.settings import Settings

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime.fromtimestamp(1795690100, tz=UTC)
WHALE = "0x" + "1" * 40
OLD = "0x" + "2" * 40


def _load(name: str):  # type: ignore[no-untyped-def]
    return json.loads((FIX / name).read_text())


class FakeUsers:
    def __init__(self) -> None:
        self.trades = [parse_trade(r) for r in _load("polymarket_data_trades.json")["data"]]
        acts = _load("polymarket_data_activity.json")
        self.histories = {
            WHALE: parse_history(WHALE, acts["new_wallet"]["data"], 15),
            OLD: parse_history(OLD, acts["old_wallet"]["data"], 15),
        }

    async def big_trades(self, min_usdc, limit=200):  # type: ignore[no-untyped-def]
        return self.trades

    async def wallet_trades(self, wallet, limit=50):  # type: ignore[no-untyped-def]
        return [t for t in self.trades if t.wallet == wallet]

    async def history(self, wallet, limit=50):  # type: ignore[no-untyped-def]
        return self.histories[wallet]

    async def aclose(self) -> None:
        return None


class FakeEvents:
    async def neg_risk_events(self, max_events=200):  # type: ignore[no-untyped-def]
        evs = [
            parse_neg_risk_event(e, Decimal(0), Decimal(1)) for e in _load("polymarket_negrisk_events.json")["events"]
        ]
        return [e for e in evs if e is not None]

    async def asks(self, token_ids):  # type: ignore[no-untyped-def]
        prices = {"y-cut50": "0.30", "y-cut25": "0.30", "y-hold": "0.35"}
        return {t: (PriceLevel(Decimal(prices[t]), Decimal(1000)),) for t in token_ids if t in prices}

    async def aclose(self) -> None:
        return None


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send(self, chat_id, text, keyboard):  # type: ignore[no-untyped-def]
        self.sent.append((chat_id, text))
        return len(self.sent)


def _watcher(sessions) -> WalletWatcher:  # type: ignore[no-untyped-def]
    st = Settings(odds_api_key=None, premium_enabled=False)  # type: ignore[call-arg]
    return WalletWatcher(st, sessions, users=FakeUsers(), events=FakeEvents())


async def _kinds(sessions) -> list[tuple[int, str]]:  # type: ignore[no-untyped-def]
    async with sessions() as s:
        rows = (await s.execute(select(Outbox.chat_id, Outbox.kind).order_by(Outbox.id))).all()
    return [(int(c), str(k)) for c, k in rows]


async def test_whale_alert_once_and_only_for_new_wallets(sessions) -> None:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, 1, 1, Decimal(100))
        sub2 = await repo.ensure_subscription(s, 2, 2, Decimal(100))
        sub2.filters = toggle(sub2.filters, AlertType.WHALES)  # chat 2 switched whales off
    w = _watcher(sessions)
    first = await w.check_trades(NOW)
    assert first.whales == 1  # only the new wallet's BUY, only for chat 1
    again = await w.check_trades(NOW)
    assert again.whales == 0  # the same trade never alerts twice
    assert await _kinds(sessions) == [(1, "whale")]


async def test_followed_wallet_alerts_only_followers_above_their_minimum(sessions) -> None:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        for chat in (1, 2, 3):
            await repo.ensure_subscription(s, chat, chat, Decimal(100))
        assert await wallets_repo.follow(s, 1, OLD, Decimal(100), "old", 20) == "added"
        assert await wallets_repo.follow(s, 2, OLD, Decimal(50000), None, 20) == "added"  # threshold too high
        assert await wallets_repo.follow(s, 1, OLD, Decimal(200), None, 20) == "updated"
    result = await _watcher(sessions).check_trades(NOW)
    assert result.followed == 2  # chat 1 gets the BUY and the SELL of the followed wallet
    assert [k for k in await _kinds(sessions) if k[1] == "wallet"] == [(1, "wallet"), (1, "wallet")]


async def test_yes_sum_alert_and_notifier_respects_alert_types(sessions) -> None:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, 1, 1, Decimal(100))
        await repo.ensure_subscription(s, 2, 2, Decimal(100))
    w = _watcher(sessions)
    assert await w.check_yes_sum(NOW) == 2
    assert await w.check_yes_sum(NOW) == 0  # same opportunity, same price: no repeat
    async with sessions() as s, s.begin():
        sub2 = await s.get(Subscription, 2)
        assert sub2 is not None
        sub2.filters = toggle(sub2.filters, AlertType.YES_SUM)  # switched off after queueing
    sender = Sender()
    await Notifier(sessions, sender).process_once(NOW)
    assert [c for c, _ in sender.sent] == [1]
    assert "YES SUM" in sender.sent[0][1] and "Fed Decision in December?" in sender.sent[0][1]
