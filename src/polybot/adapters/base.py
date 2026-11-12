from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from polybot.domain.models import Capabilities, ProviderEvent, ProviderMarket, Quote, Venue


@dataclass(slots=True)
class Catalog:
    events: list[ProviderEvent] = field(default_factory=list)
    markets: list[ProviderMarket] = field(default_factory=list)
    venues: list[Venue] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)  # adapters whose discovery also returns prices
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None


@dataclass(slots=True)
class ProbeReport:
    provider: str
    ok: bool
    events: int = 0
    markets: int = 0
    quotes: int = 0
    quotes_with_depth: int = 0
    quotes_with_limits: int = 0
    latency_ms: float | None = None
    quota: dict[str, str] = field(default_factory=dict)
    error: str | None = None


QuoteCallback = Callable[[Quote], Awaitable[None]]


class Adapter(Protocol):
    id: str
    capabilities: Capabilities

    async def discover(self) -> Catalog: ...

    async def snapshot(self, markets: list[ProviderMarket]) -> list[Quote]: ...

    async def aclose(self) -> None: ...


class StreamingAdapter(Adapter, Protocol):
    async def stream(self, markets: list[ProviderMarket], on_quote: QuoteCallback) -> None: ...
