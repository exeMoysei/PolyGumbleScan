"""Price gaps between exchanges (sprint 10, US29–US31, issues #43–#45, owner: Ivan Puzaruk) — SKELETON.

Same rule as the rest of PolyBot: profit is computed after every fee, on the volume really available.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Ticker:
    exchange: str  # "binance", "okx", "jupiter", …
    symbol: str  # "BTC/USDT"
    bid: Decimal
    ask: Decimal
    bid_size: Decimal | None  # unknown stays None
    ask_size: Decimal | None
    at: datetime  # UTC
    taker_fee: Decimal  # fraction, e.g. 0.001


@dataclass(frozen=True, slots=True)
class CryptoGap:
    symbol: str
    buy_on: str
    sell_on: str
    size: Decimal
    profit: Decimal  # after taker fees on both sides and the withdrawal fee
    roi: Decimal


def find_gaps(
    tickers: Sequence[Ticker], withdrawal_fees: dict[tuple[str, str], Decimal], min_roi: Decimal
) -> list[CryptoGap]:
    """Buy-low / sell-high pairs per symbol whose net ROI is at least ``min_roi``, best first."""
    raise NotImplementedError("crypto arbitrage, sprint 10")
