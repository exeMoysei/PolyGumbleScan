"""Pure scanning core: approved mappings + current quotes -> opportunity drafts and rejections.

No I/O here, so the same code runs live, in replay and in tests.
"""

from __future__ import annotations

import hashlib
import itertools
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from polybot.domain.enums import QuoteStatus, Route, VenueKind, Verdict
from polybot.domain.fees import FeeModel, KalshiTakerFee, NoFee, PolymarketTakerFee
from polybot.domain.legs import Leg
from polybot.domain.models import FxTable, ProviderMarket, ProviderOutcome, Quote, Selection, Venue
from polybot.domain.money import ONE, dec
from polybot.domain.prefilter import prefilter
from polybot.domain.scenarios import ScenarioSpace
from polybot.domain.solver import Plan, SolverConfig, solve
from polybot.domain.verdict import Assessment, Thresholds, assess
from polybot.matching.markets import MarketProposal

CALC_VERSION = "budget-aware-2"
QuoteKey = tuple[str, str, str]  # (provider, market_external_id, outcome_external_id)


@dataclass(frozen=True, slots=True)
class ScanConfig:
    budget: Decimal = Decimal("100")
    budget_currency: str = "USD"
    thresholds: Thresholds = field(default_factory=Thresholds)
    solver: SolverConfig = field(default_factory=SolverConfig)
    quote_ttl: dict[str, timedelta] = field(
        default_factory=lambda: {
            "polymarket": timedelta(seconds=90),
            "kalshi": timedelta(seconds=90),
            "oddsapi": timedelta(seconds=600),
        }
    )
    max_skew: timedelta = timedelta(seconds=300)
    routes: frozenset[Route] = frozenset({Route.PREDICTION_PREDICTION, Route.PREDICTION_SPORTSBOOK})
    max_legs: int = 3
    top_offers: int = 3
    max_drafts_per_key: int = 3
    prematch_buffer: timedelta = timedelta(minutes=5)
    signal_ttl: timedelta = timedelta(minutes=10)
    polymarket_step: Decimal = Decimal("1")
    sportsbook_min_stake: Decimal = Decimal("1")
    sportsbook_step: Decimal = Decimal("1")
    sportsbook_max_stake: dict[str, Decimal] = field(default_factory=dict)
    kalshi_fee_rate: Decimal = Decimal("0.07")


@dataclass(frozen=True, slots=True)
class EventInfo:
    event_id: str
    league: str
    title: str
    start_at: datetime
    home: str
    away: str


@dataclass(frozen=True, slots=True)
class Offer:
    venue: Venue
    market: ProviderMarket
    outcome: ProviderOutcome
    selection: Selection
    quote: Quote


@dataclass(frozen=True, slots=True)
class OpportunityDraft:
    fingerprint: str
    canonical_market_key: str
    event: EventInfo
    route: Route
    verdict: Verdict
    reasons: tuple[str, ...]
    plan: Plan
    legs: tuple[Leg, ...]
    offers: tuple[Offer, ...]
    space: ScenarioSpace
    rules_versions: tuple[str, ...]
    calc_version: str
    created_at: datetime
    expires_at: datetime
    snapshot_at: datetime  # oldest quote used
    budget: Decimal
    budget_currency: str

    @property
    def min_profit(self) -> Decimal:
        return self.plan.worst_regular

    @property
    def roi(self) -> Decimal:
        return self.plan.roi

    def material_signature(self) -> tuple[str, ...]:
        """Changes that justify notifying the user again."""
        sizes = tuple(f"{pl.fill.size:.0f}" for pl in self.plan.legs)
        prices = tuple(f"{leg.quote.best_price}" for leg in self.legs)
        profit_bucket = (self.plan.worst_regular / Decimal("0.5")).to_integral_value()
        return (self.verdict.value, *sizes, *prices, str(profit_bucket))


@dataclass(slots=True)
class ScanOutcome:
    drafts: list[OpportunityDraft] = field(default_factory=list)
    rejections: Counter[str] = field(default_factory=Counter)
    evaluated: int = 0


