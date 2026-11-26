"""Arbitrage inside one Polymarket multi-outcome event (US3): buy YES on every outcome when the YES prices add up
to less than 1.

Only "negative risk" events qualify: their outcomes are mutually exclusive and exhaustive, so exactly one YES pays
1 USDC. Events whose outcome list can still grow (``negRiskAugmented``) are skipped, because a new outcome could
win and every bought YES would then lose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from polybot.logic.fees import FeeModel
from polybot.logic.models import PriceLevel
from polybot.logic.money import ZERO


@dataclass(frozen=True, slots=True)
class OutcomeBook:
    label: str
    token_id: str
    asks: tuple[PriceLevel, ...]  # best first
    fee: FeeModel
    min_size: Decimal = Decimal(1)


@dataclass(frozen=True, slots=True)
class YesSumPlan:
    event_title: str
    event_url: str
    shares: Decimal  # shares of EVERY outcome; exactly one pays ``shares`` USDC
    cost: Decimal  # all outcomes, fees included
    fees: Decimal
    top_sum: Decimal  # sum of best asks (what the user sees on the site)

    @property
    def payout(self) -> Decimal:
        return self.shares

    @property
    def profit(self) -> Decimal:
        return self.payout - self.cost

    @property
    def roi(self) -> Decimal:
        return self.profit / self.cost if self.cost > 0 else ZERO


def _fill_cost(book: OutcomeBook, shares: Decimal) -> tuple[Decimal, Decimal] | None:
    """(notional, fee) for buying ``shares`` walking the asks; None when the book is too thin."""
    remaining, notional, fills = shares, ZERO, []
    for level in book.asks:
        if remaining <= 0:
            break
        take = min(level.size if level.size is not None else remaining, remaining)
        if take <= 0:
            continue
        fills.append((level.price, take))
        notional += level.price * take
        remaining -= take
    if remaining > 0:
        return None
    return notional, book.fee.entry_fee(fills, notional)


def best_plan(
    title: str,
    url: str,
    books: Sequence[OutcomeBook],
    budget: Decimal,
    step: Decimal = Decimal(1),
    max_steps: int = 5000,
) -> YesSumPlan | None:
    """Most profitable equal number of YES shares on every outcome within ``budget``; None if nothing is profitable."""
    if len(books) < 2 or any(not b.asks for b in books):
        return None
    top_sum = sum((b.asks[0].price for b in books), ZERO)
    if top_sum >= 1:
        return None  # walking the book only gets more expensive
    shares = max(b.min_size for b in books)
    best: YesSumPlan | None = None
    for _ in range(max_steps):
        notional, fees = ZERO, ZERO
        for b in books:
            cost = _fill_cost(b, shares)
            if cost is None:
                return best
            notional += cost[0]
            fees += cost[1]
        total = notional + fees
        if total > budget:
            return best
        plan = YesSumPlan(title, url, shares, total, fees, top_sum)
        if plan.profit > 0 and (best is None or plan.profit > best.profit):
            best = plan
        shares += step
    return best
