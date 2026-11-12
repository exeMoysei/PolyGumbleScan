"""Order book state for streaming feeds: snapshot + deltas, invalid after a sequence gap."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from polybot.domain.models import PriceLevel


@dataclass(slots=True)
class BookState:
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    sequence: int | None = None
    valid: bool = False
    gaps: int = 0

    def snapshot(
        self, asks: list[tuple[Decimal, Decimal]], bids: list[tuple[Decimal, Decimal]], sequence: int | None = None
    ) -> None:
        self.asks = {p: s for p, s in asks if s > 0}
        self.bids = {p: s for p, s in bids if s > 0}
        self.sequence = sequence
        self.valid = True

    def delta(self, side: str, price: Decimal, size: Decimal, sequence: int | None = None) -> bool:
        """Apply one level change. Returns False (and invalidates the book) on a sequence gap."""
        if not self.valid:
            return False
        if sequence is not None and self.sequence is not None:
            if sequence <= self.sequence:
                return True  # duplicate / late delta: ignore
            if sequence != self.sequence + 1:
                self.valid = False
                self.gaps += 1
                return False
        if sequence is not None:
            self.sequence = sequence
        book = self.asks if side == "ask" else self.bids
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size
        return True

    def ask_levels(self) -> tuple[PriceLevel, ...] | None:
        if not self.valid:
            return None
        return tuple(PriceLevel(p, s) for p, s in sorted(self.asks.items()))

    def bid_levels(self) -> tuple[PriceLevel, ...] | None:
        if not self.valid:
            return None
        return tuple(PriceLevel(p, s) for p, s in sorted(self.bids.items(), reverse=True))