def route_of(venues: Iterable[Venue]) -> Route:
    kinds = {v.kind for v in venues}
    if kinds == {VenueKind.PREDICTION}:
        return Route.PREDICTION_PREDICTION
    if VenueKind.PREDICTION in kinds:
        return Route.PREDICTION_SPORTSBOOK
    return Route.SPORTSBOOK_SPORTSBOOK


def fee_model_for(quote: Quote, market: ProviderMarket, cfg: ScanConfig) -> FeeModel:
    if quote.provider == "polymarket":
        rate = quote.fee_param("rate") or market.fee_param("rate") or "0"
        exp = quote.fee_param("exponent") or market.fee_param("exponent") or "1"
        return PolymarketTakerFee(dec(rate), dec(exp)) if dec(rate) > 0 else NoFee()
    if quote.provider == "kalshi":
        k_rate = quote.fee_param("rate") or market.fee_param("rate")
        return KalshiTakerFee(dec(k_rate) if k_rate else cfg.kalshi_fee_rate)
    return NoFee()


def build_leg(offer: Offer, cfg: ScanConfig, fx: FxTable, now: datetime) -> Leg | str:
    q = offer.quote
    if q.status != QuoteStatus.OPEN or not q.levels:
        return "quote_not_open"
    ttl = cfg.quote_ttl.get(q.provider, timedelta(seconds=120))
    if now - q.source_at > ttl:
        return f"quote_stale:{q.provider}"
    rate = None
    if q.currency != cfg.budget_currency:
        rate = fx.get(q.currency)
        if rate is None:
            return f"fx_missing:{q.currency}"
        if not rate.is_fresh(now):
            return f"fx_stale:{q.currency}"
    fee = fee_model_for(q, offer.market, cfg)
    if offer.venue.kind == VenueKind.PREDICTION:
        if q.provider == "polymarket":
            min_size, step = (q.min_size or Decimal(5)), cfg.polymarket_step
        else:
            min_size, step = (q.min_size or ONE), (q.size_step or ONE)
        max_size = None
    else:
        min_size, step = cfg.sportsbook_min_stake, cfg.sportsbook_step
        max_size = cfg.sportsbook_max_stake.get(offer.venue.id)
    return Leg(
        venue=offer.venue,
        selection=offer.selection,
        rules=offer.market.rules,
        quote=q,
        fee=fee,
        fx=rate,
        min_size=min_size,
        step=step,
        max_size=max_size,
        market_url=q.url or offer.market.url,
        label=offer.selection.label,
    )


def collect_offers(
    proposals: Sequence[MarketProposal], quotes: dict[QuoteKey, list[Quote]], venues: dict[str, Venue]
) -> list[Offer]:
    offers: list[Offer] = []
    for p in proposals:
        for co in p.outcomes:
            for q in quotes.get((p.market.provider, p.market.external_id, co.outcome.external_id), []):
                venue = venues.get(q.venue_id) or Venue(
                    q.venue_id,
                    q.provider,
                    VenueKind.SPORTSBOOK if q.provider == "oddsapi" else VenueKind.PREDICTION,
                    q.venue_id,
                )
                offers.append(Offer(venue, p.market, co.outcome, co.selection, q))
    return offers


def _semantic(sel: Selection) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    return (sel.wins, sel.pushes, sel.undefined)


def _covers(sels: Sequence[Selection], regular: frozenset[str]) -> bool:
    seen: set[str] = set()
    for s in sels:
        if seen & s.wins:
            return False  # overlapping selections waste money; not considered in MVP
        seen |= s.wins
    covered = set(seen)
    for s in sels:
        covered |= s.pushes | s.undefined
    return covered >= regular


def fingerprint(
    key: str, offers: Sequence[Offer], *, budget: Decimal | None = None, currency: str | None = None
) -> str:
    refs = sorted(f"{o.venue.id}|{o.market.external_id}|{o.outcome.external_id}" for o in offers)
    if budget is not None:
        refs.append(f"budget:{budget.normalize():f}:{currency}")
    return hashlib.sha256("||".join([key, *refs]).encode()).hexdigest()[:20]


