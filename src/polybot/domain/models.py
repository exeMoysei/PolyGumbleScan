"""Domain value objects shared by adapters, matching, the solver and the scanner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from polybot.domain.enums import (
    FreshnessSource,
    MarketType,
    Period,
    QuoteKind,
    QuoteStatus,
    ScenarioKind,
    SettlementPolicy,
    VenueKind,
)


class Tri(StrEnum):
    """Tri-state used by capabilities: unknown must stay unknown, never guessed."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Capabilities:
    quote_source: str  # "order_book", "aggregator_odds", "direct_odds"
    depth: Tri = Tri.UNKNOWN
    limits: Tri = Tri.UNKNOWN
    fee_model: str = "unknown"
    update_interval_s: int | None = None
    market_types: tuple[MarketType, ...] = ()
    currencies: tuple[str, ...] = ()
    deep_links: Tri = Tri.UNKNOWN
    recheck: Tri = Tri.UNKNOWN
    streaming: Tri = Tri.NO

    def as_dict(self) -> dict[str, Any]:
        return {
            "quote_source": self.quote_source,
            "depth": self.depth.value,
            "limits": self.limits.value,
            "fee_model": self.fee_model,
            "update_interval_s": self.update_interval_s,
            "market_types": [m.value for m in self.market_types],
            "currencies": list(self.currencies),
            "deep_links": self.deep_links.value,
            "recheck": self.recheck.value,
            "streaming": self.streaming.value,
        }


@dataclass(frozen=True, slots=True)
class Venue:
    """A place where the user actually places the bet.

    For aggregators the *source* (e.g. ``oddsapi``) differs from the venue (bookmaker brand + region).
    """

    id: str  # e.g. "polymarket", "kalshi", "oddsapi:pinnacle:eu"
    source: str  # provider/adapter id that delivered the data
    kind: VenueKind
    name: str
    region: str | None = None


# ---------------------------------------------------------------- scenarios and selections


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    kind: ScenarioKind
    label: str


@dataclass(frozen=True, slots=True)
class Selection:
    """Canonical meaning of an outcome: the regular scenarios it wins in, and where it pushes."""

    key: str  # e.g. "win:nba:lal", "draw", "not_win:epl:ars", "over:2.5"
    label: str
    wins: frozenset[str]
    pushes: frozenset[str] = frozenset()
    # regular scenarios whose result depends on venue rules (e.g. a tie in a 2-way moneyline)
    undefined: frozenset[str] = frozenset()
    negated: bool = False  # the "No" side of a binary contract

    def regular_policy(self, scenario_id: str) -> SettlementPolicy:
        if scenario_id in self.wins:
            return SettlementPolicy.WIN
        if scenario_id in self.pushes:
            return SettlementPolicy.REFUND
        return SettlementPolicy.LOSE


