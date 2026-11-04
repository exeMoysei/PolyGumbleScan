"""Ingest process: catalog discovery + matching + quote polling into Redis/PostgreSQL."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot import metrics
from polybot.adapters.base import Adapter, Catalog
from polybot.domain.enums import MappingStatus
from polybot.domain.models import Quote
from polybot.matching.catalog import MatchReport, match_catalog
from polybot.services.pipeline import event_info
from polybot.services.runtime import SOURCE_KIND, registry_with_aliases
from polybot.settings import Settings
from polybot.storage import repo
from polybot.storage.quotes import QuoteStore

log = logging.getLogger(__name__)


class IngestService:
    def __init__(
        self,
        settings: Settings,
        adapters: Sequence[Adapter],
        sessions: async_sessionmaker[AsyncSession],
        store: QuoteStore,
    ) -> None:
        self.settings = settings
        self.adapters = list(adapters)
        self.sessions = sessions
        self.store = store
        self.catalogs: dict[str, Catalog] = {}
        self.approved: set[tuple[str, str]] = set()
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ discovery
    async def discover_once(self, now: datetime | None = None) -> MatchReport:
        now = now or datetime.now(UTC)
        for a in self.adapters:
            try:
                self.catalogs[a.id] = await a.discover()
                quota = getattr(a, "quota", {}).get("x-requests-remaining")
                if quota is not None:
                    metrics.API_QUOTA.labels(a.id).set(float(quota))
            except Exception:
                metrics.FEED_ERRORS.labels(a.id, "discover").inc()
                log.exception("discovery failed", extra={"provider": a.id})
        events = [e for c in self.catalogs.values() for e in c.events]
        markets = [m for c in self.catalogs.values() for m in c.markets]
        async with self.sessions() as s, s.begin():
            registry = registry_with_aliases(await repo.team_aliases(s))
            report = match_catalog(events, markets, registry)
            for a in self.adapters:
                await repo.upsert_source(s, a.id, SOURCE_KIND.get(a.id, "prediction"), a.capabilities)
            for c in self.catalogs.values():
                await repo.upsert_venues(s, c.venues, {a.id: a.capabilities for a in self.adapters})
            await repo.upsert_events(s, events)
            ids = await repo.upsert_markets(s, markets)
            await repo.upsert_clusters(
                s, report.clusters, {c.id: event_info(c, registry).title for c in report.clusters}
            )
            changes = []
            for p in report.proposals:
                if len(next((c.providers for c in report.clusters if c.id == p.event_id), set())) < 2:
                    continue  # single-venue events cannot form a cross-venue opportunity
                ch = await repo.sync_mapping(
                    s,
                    ids[(p.market.provider, p.market.external_id)],
                    p,
                    auto_approve=self.settings.auto_approve_strong_matches,
                    now=now,
                )
                if ch:
                    changes.append(ch)
            invalid = {c.canonical_market_key for c in changes if c.status == MappingStatus.INVALIDATED}
            await repo.invalidate_by_markets(s, invalid, now)
            await self._notify_admins(s, changes, now)
            self.approved = {(p, m) for p, m, _ in await repo.approved_markets(s)}
            metrics.EVENTS_SHARED.set(len(report.cross_venue_clusters))
        # aggregators deliver prices together with the catalog
        for c in self.catalogs.values():
            if c.quotes:
                await self._store_quotes(c.quotes)
        log.info(
            "discovery done",
            extra={
                "events": len(events),
                "markets": len(markets),
                "clusters": len(report.clusters),
                "shared": len(report.cross_venue_clusters),
                "unresolved": len(report.unresolved),
            },
        )
        return report

    async def _notify_admins(self, s: AsyncSession, changes: list[repo.MappingChange], now: datetime) -> None:
        if not changes:
            return
        targets = [self.settings.tech_chat_id] if self.settings.tech_chat_id else list(self.settings.admin_ids)
        if not targets:
            return
        lines = [f"🧩 Связки к проверке: {len(changes)}"]
        for c in changes[:15]:
            prev = f" (было {c.previous.value})" if c.previous else ""
            lines.append(
                f"• {c.provider} {c.market_external_id}: {c.status.value}{prev}"
                + (f" — {', '.join(c.reasons[:3])}" if c.reasons else "")
            )
        lines.append("Открыть очередь: /pending")
        await repo.enqueue_text(
            s, targets, "\n".join(lines), dedup=f"map:{now:%Y%m%d%H%M}:{len(changes)}", now=now, kind="admin"
        )

    # ------------------------------------------------------------------ quotes
    async def quotes_once(self, adapter: Adapter) -> int:
        cat = self.catalogs.get(adapter.id)
        if cat is None:
            return 0
        markets = [m for m in cat.markets if (m.provider, m.external_id) in self.approved]
        if not markets:
            return 0
        try:
            quotes = await adapter.snapshot(markets)
        except Exception:
            metrics.FEED_ERRORS.labels(adapter.id, "snapshot").inc()
            log.exception("snapshot failed", extra={"provider": adapter.id})
            return 0
        return await self._store_quotes(quotes)

    async def _store_quotes(self, quotes: Sequence[Quote]) -> int:
        ttl = {k: v * 1000 for k, v in self.settings.quote_ttl_s.items()}
        accepted = await self.store.put_many(quotes, ttl)
        now = datetime.now(UTC)
        for q in accepted:
            metrics.QUOTES.labels(q.provider).inc()
            metrics.QUOTE_AGE.labels(q.provider).observe(max(0.0, (now - q.source_at).total_seconds()))
        dropped = len(quotes) - len(accepted)
        if dropped and quotes:
            metrics.QUOTES_DROPPED.labels(quotes[0].provider).inc(dropped)
        if accepted:
            async with self.sessions() as s, s.begin():
                await repo.store_quote_snapshots(s, accepted)
        return len(accepted)

    # ------------------------------------------------------------------ loops
    async def run(self) -> None:
        await self.discover_once()
        tasks = [
            asyncio.create_task(self._discovery_loop(), name="discovery"),
            asyncio.create_task(self._retention_loop(), name="retention"),
        ]
        for a in self.adapters:
            if a.id == "oddsapi":
                continue  # prices arrive with discovery; polled by its own interval below
            tasks.append(asyncio.create_task(self._quote_loop(a), name=f"quotes:{a.id}"))
        if self.settings.polymarket_ws:
            poly = next((a for a in self.adapters if a.id == "polymarket"), None)
            if poly is not None and hasattr(poly, "stream"):
                tasks.append(asyncio.create_task(self._stream_loop(poly), name="stream:polymarket"))
        odds = next((a for a in self.adapters if a.id == "oddsapi"), None)
        if odds is not None:
            tasks.append(asyncio.create_task(self._odds_loop(odds), name="quotes:oddsapi"))
        await self._stop.wait()
        for t in tasks:
            t.cancel()

    async def _stream_loop(self, a: Adapter) -> None:
        async def on_quote(q: Quote) -> None:
            await self._store_quotes([q])

        while True:
            markets = [
                m for m in self.catalogs.get(a.id, Catalog()).markets if (m.provider, m.external_id) in self.approved
            ]
            if not markets:
                await asyncio.sleep(30)
                continue
            task = asyncio.create_task(a.stream(markets, on_quote))  # type: ignore[attr-defined]
            await asyncio.sleep(self.settings.discovery_interval_s)  # resubscribe after catalog refresh
            task.cancel()

    async def _discovery_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.discovery_interval_s)
            try:
                await self.discover_once()
            except Exception:
                log.exception("discovery loop error")

    async def _quote_loop(self, a: Adapter) -> None:
        interval = self.settings.quote_interval_s.get(a.id, 30)
        while True:
            started = asyncio.get_running_loop().time()
            await self.quotes_once(a)
            await asyncio.sleep(max(1.0, interval - (asyncio.get_running_loop().time() - started)))

    async def _odds_loop(self, a: Adapter) -> None:
        interval = self.settings.quote_interval_s.get(a.id, 300)
        while True:
            await asyncio.sleep(interval)
            if not any(p == a.id for p, _ in self.approved):
                continue  # do not burn quota without approved mappings
            try:
                cat = await a.discover()
                self.catalogs[a.id] = cat
                await self._store_quotes(cat.quotes)
            except Exception:
                metrics.FEED_ERRORS.labels(a.id, "snapshot").inc()
                log.exception("odds poll failed")

    async def _retention_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                async with self.sessions() as s, s.begin():
                    n = await repo.purge_old(s, datetime.now(UTC) - timedelta(days=self.settings.raw_retention_days))
                log.info("retention purge", extra={"rows": n})
            except Exception:
                log.exception("retention failed")

    def stop(self) -> None:
        self._stop.set()