def scan_key(
    key: str,
    space: ScenarioSpace,
    event: EventInfo,
    proposals: Sequence[MarketProposal],
    quotes: dict[QuoteKey, list[Quote]],
    venues: dict[str, Venue],
    cfg: ScanConfig,
    fx: FxTable,
    now: datetime,
) -> ScanOutcome:
    out = ScanOutcome()
    if now >= event.start_at - cfg.prematch_buffer:
        out.rejections["event_started"] += 1
        return out
    legs_by_sem: dict[tuple[frozenset[str], frozenset[str], frozenset[str]], list[tuple[Leg, Offer]]] = defaultdict(
        list
    )
    for offer in collect_offers(proposals, quotes, venues):
        leg = build_leg(offer, cfg, fx, now)
        if isinstance(leg, str):
            out.rejections[leg] += 1
            continue
        legs_by_sem[_semantic(offer.selection)].append((leg, offer))
    # best offer per venue, then top-K venues per selection by top-of-book cost
    groups: list[list[tuple[Leg, Offer]]] = []
    for items in legs_by_sem.values():
        best: dict[str, tuple[Leg, Offer]] = {}
        for leg, offer in items:
            cost = leg.effective_unit_cost()
            if cost is None:
                continue
            cur = best.get(offer.venue.id)
            if cur is None or (cur[0].effective_unit_cost() or cost) > cost:
                best[offer.venue.id] = (leg, offer)
        ranked = sorted(best.values(), key=lambda lo: lo[0].effective_unit_cost() or Decimal(99))
        if ranked:
            groups.append(ranked[: cfg.top_offers])
    regular = space.regular_ids
    drafts: list[OpportunityDraft] = []
    for r in range(2, min(cfg.max_legs, len(groups)) + 1):
        for gcombo in itertools.combinations(groups, r):
            if not _covers([g[0][1].selection for g in gcombo], regular):
                continue
            for choice in itertools.product(*gcombo):
                venues_used = [o.venue for _, o in choice]
                if len({v.id for v in venues_used}) != len(venues_used):
                    continue
                route = route_of(venues_used)
                if route not in cfg.routes:
                    out.rejections[f"route_disabled:{route.value}"] += 1
                    continue
                legs = [leg for leg, _ in choice]
                offers = tuple(o for _, o in choice)
                times = [leg.quote.source_at for leg in legs]
                if max(times) - min(times) > cfg.max_skew:
                    out.rejections["quote_skew"] += 1
                    continue
                pf = prefilter(legs, space.all)
                if not pf.passes:
                    out.rejections["no_edge_top_of_book"] += 1
                    continue
                out.evaluated += 1
                result = solve(legs, space.all, cfg.budget, cfg.solver)
                a: Assessment = assess(result, legs, cfg.thresholds)
                if a.verdict == Verdict.REJECTED or a.plan is None:
                    for reason in a.reasons[:1]:
                        out.rejections[reason.split(":")[0]] += 1
                    continue
                ttl_ends = [
                    leg.quote.source_at + cfg.quote_ttl.get(leg.quote.provider, timedelta(minutes=2)) for leg in legs
                ]
                expires = min([*ttl_ends, now + cfg.signal_ttl, event.start_at - cfg.prematch_buffer])
                drafts.append(
                    OpportunityDraft(
                        fingerprint=fingerprint(key, offers, budget=cfg.budget, currency=cfg.budget_currency),
                        canonical_market_key=key,
                        event=event,
                        route=route,
                        verdict=a.verdict,
                        reasons=a.reasons,
                        plan=a.plan,
                        legs=tuple(legs),
                        offers=offers,
                        space=space,
                        rules_versions=tuple(o.market.rules.version for o in offers),
                        calc_version=CALC_VERSION,
                        created_at=now,
                        expires_at=expires,
                        snapshot_at=min(times),
                        budget=cfg.budget,
                        budget_currency=cfg.budget_currency,
                    )
                )
    drafts.sort(key=lambda d: (d.verdict != Verdict.SIGNAL, -d.plan.worst_regular))
    out.drafts = drafts[: cfg.max_drafts_per_key]
    return out
