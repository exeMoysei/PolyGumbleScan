"""Scan process: recompute affected canonical markets on quote changes, rule changes and TTL expiry."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot import metrics
from polybot.codec import dec_market, dec_selection, dec_space
from polybot.domain.enums import MappingStatus
from polybot.domain.scenarios import ScenarioSpace
from polybot.matching.markets import CanonicalOutcome, MarketProposal
from polybot.services.pipeline import fx_table_from, index_quotes, scan_config_from
from polybot.services.scanner import EventInfo, OpportunityDraft, scan_key
from polybot.settings import Settings
from polybot.storage import repo
from polybot.storage.models import CanonicalEvent, MarketMapping, MarketRow
from polybot.storage.quotes import QuoteStore, RedisQuoteStore

log = logging.getLogger(__name__)


@dataclass(slots=True)
class KeyBundle:
    key: str
    space: ScenarioSpace
    event: EventInfo
    proposals: list[MarketProposal] = field(default_factory=list)

    @property
    def markets(self) -> list[tuple[str, str]]:
        return [(p.market.provider, p.market.external_id) for p in self.proposals]


async def load_bundles(s: AsyncSession, keys: set[str] | None = None) -> dict[str, KeyBundle]:
    q = (
        select(MarketMapping, MarketRow, CanonicalEvent)
        .join(MarketRow, MarketRow.id == MarketMapping.market_id)
        .join(CanonicalEvent, CanonicalEvent.id == MarketMapping.canonical_event_id)
        .where(MarketMapping.status == MappingStatus.APPROVED.value)
    )
    if keys is not None:
        q = q.where(MarketMapping.canonical_market_key.in_(keys))
    bundles: dict[str, KeyBundle] = {}
    for mp, mrow, ev in await s.execute(q):
        if mp.approved_rules_version != mrow.rules_version or mp.approved_params != mp.params:
            continue
        doc = mp.proposal
        if not doc.get("space"):
            continue
        market = dec_market(mrow.data)
        by_id = {o.external_id: o for o in market.outcomes}
        outcomes = tuple(
            CanonicalOutcome(by_id[o["outcome_id"]], dec_selection(o["selection"]))
            for o in doc["outcomes"]
            if o["outcome_id"] in by_id
        )
        space = dec_space(doc["space"])
        prop = MarketProposal(
            market,
            mp.canonical_event_id,
            mp.canonical_market_key,
            space,
            outcomes,
            MappingStatus.APPROVED,
            (),
            mp.rules_version,
            mp.params,
        )
        b = bundles.get(mp.canonical_market_key)
        if b is None:
            home, away = ev.home_team_id, ev.away_team_id
            labels = doc["space"].get("labels", {})
            hn = labels.get(f"win:{home}", home).removeprefix("Победа ")
            an = labels.get(f"win:{away}", away).removeprefix("Победа ")
            info = EventInfo(ev.id, ev.league, ev.title, ev.start_at, hn, an)
            b = bundles[mp.canonical_market_key] = KeyBundle(mp.canonical_market_key, space, info)
        b.proposals.append(prop)
    return bundles


class ScanService:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        store: QuoteStore,
        full_scan_interval_s: int = 30,
        max_budgets: int = 5,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.store = store
        self.full_scan_interval_s = full_scan_interval_s
        self.max_budgets = max_budgets
        self._stop = asyncio.Event()

    async def scan(self, keys: set[str] | None = None, now: datetime | None = None) -> list[OpportunityDraft]:
        started = time.perf_counter()
        now = now or datetime.now(UTC)
        async with self.sessions() as s:
            bundles = await load_bundles(s, keys)
            subs = await repo.active_subscriptions(s)
            paused = (await repo.get_flag(s, repo.PUBLISHING_PAUSED)) == "1"
            venues = await repo.venues(s)
        budgets = sorted({Decimal(sub.budget) for sub in subs})[: self.max_budgets] or [self.settings.default_budget]
        fx = fx_table_from(self.settings, now)
        markets = [m for b in bundles.values() for m in b.markets]
        quotes = index_quotes(await self.store.get_markets(markets))
        published: list[OpportunityDraft] = []
        for budget in budgets:
            cfg = scan_config_from(self.settings, budget)
            for key, b in bundles.items():
                res = scan_key(key, b.space, b.event, b.proposals, quotes, venues, cfg, fx, now)
                for reason, n in res.rejections.items():
                    metrics.REJECTIONS.labels(reason.split(":")[0]).inc(n)
                drafts = [d for d in res.drafts if await self._inputs_unchanged(d)]
                async with self.sessions() as s, s.begin():
                    for d in drafts:
                        r = await repo.publish_draft(
                            s, d, subs, now, paused=paused, free_daily_alerts=self.settings.free_alert_limit()
                        )
                        if r.material:
                            metrics.OPPORTUNITIES.labels(d.verdict.value, d.route.value).inc()
                            metrics.SIGNAL_LATENCY.observe(
                                max(0.0, (now - max(leg.quote.source_at for leg in d.legs)).total_seconds())
                            )
                    await repo.close_opportunities(
                        s,
                        keys={key},
                        keep={d.fingerprint for d in drafts},
                        budget=budget,
                        reason="no_longer_profitable",
                        now=now,
                    )
                    await repo.record_rejections(
                        s, key, dict(Counter({k.split(":")[0]: v for k, v in res.rejections.items()}))
                    )
                published.extend(drafts)
        async with self.sessions() as s, s.begin():
            await repo.expire_opportunities(s, now)
        metrics.SCAN_SECONDS.observe(time.perf_counter() - started)
        return published

    async def _inputs_unchanged(self, d: OpportunityDraft) -> bool:
        """Optimistic check: the quotes used must still be the latest ones before publishing."""
        fresh = index_quotes(
            await self.store.get_markets({(o.market.provider, o.market.external_id) for o in d.offers})
        )
        for leg in d.legs:
            cur = [
                q
                for q in fresh.get(
                    (leg.quote.provider, leg.quote.market_external_id, leg.quote.outcome_external_id), []
                )
                if q.venue_id == leg.quote.venue_id
            ]
            if not cur or cur[0].source_at != leg.quote.source_at or cur[0].raw_hash != leg.quote.raw_hash:
                return False
        return True

    async def run(self) -> None:
        last_full = 0.0
        last_id = "$"
        market_to_keys: dict[tuple[str, str], set[str]] = {}
        while not self._stop.is_set():
            loop_now = time.monotonic()
            if loop_now - last_full >= self.full_scan_interval_s:
                try:
                    await self.scan()
                    async with self.sessions() as s:
                        bundles = await load_bundles(s)
                    market_to_keys = {}
                    for k, b in bundles.items():
                        for m in b.markets:
                            market_to_keys.setdefault(m, set()).add(k)
                except Exception:
                    log.exception("full scan failed")
                last_full = loop_now
            if isinstance(self.store, RedisQuoteStore):
                try:
                    last_id, changed = await self.store.read_changes(last_id, block_ms=1000)
                    if changed:
                        await asyncio.sleep(self.settings.scan_debounce_ms / 1000)  # coalesce bursts
                        last_id, more = await self.store.read_changes(last_id, block_ms=1)
                        changed |= more
                        keys = set().union(*(market_to_keys.get(m, set()) for m in changed))
                        if keys:
                            await self.scan(keys)
                except Exception:  # Redis restart / outage: back off, the full scan catches up
                    log.exception("incremental scan failed")
                    last_id = "$"
                    await asyncio.sleep(2)
            else:
                await asyncio.sleep(1)

    def stop(self) -> None:
        self._stop.set()
