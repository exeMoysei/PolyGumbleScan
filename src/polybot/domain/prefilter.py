"""Fast pre-selection for the linear two/three-outcome case: S = Σ 1/dᵢ.

Valid only when the legs partition the regular scenarios (each wins in exactly one, no pushes). It
uses top-of-book prices incl. fees, which is a lower bound of the real cost, so ``S >= 1`` safely
proves there is no arbitrage. ``S < 1`` only makes a *preliminary* candidate: the solver decides.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from polybot.domain.enums import ScenarioKind
from polybot.domain.legs import Leg
from polybot.domain.models import Scenario


@dataclass(frozen=True, slots=True)
class Prefilter:
    applicable: bool
    implied_sum: Decimal | None

    @property
    def passes(self) -> bool:
        return not self.applicable or (self.implied_sum is not None and self.implied_sum < 1)


def is_linear_partition(legs: Sequence[Leg], scenarios: Sequence[Scenario]) -> bool:
    regular = {s.id for s in scenarios if s.kind == ScenarioKind.REGULAR}
    seen: set[str] = set()
    for leg in legs:
        if leg.selection.pushes or leg.selection.undefined & regular:
            return False
        if seen & leg.selection.wins:
            return False
        seen |= leg.selection.wins
    return seen == regular


def implied_sum(legs: Sequence[Leg]) -> Decimal | None:
    total = Decimal(0)
    for leg in legs:
        c = leg.effective_unit_cost()
        if c is None:
            return None
        total += c
    return total


def prefilter(legs: Sequence[Leg], scenarios: Sequence[Scenario]) -> Prefilter:
    if not is_linear_partition(legs, scenarios):
        return Prefilter(False, None)
    return Prefilter(True, implied_sum(legs))


def ideal_stakes(decimal_odds: Sequence[Decimal], budget: Decimal) -> tuple[list[Decimal], Decimal]:
    """Textbook equal-payout stakes xᵢ = B / (S·dᵢ); returns (stakes, payout B/S). Before costs."""
    s = sum((1 / d for d in decimal_odds), Decimal(0))
    return [budget / (s * d) for d in decimal_odds], budget / s
