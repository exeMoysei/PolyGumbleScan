"""Casino alert rules (US10, owner: Mikhailo Ivanyshyn) — SKELETON: signatures agreed, bodies to be written.

Pure functions only (no network): they decide which casino bets are worth an alert.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CasinoBet:
    casino: str  # e.g. a contract address or a casino id
    player: str  # wallet address or public nickname
    game: str
    amount: Decimal  # stake, in ``currency``
    payout: Decimal  # 0 when the bet lost
    currency: str
    at: datetime  # UTC
    tx_hash: str | None = None

    @property
    def is_win(self) -> bool:
        return self.payout > self.amount


@dataclass(frozen=True, slots=True)
class CasinoRule:
    min_bet: Decimal = Decimal("10000")  # alert on a stake of at least this much …
    min_win: Decimal = Decimal("25000")  # … or a payout of at least this much
    watched_players: frozenset[str] = frozenset()  # empty = everybody


def is_big_bet(bet: CasinoBet, rule: CasinoRule) -> bool:
    """True when the bet is large enough (stake or payout) and the player is watched."""
    raise NotImplementedError("US10")


def alerts_for(bets: Iterable[CasinoBet], rule: CasinoRule) -> list[CasinoBet]:
    """Bets that should become alerts, biggest first, without duplicates (same tx hash)."""
    raise NotImplementedError("US10")
