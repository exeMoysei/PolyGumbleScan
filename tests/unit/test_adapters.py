"""Adapter parsing against TEST DATA fixtures in the providers' documented formats."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from polybot.adapters.book_state import BookState
from polybot.adapters.common import parse_ts
from polybot.adapters.http import HttpClient, HttpError, mask_url
from polybot.adapters.kalshi.adapter import parse_events as k_events
from polybot.adapters.kalshi.adapter import parse_orderbook, parse_ticker_start
from polybot.adapters.odds_api.adapter import parse_odds
from polybot.adapters.polymarket.adapter import apply_ws_message, parse_book
from polybot.adapters.polymarket.adapter import parse_events as p_events
from polybot.domain.enums import FreshnessSource, MarketType, Period, QuoteStatus, SettlementPolicy, VenueKind
from polybot.domain.models import StartPrecision

FIX = Path(__file__).parent.parent / "fixtures"
D = Decimal


def load(rel: str):  # type: ignore[no-untyped-def]
    return json.loads((FIX / rel).read_text())


def test_polymarket_events_and_rules() -> None:
    cat = p_events(load("polymarket/events_nba.json")["events"], "nba")
    assert len(cat.events) == 3 and len(cat.markets) == 3
    ev = cat.events[0]
    assert ev.start_at == datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    assert ev.abbreviations == ("LAL", "BOS")
    m = cat.markets[0]
    assert m.market_type == MarketType.MONEYLINE and m.period == Period.FULL_GAME
    assert m.rules.on_cancel == SettlementPolicy.HALF
    assert m.rules.on_postpone == SettlementPolicy.CARRY
    assert m.rules.includes_overtime is True
    assert [o.subject for o in m.outcomes] == ["Lakers", "Celtics"]


def test_polymarket_soccer_binary_markets() -> None:
    cat = p_events(load("polymarket/events_epl.json")["events"], "epl")
    subjects = [(o.subject, o.negated) for m in cat.markets for o in m.outcomes]
    assert ("draw", False) in subjects and ("Arsenal", True) in subjects
    assert all(m.market_type == MarketType.MATCH_RESULT and m.period == Period.REGULATION for m in cat.markets)
    assert cat.markets[0].rules.on_cancel == SettlementPolicy.NO_WINS


def test_polymarket_book_sorted_best_ask_first() -> None:
    cat = p_events(load("polymarket/events_nba.json")["events"], "nba")
    book = next(b for b in load("polymarket/books.json")["books"] if b["asset_id"] == "tok-lal-0115")
    q = parse_book(book, cat.markets[0])
    assert [lv.price for lv in q.levels] == [D("0.42"), D("0.43"), D("0.45")]
    assert q.min_size == D(5) and q.currency == "USDC" and q.freshness == FreshnessSource.VENUE


def test_kalshi_ticker_dates() -> None:
    start, prec, game = parse_ticker_start("KXNBAGAME-26JAN15LALBOS")  # type: ignore[misc]
    assert prec == StartPrecision.DATE and start == datetime(2026, 1, 15, 5, 0, tzinfo=UTC) and game is None
    start2, prec2, _ = parse_ticker_start("KXMLBGAME-26JUL041905NYYBOS")  # type: ignore[misc]
    assert prec2 == StartPrecision.EXACT and start2 == datetime(2026, 7, 4, 23, 5, tzinfo=UTC)


def test_kalshi_asks_derived_from_opposite_bids_both_formats() -> None:
    cat = k_events(load("kalshi/events_nba.json"), "nba")
    books = load("kalshi/orderbooks.json")["books"]
    lal = next(m for m in cat.markets if m.external_id.endswith("-LAL"))
    yes, no = parse_orderbook(books[lal.external_id], lal)
    # NO bids 0.55x120, 0.54x300 -> YES asks 0.45x120, 0.46x300 (sorted, sizes preserved)
    assert [(lv.price, lv.size) for lv in yes.levels] == [(D("0.4500"), D("120.00")), (D("0.4600"), D("300.00"))]
    assert [lv.price for lv in no.levels] == [D("0.5900"), D("0.6000")]
    bos = next(m for m in cat.markets if m.external_id.endswith("-BOS"))
    yes_b, _ = parse_orderbook(books[bos.external_id], bos)  # legacy cents
    assert [(lv.price, lv.size) for lv in yes_b.levels] == [(D("0.54"), D(150)), (D("0.55"), D(300))]
    uta = next(m for m in cat.markets if m.external_id.endswith("-UTA"))
    y, n = parse_orderbook(books[uta.external_id], uta)
    assert y.status == QuoteStatus.SUSPENDED and n.status == QuoteStatus.SUSPENDED
    assert lal.rules.on_cancel == SettlementPolicy.HALF and lal.rules.includes_overtime is True


def test_odds_api_venues_and_aggregator_freshness() -> None:
    cat = parse_odds(load("oddsapi/odds_nba.json")["data"], "nba", "eu", currency="USD")
    assert {v.id for v in cat.venues} == {"oddsapi:pinnacle:eu", "oddsapi:testbook:eu"}
    assert all(v.kind == VenueKind.SPORTSBOOK and v.source == "oddsapi" for v in cat.venues)
    q = cat.quotes[0]
    assert q.freshness == FreshnessSource.AGGREGATOR and q.max_size is None
    assert q.source_at == datetime(2026, 1, 15, 23, 59, 30, tzinfo=UTC)
    ev = cat.events[0]
    assert ev.home == "Boston Celtics" and ev.away == "Los Angeles Lakers"
    assert all(m.rules.assumed for m in cat.markets)
    filtered = parse_odds(load("oddsapi/odds_nba.json")["data"], "nba", "eu", bookmakers={"pinnacle"})
    assert {v.id for v in filtered.venues} == {"oddsapi:pinnacle:eu"}


def test_odds_api_soccer_h2h_is_three_way() -> None:
    cat = parse_odds(load("oddsapi/odds_epl.json")["data"], "epl", "eu")
    m = cat.markets[0]
    assert m.market_type == MarketType.MATCH_RESULT and m.period == Period.REGULATION
    assert {o.subject for o in m.outcomes} == {"Arsenal", "Chelsea", "draw"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-16 00:30:00+00", datetime(2026, 1, 16, 0, 30, tzinfo=UTC)),
        ("2026-01-16T00:30:00Z", datetime(2026, 1, 16, 0, 30, tzinfo=UTC)),
        ("1768523400000", datetime(2026, 1, 16, 0, 30, tzinfo=UTC)),
        (1768523400, datetime(2026, 1, 16, 0, 30, tzinfo=UTC)),
        ("garbage", None),
    ],
)
def test_parse_ts(raw: object, expected: datetime | None) -> None:
    assert parse_ts(raw) == expected


def test_book_state_gap_invalidates_until_snapshot() -> None:
    b = BookState()
    assert b.ask_levels() is None
    b.snapshot([(D("0.45"), D(100))], [(D("0.40"), D(50))], sequence=10)
    assert b.delta("ask", D("0.44"), D(20), 11)
    assert b.delta("ask", D("0.44"), D(99), 11)  # duplicate ignored
    assert [lv.price for lv in b.ask_levels() or ()] == [D("0.44"), D("0.45")]
    assert b.ask_levels()[0].size == D(20)  # type: ignore[index]
    assert not b.delta("ask", D("0.43"), D(5), 13)  # gap
    assert b.ask_levels() is None and b.gaps == 1
    assert not b.delta("ask", D("0.43"), D(5), 14)
    b.snapshot([(D("0.46"), D(10))], [], sequence=20)
    assert b.ask_levels() is not None
    assert b.delta("ask", D("0.46"), D(0), 21) and b.ask_levels() == ()


def test_polymarket_ws_messages() -> None:
    books: dict[str, BookState] = {}
    assert (
        apply_ws_message(
            {
                "event_type": "price_change",
                "price_changes": [{"asset_id": "a", "price": "0.4", "size": "1", "side": "SELL"}],
            },
            books,
        )
        == set()
    )  # no snapshot yet
    apply_ws_message(
        {"event_type": "book", "asset_id": "a", "asks": [{"price": "0.45", "size": "10"}], "bids": []}, books
    )
    apply_ws_message(
        {
            "event_type": "price_change",
            "price_changes": [
                {"asset_id": "a", "price": "0.44", "size": "5", "side": "SELL"},
                {"asset_id": "a", "price": "0.45", "size": "0", "side": "SELL"},
            ],
        },
        books,
    )
    assert [(lv.price, lv.size) for lv in books["a"].ask_levels() or ()] == [(D("0.44"), D(5))]


async def test_http_client_retries_with_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if calls["n"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    c = HttpClient("https://x.test", transport=httpx.MockTransport(handler), backoff=0.001)
    assert await c.get_json("/a") == {"ok": True} and calls["n"] == 3
    await c.aclose()

    c2 = HttpClient("https://x.test", transport=httpx.MockTransport(lambda r: httpx.Response(404)), retries=1)
    with pytest.raises(HttpError) as ei:
        await c2.get_json("/missing", params={"apiKey": "SECRET"})
    assert "SECRET" not in str(ei.value)
    await c2.aclose()


def test_mask_url() -> None:
    assert mask_url("https://a/v4?apiKey=abc123&x=1") == "https://a/v4?apiKey=***&x=1"
