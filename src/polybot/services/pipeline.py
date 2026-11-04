"""Glue: catalogs -> matching -> approved proposals -> scan. Shared by live services, replay and demo."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from polybot.adapters.base import Adapter, Catalog
from polybot.domain.models import FxRate, FxTable, ProviderEvent, ProviderMarket, Quote, Venue
from polybot.domain.solver import SolverConfig
from polybot.domain.verdict import Thresholds
from polybot.matching.catalog import MatchReport, match_catalog
from polybot.matching.events import EventCluster
from polybot.matching.markets import MarketProposal
from polybot.matching.teams import TeamRegistry
from polybot.services.scanner import EventInfo, OpportunityDraft, QuoteKey, ScanConfig, scan_key
from polybot.settings import Settings


def scan_config_from(settings: Settings, budget: Decimal | None = None) -> ScanConfig:
    return ScanConfig(
        budget=budget or settings.default_budget,
        budget_currency=settings.budget_currency,
        thresholds=Thresholds(settings.min_profit, settings.min_roi),
        solver=SolverConfig(
            settings.solver_max_anchor_points, settings.solver_max_evaluations, settings.exceptional_tolerance
        ),
        quote_ttl={k: timedelta(seconds=v) for k, v in settings.quote_ttl_s.items()},
        max_skew=timedelta(seconds=settings.max_quote_skew_s),
        routes=frozenset(settings.routes),
        max_legs=settings.max_legs,
        top_offers=settings.top_offers_per_selection,
        prematch_buffer=timedelta(minutes=settings.prematch_buffer_min),
        signal_ttl=timedelta(seconds=settings.signal_ttl_s),
        polymarket_step=settings.polymarket_size_step,
        sportsbook_min_stake=settings.sportsbook_min_stake,
        sportsbook_step=settings.sportsbook_stake_step,
        sportsbook_max_stake=dict(settings.sportsbook_max_stake),
        kalshi_fee_rate=settings.kalshi_fee_rate,
    )


def fx_table_from(settings: Settings, now: datetime) -> FxTable:
    table = FxTable(settings.budget_currency)
    for pair, rate in settings.fx_static.items():
        base, quote = pair.split("/")
        table.add(FxRate(base, quote, rate, now, timedelta(seconds=settings.fx_ttl_s), settings.fx_reserve_bps))
    return table


def event_info(cluster: EventCluster, registry: TeamRegistry) -> EventInfo:
    home, away, known = cluster.roles()
    hn = registry.teams[home].name if home in registry.teams else home
    an = registry.teams[away].name if away in registry.teams else away
    if not known:
        title = f"{hn} vs {an}"
    elif cluster.sport == "soccer":
        title = f"{hn} vs {an}"  # football convention: home team first
    else:
        title = f"{an} @ {hn}"
    return EventInfo(cluster.id, cluster.league, title, cluster.start_at, hn, an)


def index_quotes(quotes: Sequence[Quote]) -> dict[QuoteKey, list[Quote]]:
    """Latest quote per (venue, market, outcome); late updates never overwrite newer ones."""
    latest: dict[tuple[str, str, str], Quote] = {}
    for q in quotes:
        k = q.key
        cur = latest.get(k)
        if cur is None or is_newer(q, cur):
            latest[k] = q
    out: dict[QuoteKey, list[Quote]] = defaultdict(list)
    for q in latest.values():
        out[(q.provider, q.market_external_id, q.outcome_external_id)].append(q)
    return dict(out)


def is_newer(new: Quote, old: Quote) -> bool:
    if new.sequence is not None and old.sequence is not None and new.source_at == old.source_at:
        return new.sequence > old.sequence
    if new.source_at != old.source_at:
        return new.source_at > old.source_at
    if new.sequence is not None and old.sequence is not None:
        return new.sequence > old.sequence
    return new.received_at >= old.received_at


@dataclass(slots=True)
class ScanReport:
    drafts: list[OpportunityDraft] = field(default_factory=list)
    rejections: Counter[str] = field(default_factory=Counter)
    keys_scanned: int = 0
    combos_evaluated: int = 0


def scan_all(
    report: MatchReport,
    is_approved: Callable[[MarketProposal], bool],
    quotes: dict[QuoteKey, list[Quote]],
    venues: dict[str, Venue],
    cfg: ScanConfig,
    fx: FxTable,
    now: datetime,
    registry: TeamRegistry,
    only_keys: set[str] | None = None,
) -> ScanReport:
    clusters = {c.id: c for c in report.clusters}
    out = ScanReport()
    for key, proposals in report.by_key().items():
        if only_keys is not None and key not in only_keys:
            continue
        approved = [p for p in proposals if is_approved(p) and p.space is not None]
        if len({p.market.provider for p in approved}) < 1 or len(approved) < 1:
            continue
        cluster = clusters.get(approved[0].event_id)
        space = approved[0].space
        if cluster is None or space is None:
            continue
        res = scan_key(key, space, event_info(cluster, registry), approved, quotes, venues, cfg, fx, now)
        out.keys_scanned += 1
        out.combos_evaluated += res.evaluated
        out.rejections.update(res.rejections)
        out.drafts.extend(res.drafts)
    return out


@dataclass(slots=True)
class World:
    """Everything one discovery + snapshot round produced."""

    events: list[ProviderEvent] = field(default_factory=list)
    markets: list[ProviderMarket] = field(default_factory=list)
    venues: dict[str, Venue] = field(default_factory=dict)
    quotes: list[Quote] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def absorb(self, cat: Catalog) -> None:
        self.events += cat.events
        self.markets += cat.markets
        for v in cat.venues:
            self.venues[v.id] = v
        self.quotes += cat.quotes


async def collect(adapters: Sequence[Adapter]) -> World:
    """Discover and snapshot all adapters; one failing feed never stops the others."""
    world = World()
    for a in adapters:
        try:
            cat = await a.discover()
            world.absorb(cat)
            if not cat.quotes:
                world.quotes += await a.snapshot(cat.markets)
        except Exception as exc:
            world.errors[a.id] = f"{type(exc).__name__}: {exc}"
    return world


def run_offline(
    world: World,
    registry: TeamRegistry,
    cfg: ScanConfig,
    fx: FxTable,
    now: datetime,
    is_approved: Callable[[MarketProposal], bool],
) -> tuple[MatchReport, ScanReport]:
    report = match_catalog(world.events, world.markets, registry)
    scan = scan_all(report, is_approved, index_quotes(world.quotes), world.venues, cfg, fx, now, registry)
    return report, scan
