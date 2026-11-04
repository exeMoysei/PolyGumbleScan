"""Offline adapters that replay JSON fixtures through the *real* parsers (used by tests, demo, CI)."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polybot.adapters.base import Catalog
from polybot.adapters.kalshi.adapter import CAPABILITIES as K_CAPS
from polybot.adapters.kalshi.adapter import parse_events as k_events
from polybot.adapters.kalshi.adapter import parse_orderbook
from polybot.adapters.odds_api.adapter import CAPABILITIES as O_CAPS
from polybot.adapters.odds_api.adapter import parse_odds
from polybot.adapters.polymarket.adapter import CAPABILITIES as P_CAPS
from polybot.adapters.polymarket.adapter import parse_book
from polybot.adapters.polymarket.adapter import parse_events as p_events
from polybot.domain.models import ProviderEvent, ProviderMarket, Quote


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _restamp(quotes: list[Quote], now: datetime | None) -> list[Quote]:
    if now is None:
        return quotes
    return [replace(q, source_at=now, received_at=now) for q in quotes]


class _Clock:
    """Fixed ``now`` for tests; ``live`` restamps quotes with the wall clock and shifts event dates by whole
    days so that the fixture games are always in the future (staging smoke tests on the VPS)."""

    def __init__(self, now: datetime | None, live: bool) -> None:
        self.fixed, self.live = now, live

    def now(self) -> datetime | None:
        return datetime.now(UTC) if self.live else self.fixed

    # first exact-time game in the bundled fixtures; every adapter shifts by the same whole number of days
    ANCHOR = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)

    def shift(self, events: list[ProviderEvent]) -> list[ProviderEvent]:
        if not self.live or not events:
            return events
        days = max(0, math.ceil((datetime.now(UTC) + timedelta(hours=3) - self.ANCHOR) / timedelta(days=1)))
        return [replace(e, start_at=e.start_at + timedelta(days=days)) for e in events]


class FixturePolymarket:
    id = "polymarket"
    capabilities = P_CAPS

    def __init__(self, root: Path, leagues: list[str], now: datetime | None = None, live: bool = False) -> None:
        self.root, self.leagues, self.clock = root / "polymarket", leagues, _Clock(now, live)
        self.books: dict[str, dict[str, Any]] = {}

    async def discover(self) -> Catalog:
        cat = Catalog()
        for lg in self.leagues:
            f = self.root / f"events_{lg}.json"
            if f.exists():
                part = p_events(_load(f)["events"], lg)
                cat.events += part.events
                cat.markets += part.markets
                cat.venues = part.venues
        cat.events = self.clock.shift(cat.events)
        bf = self.root / "books.json"
        if bf.exists():
            self.books = {b["asset_id"]: b for b in _load(bf)["books"]}
        return cat

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        now = self.clock.now()
        out = [
            parse_book(self.books[o.external_id], m, now)
            for m in markets
            for o in m.outcomes
            if o.external_id in self.books
        ]
        return _restamp(out, now)

    async def aclose(self) -> None:
        return None


class FixtureKalshi:
    id = "kalshi"
    capabilities = K_CAPS

    def __init__(self, root: Path, leagues: list[str], now: datetime | None = None, live: bool = False) -> None:
        self.root, self.leagues, self.clock = root / "kalshi", leagues, _Clock(now, live)
        self.books: dict[str, dict[str, Any]] = {}

    async def discover(self) -> Catalog:
        cat = Catalog()
        for lg in self.leagues:
            f = self.root / f"events_{lg}.json"
            if f.exists():
                part = k_events(_load(f), lg)
                cat.events += part.events
                cat.markets += part.markets
                cat.venues = part.venues
        cat.events = self.clock.shift(cat.events)
        bf = self.root / "orderbooks.json"
        if bf.exists():
            self.books = _load(bf)["books"]
        return cat

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        out: list[Quote] = []
        for m in markets:
            if m.external_id in self.books:
                out += parse_orderbook(self.books[m.external_id], m, self.clock.now())
        return _restamp(out, self.clock.now())

    async def aclose(self) -> None:
        return None


class FixtureOddsApi:
    id = "oddsapi"
    capabilities = O_CAPS

    def __init__(
        self, root: Path, leagues: list[str], now: datetime | None = None, region: str = "eu", live: bool = False
    ) -> None:
        self.root, self.leagues, self.clock, self.region = root / "oddsapi", leagues, _Clock(now, live), region
        self._quotes: list[Quote] = []

    async def discover(self) -> Catalog:
        cat = Catalog()
        for lg in self.leagues:
            f = self.root / f"odds_{lg}.json"
            if f.exists():
                part = parse_odds(_load(f)["data"], lg, self.region, received_at=self.clock.now(), currency="USD")
                cat.events += part.events
                cat.markets += part.markets
                cat.venues += part.venues
                cat.quotes += part.quotes
        self._quotes = _restamp(cat.quotes, self.clock.now())
        cat.quotes = self._quotes
        cat.events = self.clock.shift(cat.events)
        return cat

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]:
        ids = {m.external_id for m in markets}
        return [q for q in self._quotes if q.market_external_id in ids]

    async def aclose(self) -> None:
        return None


def fixture_adapters(root: Path, leagues: list[str], now: datetime | None = None, live: bool = False) -> list[Any]:
    return [
        FixturePolymarket(root, leagues, now, live),
        FixtureKalshi(root, leagues, now, live),
        FixtureOddsApi(root, leagues, now, live=live),
    ]
