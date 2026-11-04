"""TEST DATA ONLY. Synthetic venues, quotes and rules used by offline tests. Not real market data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polybot.domain.enums import (
    FreshnessSource,
    MarketType,
    Period,
    QuoteKind,
    SettlementPolicy,
    VenueKind,
)
from polybot.domain.fees import FeeModel, KalshiTakerFee, NoFee
from polybot.domain.legs import Leg
from polybot.domain.models import FxRate, PriceLevel, Quote, RuleSet, Selection, Venue
from polybot.domain.scenarios import ScenarioSpace, build_space

D = Decimal
NOW = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)

POLY = Venue("polymarket", "polymarket", VenueKind.PREDICTION, "Polymarket")
KALSHI = Venue("kalshi", "kalshi", VenueKind.PREDICTION, "Kalshi")
BOOK = Venue("oddsapi:testbook:eu", "oddsapi", VenueKind.SPORTSBOOK, "TestBook", "eu")


def nba_space() -> ScenarioSpace:
    return build_space("basketball", MarketType.MONEYLINE, Period.FULL_GAME, ("nba:bos", "nba:lal"))


def soccer_space() -> ScenarioSpace:
    return build_space("soccer", MarketType.MATCH_RESULT, Period.REGULATION, ("epl:ars", "epl:che"))


def rules(
    provider: str,
    period: Period = Period.FULL_GAME,
    cancel: SettlementPolicy = SettlementPolicy.REFUND,
    postpone: SettlementPolicy = SettlementPolicy.REFUND,
    draw: SettlementPolicy = SettlementPolicy.UNKNOWN,
    assumed: bool = False,
) -> RuleSet:
    return RuleSet(
        provider=provider,
        period=period,
        on_cancel=cancel,
        on_postpone=postpone,
        on_draw=draw,
        text=f"TEST RULES {provider}",
        assumed=assumed,
    )


def book_quote(
    venue: Venue,
    levels: list[tuple[str, str | None]],
    *,
    kind: QuoteKind = QuoteKind.ASK_LEVELS,
    currency: str = "USD",
    age_s: int = 5,
    freshness: FreshnessSource = FreshnessSource.VENUE,
) -> Quote:
    return Quote(
        venue_id=venue.id,
        provider=venue.source,
        market_external_id="TEST-MKT",
        outcome_external_id="TEST-OUT",
        kind=kind,
        levels=tuple(PriceLevel(D(p), D(s) if s is not None else None) for p, s in levels),
        currency=currency,
        source_at=NOW - timedelta(seconds=age_s),
        received_at=NOW,
        freshness=freshness,
    )


def prediction_leg(
    venue: Venue,
    selection: Selection,
    levels: list[tuple[str, str]],
    *,
    fee: FeeModel | None = None,
    rule_set: RuleSet | None = None,
    currency: str = "USD",
    fx: FxRate | None = None,
    min_size: str = "1",
    step: str = "1",
) -> Leg:
    return Leg(
        venue=venue,
        selection=selection,
        rules=rule_set or rules(venue.source),
        quote=book_quote(venue, list(levels), currency=currency),
        fee=fee or NoFee(),
        fx=fx,
        min_size=D(min_size),
        step=D(step),
        label=selection.label,
    )


def sportsbook_leg(
    selection: Selection,
    odds: str,
    *,
    max_stake: str | None = "500",
    step: str = "1",
    min_stake: str = "1",
    rule_set: RuleSet | None = None,
    freshness: FreshnessSource = FreshnessSource.VENUE,
    venue: Venue = BOOK,
) -> Leg:
    return Leg(
        venue=venue,
        selection=selection,
        rules=rule_set or rules("oddsapi"),
        quote=book_quote(venue, [(odds, None)], kind=QuoteKind.DECIMAL_ODDS, freshness=freshness),
        fee=NoFee(),
        min_size=D(min_stake),
        step=D(step),
        max_size=D(max_stake) if max_stake is not None else None,
        label=selection.label,
    )


def kalshi_fee() -> KalshiTakerFee:
    return KalshiTakerFee(D("0.07"))
