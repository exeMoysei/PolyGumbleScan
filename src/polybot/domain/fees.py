"""Fee models. Entry fees are charged once per fill, settlement deductions once per payout.

All functions work in the leg's native currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from polybot.domain.money import CENT, ZERO, ceil_step

FEE_QUANTUM = Decimal("0.0001")


class FeeModel(Protocol):
    @property
    def name(self) -> str: ...

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        """Fee for buying ``fills`` = [(price, qty), ...]; ``stake`` is the sportsbook stake."""
        ...

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        """Amount withheld from a winning payout (e.g. exchange commission on net winnings)."""
        ...


@dataclass(frozen=True, slots=True)
class NoFee:
    name: str = "none"

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        return ZERO

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        return ZERO


@dataclass(frozen=True, slots=True)
class PolymarketTakerFee:
    """Polymarket taker fee: ``C * p * rate * (p * (1 - p)) ** exponent`` per fill.

    ``rate`` and ``exponent`` are per-market parameters (CLOB market info ``fd = {r, e, to}``).
    Rounded up to 0.0001 USDC per fill (conservative).
    """

    rate: Decimal
    exponent: Decimal = Decimal(1)
    name: str = "polymarket_taker"

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        total = ZERO
        if self.rate == 0:
            return total
        for price, qty in fills:
            base = price * (1 - price)
            factor = base**self.exponent if base > 0 else ZERO
            total += ceil_step(qty * price * self.rate * factor, FEE_QUANTUM)
        return total

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        return ZERO


@dataclass(frozen=True, slots=True)
class KalshiTakerFee:
    """Kalshi trading fee: ``ceil_to_cent(rate * C * P * (1 - P))`` per fill (default rate 0.07)."""

    rate: Decimal = Decimal("0.07")
    name: str = "kalshi_taker"

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        return sum(
            (ceil_step(self.rate * qty * price * (1 - price), CENT) for price, qty in fills if qty > 0),
            ZERO,
        )

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        return ZERO


@dataclass(frozen=True, slots=True)
class StakeFee:
    """Percentage of the stake taken at entry (some sportsbooks / payment fees)."""

    rate: Decimal
    name: str = "stake_fee"

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        return ceil_step(stake * self.rate, CENT)

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        return ZERO


@dataclass(frozen=True, slots=True)
class WinningsCommission:
    """Commission on net winnings (betting exchanges)."""

    rate: Decimal
    name: str = "winnings_commission"

    def entry_fee(self, fills: list[tuple[Decimal, Decimal]], stake: Decimal) -> Decimal:
        return ZERO

    def settlement_deduction(self, gross_payout: Decimal, net_win: Decimal) -> Decimal:
        if net_win <= 0:
            return ZERO
        return ceil_step(net_win * self.rate, CENT)
