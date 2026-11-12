"""Kalshi: events with nested markets, order books (bids only for YES and NO).

The book only has bids: the YES ask ladder is derived from NO bids (ask = 1 - no_bid, same size) and the
NO ask ladder from YES bids. Both the ``orderbook_fp`` (dollar strings) and the legacy integer-cent
``orderbook`` formats are supported; levels are sorted here, never trusted to arrive in order.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from polybot.adapters.base import Catalog, ProbeReport
from polybot.adapters.common import LEAGUE_SPORT, default_winner_market, raw_hash
from polybot.adapters.http import HttpClient
from polybot.adapters.rules_parser import parse_rules
from polybot.domain.enums import FreshnessSource, MarketType, QuoteKind, QuoteStatus, VenueKind
from polybot.domain.models import (
    Capabilities,
    PriceLevel,
    ProviderEvent,
    ProviderMarket,
    ProviderOutcome,
    Quote,
    StartPrecision,
    Tri,
    Venue,
)
from polybot.domain.money import dec
from polybot.matching.normalize import split_matchup

PROVIDER = "kalshi"
VENUE = Venue(PROVIDER, PROVIDER, VenueKind.PREDICTION, "Kalshi", "us")
CAPABILITIES = Capabilities(
    quote_source="order_book",
    depth=Tri.YES,
    limits=Tri.YES,
    fee_model="kalshi_taker",
    update_interval_s=5,
    market_types=(MarketType.MONEYLINE, MarketType.MATCH_RESULT),
    currencies=("USD",),
    deep_links=Tri.YES,
    recheck=Tri.YES,
    streaming=Tri.UNKNOWN,
)
DEFAULT_SERIES = {"nba": "KXNBAGAME", "nfl": "KXNFLGAME", "nhl": "KXNHLGAME", "mlb": "KXMLBGAME", "epl": "KXEPLGAME"}
_MONTHS = {
    m: i
    for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)
}
_TICKER_DATE = re.compile(
    r"-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<hhmm>\d{4})?(?P<codes>[A-Z]+)?(?:G(?P<g>\d))?"
)
ET = ZoneInfo("America/New_York")


def parse_ticker_start(event_ticker: str) -> tuple[datetime, StartPrecision, int | None] | None:
    m = _TICKER_DATE.search(event_ticker)
    if not m or m.group("mon") not in _MONTHS:
        return None
    day = datetime(2000 + int(m.group("yy")), _MONTHS[m.group("mon")], int(m.group("dd")), tzinfo=ET)
    game = int(m.group("g")) if m.group("g") else None
    if m.group("hhmm"):
        hh, mm = int(m.group("hhmm")[:2]), int(m.group("hhmm")[2:])
        if hh < 24 and mm < 60:
            return day.replace(hour=hh, minute=mm).astimezone(UTC), StartPrecision.EXACT, game
    local_midnight = datetime.combine(day.date(), time(0, 0), tzinfo=ET)
    return local_midnight.astimezone(UTC), StartPrecision.DATE, game


def parse_events(payload: dict[str, Any], league: str, fee_rate: Decimal = Decimal("0.07")) -> Catalog:
    cat = Catalog(venues=[VENUE], fetched_at=datetime.now(UTC))
    sport = LEAGUE_SPORT.get(league, "unknown")
    winner_type, winner_period = default_winner_market(league)
    for ev in payload.get("events") or []:
        ticker = str(ev.get("event_ticker") or "")
        start = parse_ticker_start(ticker)
        if start is None:
            continue
        start_at, precision, game = start
        markets = [m for m in ev.get("markets") or [] if str(m.get("status", "")).lower() in {"active", "open"}]
        if not markets:
            continue
        series = str(ev.get("series_ticker") or ticker.split("-")[0])
        url = f"https://kalshi.com/markets/{series.lower()}/{ticker.lower()}"
        title = str(ev.get("title") or markets[0].get("title") or "")
        teams = [
            str(m.get("yes_sub_title") or "")
            for m in markets
            if str(m.get("yes_sub_title") or "").lower() not in {"tie", "draw", ""}
        ]
        # roles come from the "<away> at <home>" title; fall back to market sub-titles (no roles)
        participants: tuple[str, ...] = () if split_matchup(title) else tuple(teams[:2])
        abbreviations: tuple[str, ...] = ()
        cat.events.append(
            ProviderEvent(
                provider=PROVIDER,
                external_id=ticker,
                sport=sport,
                league=league,
                title=title,
                participants=participants,
                start_at=start_at,
                start_precision=precision,
                date_tz="America/New_York",
                game_number=game,
                abbreviations=abbreviations,
                url=url,
            )
        )
        for m in markets:
            rules_text = " ".join(str(m.get(k) or "") for k in ("rules_primary", "rules_secondary")).strip()
            mt = str(m.get("ticker"))
            subject = str(m.get("yes_sub_title") or m.get("subtitle") or "")
            if subject.lower() in {"tie", "draw"}:
                subject = "draw"
            rules = parse_rules(PROVIDER, rules_text, default_period=winner_period, url=url)
            cat.markets.append(
                ProviderMarket(
                    provider=PROVIDER,
                    external_id=mt,
                    external_event_id=ticker,
                    market_type=winner_type,
                    period=winner_period,
                    rules=rules,
                    url=url,
                    title=str(m.get("title") or ""),
                    outcomes=(
                        ProviderOutcome(f"{mt}:yes", "Yes", subject),
                        ProviderOutcome(f"{mt}:no", "No", subject, negated=True),
                    ),
                    fee_params=(("rate", str(fee_rate)),),
                )
            )
    return cat


def _levels(raw: Any, cents: bool) -> list[tuple[Decimal, Decimal]]:
    out = []
    for lv in raw or []:
        if not isinstance(lv, list | tuple) or len(lv) < 2:
            continue
        price = dec(lv[0]) / 100 if cents else dec(lv[0])
        size = dec(lv[1])
        if size > 0 and 0 < price < 1:
            out.append((price, size))
    return out


def book_bids(payload: dict[str, Any]) -> tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]:
    """Return (yes_bids, no_bids) as (price_dollars, size)."""
    fp = payload.get("orderbook_fp")
    if isinstance(fp, dict):
        return _levels(fp.get("yes_dollars"), False), _levels(fp.get("no_dollars"), False)
    ob = payload.get("orderbook") or {}
    if "yes_dollars" in ob or "no_dollars" in ob:
        return _levels(ob.get("yes_dollars"), False), _levels(ob.get("no_dollars"), False)
    return _levels(ob.get("yes"), True), _levels(ob.get("no"), True)


def asks_from_opposite_bids(bids: list[tuple[Decimal, Decimal]]) -> tuple[PriceLevel, ...]:
    """Buying YES at (1 - p) matches a resting NO bid at p for the same contract count."""
    ladder = sorted(((1 - p, s) for p, s in bids), key=lambda x: x[0])
    return tuple(PriceLevel(p, s) for p, s in ladder)


def parse_orderbook(
    payload: dict[str, Any], market: ProviderMarket, received_at: datetime | None = None
) -> list[Quote]:
    now = received_at or datetime.now(UTC)
    yes_bids, no_bids = book_bids(payload)
    yes_asks = asks_from_opposite_bids(no_bids)
    no_asks = asks_from_opposite_bids(yes_bids)
    rh = raw_hash(payload)
    quotes = []
    for outcome, levels in zip(market.outcomes, (yes_asks, no_asks), strict=True):
        quotes.append(
            Quote(
                venue_id=PROVIDER,
                provider=PROVIDER,
                market_external_id=market.external_id,
                outcome_external_id=outcome.external_id,
                kind=QuoteKind.ASK_LEVELS,
                levels=levels,
                currency="USD",
                source_at=now,
                received_at=now,
                freshness=FreshnessSource.VENUE,
                status=QuoteStatus.OPEN if levels else QuoteStatus.SUSPENDED,
                min_size=Decimal(1),
                size_step=Decimal(1),
                tick_size=Decimal("0.01"),
                fee_params=market.fee_params,
                url=market.url,
                raw_hash=rh,
            )
        )
    return quotes


class KalshiAdapter:
    id = PROVIDER
    capabilities = CAPABILITIES

    def __init__(
        self,
        leagues: dict[str, str] | None = None,
        *,
        base_url: str = "https://api.elections.kalshi.com/trade-api/v2",
        fee_rate: Decimal = Decimal("0.07"),
        horizon: timedelta = timedelta(days=3),
        http: HttpClient | None = None,
    ) -> None:
        self.leagues = leagues or {k: v for k, v in DEFAULT_SERIES.items() if k == "nba"}
        self.http = http or HttpClient(base_url, concurrency=4)
        self.fee_rate = fee_rate
        self.horizon = horizon

    async def discover(self) -> Catalog:
        total = Catalog(venues=[VENUE], fetched_at=datetime.now(UTC))
        now = datetime.now(UTC)
        for league, series in self.leagues.items():
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {
                    "series_ticker": series,
                    "status": "open",
                    "with_nested_markets": "true",
                    "limit": 200,
                }
                if cursor:
                    params["cursor"] = cursor
                page = await self.http.get_json("/events", params=params)
                cat = parse_events(page, league, self.fee_rate)
                keep = {
                    e.external_id for e in cat.events if now - timedelta(days=1) <= e.start_at <= now + self.horizon
                }
                total.events.extend(e for e in cat.events if e.external_id in keep)
                total.markets.extend(m for m in cat.markets if m.external_event_id in keep)
                cursor = page.get("cursor") or None
                if not cursor:
                    break
        return total

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        import asyncio

        async def one(m: ProviderMarket) -> list[Quote]:
            payload = await self.http.get_json(f"/markets/{m.external_id}/orderbook")
            return parse_orderbook(payload, m)

        results = await asyncio.gather(*(one(m) for m in markets), return_exceptions=True)
        out: list[Quote] = []
        for r in results:
            if isinstance(r, list):
                out.extend(r)
        return out

    async def probe(self) -> ProbeReport:
        started = datetime.now(UTC)
        try:
            cat = await self.discover()
            quotes = await self.snapshot(cat.markets[:20])
        except Exception as exc:
            return ProbeReport(PROVIDER, False, error=str(exc))
        n_depth = sum(1 for q in quotes if q.total_size is not None)
        return ProbeReport(
            PROVIDER,
            True,
            len(cat.events),
            len(cat.markets),
            len(quotes),
            n_depth,
            n_depth,
            (datetime.now(UTC) - started).total_seconds() * 1000,
        )

    async def aclose(self) -> None:
        await self.http.aclose()
