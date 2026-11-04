"""The Odds API v4 (aggregator). One request returns events, bookmakers and decimal prices.

Venue = bookmaker brand + region (``oddsapi:<bookmaker>:<region>``); the data source is ``oddsapi``.
Limits are unknown and freshness is only confirmed by the aggregator, so every route through this
adapter produces *candidates*, never normal signals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from polybot.adapters.base import Catalog, ProbeReport
from polybot.adapters.common import LEAGUE_SPORT, default_winner_market, parse_ts, raw_hash
from polybot.adapters.http import HttpClient
from polybot.adapters.rules_parser import sportsbook_default_rules
from polybot.domain.enums import FreshnessSource, MarketType, Period, QuoteKind, QuoteStatus, VenueKind
from polybot.domain.models import (
    Capabilities,
    PriceLevel,
    ProviderEvent,
    ProviderMarket,
    ProviderOutcome,
    Quote,
    Tri,
    Venue,
)
from polybot.domain.money import dec

PROVIDER = "oddsapi"
CAPABILITIES = Capabilities(
    quote_source="aggregator_odds",
    depth=Tri.NO,
    limits=Tri.UNKNOWN,
    fee_model="none",
    update_interval_s=60,
    market_types=(MarketType.MONEYLINE, MarketType.MATCH_RESULT, MarketType.TOTAL),
    currencies=("USD", "EUR", "GBP"),
    deep_links=Tri.UNKNOWN,
    recheck=Tri.YES,
    streaming=Tri.NO,
)
SPORT_KEYS = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "nhl": "icehockey_nhl",
    "mlb": "baseball_mlb",
    "epl": "soccer_epl",
}
REGION_CURRENCY = {"us": "USD", "us2": "USD", "uk": "GBP", "eu": "EUR", "au": "AUD"}


def venue_for(bookmaker: str, title: str, region: str) -> Venue:
    return Venue(f"{PROVIDER}:{bookmaker}:{region}", PROVIDER, VenueKind.SPORTSBOOK, title, region)


def market_id(event_id: str, key: str, point: Decimal | None) -> str:
    return f"{event_id}:{key}" + (f":{point.normalize():f}" if point is not None else "")


def parse_odds(
    payload: list[dict[str, Any]],
    league: str,
    region: str,
    bookmakers: set[str] | None = None,
    received_at: datetime | None = None,
    currency: str | None = None,
) -> Catalog:
    now = received_at or datetime.now(UTC)
    cat = Catalog(fetched_at=now)
    sport = LEAGUE_SPORT.get(league, "unknown")
    winner_type, winner_period = default_winner_market(league)
    ccy = currency or REGION_CURRENCY.get(region, "USD")
    markets: dict[str, ProviderMarket] = {}
    venues: dict[str, Venue] = {}
    for ev in payload:
        ev_id = str(ev["id"])
        start = parse_ts(ev.get("commence_time"))
        if start is None:
            continue
        home, away = str(ev.get("home_team") or ""), str(ev.get("away_team") or "")
        cat.events.append(
            ProviderEvent(
                provider=PROVIDER,
                external_id=ev_id,
                sport=sport,
                league=league,
                title=f"{away} @ {home}",
                participants=(home, away),
                home=home,
                away=away,
                start_at=start,
            )
        )
        for bm in ev.get("bookmakers") or []:
            key = str(bm.get("key"))
            if bookmakers and key not in bookmakers:
                continue
            venue = venues.setdefault(key, venue_for(key, str(bm.get("title") or key), region))
            for mk in bm.get("markets") or []:
                mkey = str(mk.get("key"))
                updated = parse_ts(mk.get("last_update")) or parse_ts(bm.get("last_update")) or now
                outcomes = mk.get("outcomes") or []
                if mkey == "h2h":
                    mtype, period, point = winner_type, winner_period, None
                    has_draw = any(str(o.get("name", "")).lower() == "draw" for o in outcomes)
                    if has_draw:
                        mtype, period = MarketType.MATCH_RESULT, Period.REGULATION
                elif mkey == "totals":
                    mtype, period = MarketType.TOTAL, winner_period
                    points = {str(o.get("point")) for o in outcomes}
                    if len(points) != 1:
                        continue
                    point = dec(outcomes[0]["point"])
                else:
                    continue
                mid = market_id(ev_id, mkey, point)
                if mid not in markets:
                    pouts = tuple(
                        ProviderOutcome(
                            str(o["name"]),
                            str(o["name"]),
                            "draw" if str(o["name"]).lower() == "draw" else str(o["name"]),
                        )
                        for o in outcomes
                    )
                    markets[mid] = ProviderMarket(
                        provider=PROVIDER,
                        external_id=mid,
                        external_event_id=ev_id,
                        market_type=mtype,
                        period=period,
                        outcomes=pouts,
                        rules=sportsbook_default_rules(PROVIDER, sport, period),
                        line=point,
                        line_unit="points" if point is not None else None,
                        title=f"{away} @ {home} {mkey}",
                    )
                for o in outcomes:
                    price = dec(o["price"])
                    if price <= 1:
                        continue
                    link = o.get("link") or mk.get("link") or bm.get("link")
                    cat.quotes.append(
                        Quote(
                            venue_id=venue.id,
                            provider=PROVIDER,
                            market_external_id=mid,
                            outcome_external_id=str(o["name"]),
                            kind=QuoteKind.DECIMAL_ODDS,
                            levels=(PriceLevel(price, None),),
                            currency=ccy,
                            source_at=updated,
                            received_at=now,
                            freshness=FreshnessSource.AGGREGATOR,
                            status=QuoteStatus.OPEN,
                            min_size=Decimal(1),
                            size_step=Decimal(1),
                            max_size=None,
                            url=str(link) if link else None,
                            raw_hash=raw_hash(o),
                        )
                    )
    cat.markets = list(markets.values())
    cat.venues = list(venues.values())
    return cat


class OddsApiAdapter:
    id = PROVIDER
    capabilities = CAPABILITIES

    def __init__(
        self,
        api_key: str,
        leagues: list[str],
        *,
        regions: list[str] | None = None,
        markets: tuple[str, ...] = ("h2h",),
        bookmakers: set[str] | None = None,
        base_url: str = "https://api.the-odds-api.com",
        horizon: timedelta = timedelta(days=3),
        http: HttpClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.leagues = leagues
        self.regions = regions or ["eu"]
        self.markets = markets
        self.bookmakers = bookmakers
        self.http = http or HttpClient(base_url, concurrency=2)
        self.horizon = horizon
        self.quota: dict[str, str] = {}
        self._last: Catalog | None = None

    async def discover(self) -> Catalog:
        total = Catalog(fetched_at=datetime.now(UTC))
        now = datetime.now(UTC)
        seen_events: set[str] = set()
        seen_markets: set[str] = set()
        for league in self.leagues:
            sport_key = SPORT_KEYS[league]
            for region in self.regions:
                payload = await self.http.get_json(
                    f"/v4/sports/{sport_key}/odds",
                    params={
                        "apiKey": self.api_key,
                        "regions": region,
                        "markets": ",".join(self.markets),
                        "oddsFormat": "decimal",
                        "dateFormat": "iso",
                        "includeLinks": "true",
                        "commenceTimeTo": (now + self.horizon).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
                for h in ("x-requests-remaining", "x-requests-used", "x-requests-last"):
                    if h in self.http.last_headers:
                        self.quota[h] = self.http.last_headers[h]
                cat = parse_odds(payload, league, region, self.bookmakers)
                total.events.extend(e for e in cat.events if e.external_id not in seen_events)
                seen_events.update(e.external_id for e in cat.events)
                total.markets.extend(m for m in cat.markets if m.external_id not in seen_markets)
                seen_markets.update(m.external_id for m in cat.markets)
                total.venues.extend(cat.venues)
                total.quotes.extend(cat.quotes)
        self._last = total
        return total

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        cat = await self.discover()
        wanted = {m.external_id for m in markets}
        return [q for q in cat.quotes if q.market_external_id in wanted]

    async def probe(self) -> ProbeReport:
        started = datetime.now(UTC)
        try:
            cat = await self.discover()
        except Exception as exc:
            return ProbeReport(PROVIDER, False, error=str(exc))
        return ProbeReport(
            PROVIDER,
            True,
            len(cat.events),
            len(cat.markets),
            len(cat.quotes),
            0,
            0,
            (datetime.now(UTC) - started).total_seconds() * 1000,
            dict(self.quota),
        )

    async def aclose(self) -> None:
        await self.http.aclose()
