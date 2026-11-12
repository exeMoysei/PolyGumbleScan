"""Polymarket: Gamma API (catalog + rules) and CLOB (order books, asks used for pricing).

Contract checked against the public docs (Gamma ``/events``, CLOB ``/book`` and ``POST /books``).
Market price for sizing is always the ask ladder; last trade / midpoint are diagnostics only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from polybot.adapters.base import Catalog, ProbeReport, QuoteCallback
from polybot.adapters.book_state import BookState
from polybot.adapters.common import LEAGUE_SPORT, default_winner_market, maybe_json_list, parse_ts, raw_hash
from polybot.adapters.http import HttpClient
from polybot.adapters.rules_parser import parse_rules
from polybot.domain.enums import FreshnessSource, MarketType, Period, QuoteKind, QuoteStatus, VenueKind
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
from polybot.domain.money import dec, opt_dec

PROVIDER = "polymarket"
VENUE = Venue(PROVIDER, PROVIDER, VenueKind.PREDICTION, "Polymarket")
CAPABILITIES = Capabilities(
    quote_source="order_book",
    depth=Tri.YES,
    limits=Tri.YES,
    fee_model="polymarket_taker",
    update_interval_s=5,
    market_types=(MarketType.MONEYLINE, MarketType.MATCH_RESULT, MarketType.TOTAL),
    currencies=("USDC",),
    deep_links=Tri.YES,
    recheck=Tri.YES,
    streaming=Tri.YES,
)
_SLUG = re.compile(r"^(?P<league>[a-z0-9]+)-(?P<a>[a-z0-9]+)-(?P<b>[a-z0-9]+)-(?P<date>\d{4}-\d{2}-\d{2})")
_WILL_WIN = re.compile(r"^will\s+(?P<team>.+?)\s+win\b", re.IGNORECASE)


def _subject_from_binary(m: dict[str, Any]) -> str | None:
    title = str(m.get("groupItemTitle") or "").strip()
    question = str(m.get("question") or "")
    if "draw" in title.lower() or "draw" in question.lower() or "tie" in title.lower():
        return "draw"
    if title:
        return title
    wm = _WILL_WIN.match(question)
    return wm.group("team") if wm else None


def parse_events(
    payload: list[dict[str, Any]], league: str, fee_rate: Decimal = Decimal(0), fee_exponent: Decimal = Decimal(1)
) -> Catalog:
    cat = Catalog(venues=[VENUE], fetched_at=datetime.now(UTC))
    sport = LEAGUE_SPORT.get(league, "unknown")
    winner_type, winner_period = default_winner_market(league)
    for ev in payload:
        slug = str(ev.get("slug") or "")
        sm = _SLUG.match(slug)
        if ev.get("closed"):
            continue
        markets = ev.get("markets") or []
        start = None
        for m in markets:
            start = parse_ts(m.get("gameStartTime"))
            if start:
                break
        start = start or parse_ts(ev.get("startTime")) or parse_ts(ev.get("eventDate"))
        precision = StartPrecision.EXACT
        if start is None and sm:
            start = datetime.fromisoformat(sm.group("date")).replace(tzinfo=UTC)
            precision = StartPrecision.DATE
        if start is None:
            continue
        ext_id = str(ev.get("id"))
        url = f"https://polymarket.com/event/{slug}" if slug else None
        abbr = (sm.group("a").upper(), sm.group("b").upper()) if sm else ()
        cat.events.append(
            ProviderEvent(
                provider=PROVIDER,
                external_id=ext_id,
                sport=sport,
                league=league,
                title=str(ev.get("title") or ""),
                participants=(),
                start_at=start,
                start_precision=precision,
                abbreviations=abbr,
                url=url,
            )
        )
        for m in markets:
            pm = _parse_market(m, ext_id, league, winner_type, winner_period, url, fee_rate, fee_exponent)
            if pm is not None:
                cat.markets.append(pm)
    return cat


def _parse_market(
    m: dict[str, Any],
    event_id: str,
    league: str,
    winner_type: MarketType,
    winner_period: Period,
    url: str | None,
    fee_rate: Decimal,
    fee_exponent: Decimal,
) -> ProviderMarket | None:
    if m.get("closed") or m.get("active") is False:
        return None
    outcomes = [str(o) for o in maybe_json_list(m.get("outcomes"))]
    tokens = [str(t) for t in maybe_json_list(m.get("clobTokenIds"))]
    if len(outcomes) != 2 or len(tokens) != 2:
        return None
    kind = str(m.get("sportsMarketType") or "").lower()
    line = opt_dec(m.get("line"))
    rules_text = str(m.get("description") or "")
    if kind in {"totals", "total"} or [o.lower() for o in outcomes] == ["over", "under"]:
        market_type, period = MarketType.TOTAL, winner_period
        pouts = tuple(ProviderOutcome(t, o, o.lower()) for o, t in zip(outcomes, tokens, strict=True))
    elif kind and kind not in {"moneyline", "match_winner", "winner"}:
        return None  # spreads/props are out of MVP scope
    elif [o.lower() for o in outcomes] == ["yes", "no"]:
        subject = _subject_from_binary(m)
        if subject is None:
            return None
        market_type, period = winner_type, winner_period
        pouts = (ProviderOutcome(tokens[0], "Yes", subject), ProviderOutcome(tokens[1], "No", subject, negated=True))
    else:
        market_type, period = winner_type, winner_period
        pouts = tuple(ProviderOutcome(t, o, o) for o, t in zip(outcomes, tokens, strict=True))
    rules = parse_rules(PROVIDER, rules_text, default_period=period, url=url)
    rate, exponent = _fee_params(m, fee_rate, fee_exponent)
    return ProviderMarket(
        provider=PROVIDER,
        external_id=str(m.get("conditionId") or m.get("id")),
        external_event_id=event_id,
        market_type=market_type,
        period=period,
        outcomes=pouts,
        rules=rules,
        line=line,
        line_unit="points" if line is not None else None,
        url=url,
        title=str(m.get("question") or ""),
        status="open" if m.get("acceptingOrders", True) else "suspended",
        fee_params=(("rate", str(rate)), ("exponent", str(exponent))),
    )


def _fee_params(m: dict[str, Any], default_rate: Decimal, default_exp: Decimal) -> tuple[Decimal, Decimal]:
    fd = m.get("fd") if isinstance(m.get("fd"), dict) else None
    if fd:
        return dec(fd.get("r", default_rate)), dec(fd.get("e", default_exp))
    return default_rate, default_exp


def parse_book(book: dict[str, Any], market: ProviderMarket, received_at: datetime | None = None) -> Quote:
    now = received_at or datetime.now(UTC)
    asks = sorted(((dec(a["price"]), dec(a["size"])) for a in book.get("asks") or []), key=lambda x: x[0])
    ts = parse_ts(book.get("timestamp")) or now
    status = QuoteStatus.OPEN if market.status == "open" and asks else QuoteStatus.SUSPENDED
    return Quote(
        venue_id=PROVIDER,
        provider=PROVIDER,
        market_external_id=market.external_id,
        outcome_external_id=str(book.get("asset_id")),
        kind=QuoteKind.ASK_LEVELS,
        levels=tuple(PriceLevel(p, s) for p, s in asks if s > 0),
        currency="USDC",
        source_at=ts,
        received_at=now,
        freshness=FreshnessSource.VENUE,
        status=status,
        min_size=opt_dec(book.get("min_order_size")),
        size_step=Decimal("0.01"),
        tick_size=opt_dec(book.get("tick_size")),
        fee_params=market.fee_params,
        url=market.url,
        raw_hash=str(book.get("hash") or raw_hash(book)),
    )


def apply_ws_message(msg: dict[str, Any], books: dict[str, BookState]) -> set[str]:
    """Apply one market-channel message; returns the asset ids whose book changed."""
    changed: set[str] = set()
    etype = msg.get("event_type")
    if etype == "book":
        aid = str(msg.get("asset_id"))
        st = books.setdefault(aid, BookState())
        st.snapshot(
            [(dec(a["price"]), dec(a["size"])) for a in msg.get("asks") or []],
            [(dec(b["price"]), dec(b["size"])) for b in msg.get("bids") or []],
        )
        changed.add(aid)
    elif etype == "price_change":
        items = msg.get("price_changes") or [dict(c, asset_id=msg.get("asset_id")) for c in msg.get("changes") or []]
        for c in items:
            aid = str(c.get("asset_id"))
            cur = books.get(aid)
            if cur is None or not cur.valid:
                continue  # wait for a snapshot
            side = "ask" if str(c.get("side", "")).upper() == "SELL" else "bid"
            cur.delta(side, dec(c["price"]), dec(c["size"]))
            changed.add(aid)
    return changed


class PolymarketAdapter:
    id = PROVIDER
    capabilities = CAPABILITIES

    def __init__(
        self,
        leagues: dict[str, str],
        *,
        gamma_url: str = "https://gamma-api.polymarket.com",
        clob_url: str = "https://clob.polymarket.com",
        fee_rate: Decimal = Decimal(0),
        fee_exponent: Decimal = Decimal(1),
        horizon: timedelta = timedelta(days=3),
        gamma: HttpClient | None = None,
        clob: HttpClient | None = None,
    ) -> None:
        self.leagues = leagues  # league -> gamma tag slug
        self.gamma = gamma or HttpClient(gamma_url, concurrency=2)
        self.clob = clob or HttpClient(clob_url, concurrency=4)
        self.fee_rate = fee_rate
        self.fee_exponent = fee_exponent
        self.horizon = horizon

    async def discover(self) -> Catalog:
        total = Catalog(venues=[VENUE], fetched_at=datetime.now(UTC))
        now = datetime.now(UTC)
        for league, tag in self.leagues.items():
            offset = 0
            while True:
                page = await self.gamma.get_json(
                    "/events",
                    params={
                        "tag_slug": tag,
                        "active": "true",
                        "closed": "false",
                        "limit": 100,
                        "offset": offset,
                        "end_date_min": now.isoformat(),
                    },
                )
                if not isinstance(page, list) or not page:
                    break
                cat = parse_events(page, league, self.fee_rate, self.fee_exponent)
                ids = {
                    e.external_id for e in cat.events if now - timedelta(hours=6) <= e.start_at <= now + self.horizon
                }
                total.events.extend(e for e in cat.events if e.external_id in ids)
                total.markets.extend(m for m in cat.markets if m.external_event_id in ids)
                if len(page) < 100:
                    break
                offset += 100
        return total

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        by_token = {o.external_id: m for m in markets for o in m.outcomes}
        tokens = list(by_token)
        quotes: list[Quote] = []
        for i in range(0, len(tokens), 50):
            chunk = tokens[i : i + 50]
            books = await self.clob.request_json("POST", "/books", json=[{"token_id": t} for t in chunk])
            now = datetime.now(UTC)
            for b in books or []:
                m = by_token.get(str(b.get("asset_id")))
                if m:
                    quotes.append(parse_book(b, m, now))
        return quotes

    async def stream(
        self,
        markets: list[ProviderMarket],
        on_quote: QuoteCallback,
        ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market",
    ) -> None:
        """Optional streaming: snapshot + deltas. No sequence numbers on this channel, so the book is
        re-seeded by REST snapshots on reconnect and the poller keeps running as a safety net."""
        import asyncio
        import json

        import websockets

        by_token = {o.external_id: m for m in markets for o in m.outcomes}
        books: dict[str, BookState] = {}
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(ws_url, ping_interval=20, open_timeout=15) as ws:
                    await ws.send(json.dumps({"assets_ids": list(by_token), "type": "market"}))
                    for q in await self.snapshot(markets):
                        await on_quote(q)
                    backoff = 1.0
                    async for raw in ws:
                        payload = json.loads(raw)
                        for msg in payload if isinstance(payload, list) else [payload]:
                            for aid in apply_ws_message(msg, books):
                                m = by_token.get(aid)
                                levels = books[aid].ask_levels()
                                if m is None or levels is None:
                                    continue
                                now = datetime.now(UTC)
                                await on_quote(
                                    Quote(
                                        venue_id=PROVIDER,
                                        provider=PROVIDER,
                                        market_external_id=m.external_id,
                                        outcome_external_id=aid,
                                        kind=QuoteKind.ASK_LEVELS,
                                        levels=levels,
                                        currency="USDC",
                                        source_at=parse_ts(msg.get("timestamp")) or now,
                                        received_at=now,
                                        status=QuoteStatus.OPEN if levels else QuoteStatus.SUSPENDED,
                                        min_size=Decimal(5),
                                        size_step=Decimal("0.01"),
                                        fee_params=m.fee_params,
                                        url=m.url,
                                        raw_hash=str(msg.get("hash") or raw_hash(msg)),
                                    )
                                )
            except asyncio.CancelledError:
                raise
            except Exception:
                for st in books.values():
                    st.valid = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def probe(self) -> ProbeReport:
        started = datetime.now(UTC)
        try:
            cat = await self.discover()
            quotes = await self.snapshot(cat.markets[:20])
        except Exception as exc:
            return ProbeReport(PROVIDER, False, error=str(exc))
        return ProbeReport(
            PROVIDER,
            True,
            len(cat.events),
            len(cat.markets),
            len(quotes),
            sum(1 for q in quotes if q.total_size is not None),
            sum(1 for q in quotes if q.total_size is not None),
            (datetime.now(UTC) - started).total_seconds() * 1000,
        )

    async def aclose(self) -> None:
        await self.gamma.aclose()
        await self.clob.aclose()