# ---------------------------------------------------------------- rules


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Settlement rules of one market at one venue. ``None`` means "not stated" (unknown)."""

    provider: str
    period: Period
    on_cancel: SettlementPolicy = SettlementPolicy.UNKNOWN
    on_postpone: SettlementPolicy = SettlementPolicy.UNKNOWN
    on_draw: SettlementPolicy = SettlementPolicy.UNKNOWN  # tie in a market without a draw outcome
    postpone_cutoff_hours: int | None = None
    includes_overtime: bool | None = None
    result_source: str | None = None
    url: str | None = None
    text: str = ""
    assumed: bool = False  # True when the rule set is a documented default, not parsed from the market

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]

    @property
    def version(self) -> str:
        payload = {
            "provider": self.provider,
            "period": self.period.value,
            "on_cancel": self.on_cancel.value,
            "on_postpone": self.on_postpone.value,
            "on_draw": self.on_draw.value,
            "cutoff": self.postpone_cutoff_hours,
            "ot": self.includes_overtime,
            "src": self.result_source,
            "text": self.text_hash,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def exceptional_policy(self, scenario_id: str) -> SettlementPolicy:
        if scenario_id == "cancelled":
            return self.on_cancel
        if scenario_id == "postponed":
            return self.on_postpone
        return SettlementPolicy.UNKNOWN


# ---------------------------------------------------------------- normalized provider data


class StartPrecision(StrEnum):
    EXACT = "exact"
    DATE = "date"  # only the calendar date is known (in ``date_tz``)


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    provider: str
    external_id: str
    sport: str
    league: str
    title: str
    participants: tuple[str, ...]  # raw names as published, in published order
    start_at: datetime  # UTC
    home: str | None = None  # raw home name when the venue states roles
    away: str | None = None
    start_precision: StartPrecision = StartPrecision.EXACT
    date_tz: str = "UTC"
    game_number: int | None = None
    abbreviations: tuple[str, ...] = ()  # venue codes for participants (e.g. slug / ticker codes)
    url: str | None = None
    status: str = "scheduled"


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    external_id: str
    label: str  # raw label ("Lakers", "Yes", "Draw", "Over")
    # what the outcome refers to: a participant raw name, "draw", "over"/"under",
    # and whether it is the negation of that ("No" side of a binary contract)
    subject: str
    negated: bool = False


@dataclass(frozen=True, slots=True)
class ProviderMarket:
    provider: str
    external_id: str
    external_event_id: str
    market_type: MarketType
    period: Period
    outcomes: tuple[ProviderOutcome, ...]
    rules: RuleSet
    line: Decimal | None = None
    line_unit: str | None = None  # "points", "goals", "runs"
    url: str | None = None
    title: str = ""
    status: str = "open"
    fee_params: tuple[tuple[str, str], ...] = ()

    def fee_param(self, name: str) -> str | None:
        return dict(self.fee_params).get(name)


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal  # prediction: price per contract (0..1); sportsbook: decimal odds
    size: Decimal | None  # prediction: contracts available; sportsbook: None (unknown)


@dataclass(frozen=True, slots=True)
class Quote:
    venue_id: str
    provider: str
    market_external_id: str
    outcome_external_id: str
    kind: QuoteKind
    levels: tuple[PriceLevel, ...]  # asks, best first
    currency: str
    source_at: datetime
    received_at: datetime
    freshness: FreshnessSource = FreshnessSource.VENUE
    sequence: int | None = None
    status: QuoteStatus = QuoteStatus.OPEN
    min_size: Decimal | None = None
    size_step: Decimal | None = None
    max_size: Decimal | None = None  # sportsbook max stake if known
    tick_size: Decimal | None = None
    fee_params: tuple[tuple[str, str], ...] = ()  # venue fee parameters as reported (string values)
    url: str | None = None
    raw_hash: str | None = None

    @property
    def best_price(self) -> Decimal | None:
        return self.levels[0].price if self.levels else None

    @property
    def total_size(self) -> Decimal | None:
        if not self.levels or any(lv.size is None for lv in self.levels):
            return None
        return sum((lv.size for lv in self.levels if lv.size is not None), Decimal(0))

    def fee_param(self, name: str) -> str | None:
        for k, v in self.fee_params:
            if k == name:
                return v
        return None

    def age(self, now: datetime) -> timedelta:
        return now - self.source_at

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.venue_id, self.market_external_id, self.outcome_external_id)


@dataclass(frozen=True, slots=True)
class FxRate:
    """Conservative conversion ``base -> quote``: 1 base = ``rate`` quote."""

    base: str
    quote: str
    rate: Decimal
    source_at: datetime
    ttl: timedelta
    reserve_bps: Decimal = Decimal(0)  # haircut applied against the user on every conversion

    def is_fresh(self, now: datetime) -> bool:
        return now - self.source_at <= self.ttl


@dataclass(slots=True)
class FxTable:
    budget_currency: str
    rates: dict[tuple[str, str], FxRate] = field(default_factory=dict)

    def add(self, rate: FxRate) -> None:
        self.rates[(rate.base, rate.quote)] = rate

    def get(self, base: str) -> FxRate | None:
        if base == self.budget_currency:
            return None
        return self.rates.get((base, self.budget_currency))
