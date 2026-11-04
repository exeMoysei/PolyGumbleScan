"""Turn a solver result into a publishable verdict: signal, candidate (with risk flags) or rejection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from polybot.domain.enums import FreshnessSource, SolveStatus, Verdict
from polybot.domain.legs import Leg
from polybot.domain.solver import Plan, SolveResult


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_profit: Decimal = Decimal("1.00")  # budget currency
    min_roi: Decimal = Decimal("0.005")  # 0.5 %

    def met(self, plan: Plan) -> bool:
        return plan.worst_regular >= self.min_profit and plan.roi >= self.min_roi


@dataclass(frozen=True, slots=True)
class Assessment:
    verdict: Verdict
    plan: Plan | None
    reasons: tuple[str, ...]  # rejection reasons or candidate risk flags


def risk_flags(legs: Sequence[Leg]) -> list[str]:
    flags = []
    if any(not leg.limits_known for leg in legs):
        flags.append("limits_unknown")
    if any(leg.quote.freshness == FreshnessSource.AGGREGATOR for leg in legs):
        flags.append("aggregator_freshness")
    if any(leg.rules.assumed for leg in legs):
        flags.append("rules_assumed")
    return flags


def assess(result: SolveResult, legs: Sequence[Leg], thresholds: Thresholds) -> Assessment:
    if result.status == SolveStatus.SOLVER_LIMIT:
        return Assessment(Verdict.REJECTED, None, ("solver_limit", *result.reasons))
    if result.status != SolveStatus.OK:
        return Assessment(Verdict.REJECTED, None, tuple(result.reasons) or (result.status.value,))

    flags = risk_flags(legs)
    if result.best is not None and thresholds.met(result.best):
        if flags:
            return Assessment(Verdict.CANDIDATE, result.best, tuple(flags))
        return Assessment(Verdict.SIGNAL, result.best, ())

    risky = result.best_risky
    if risky is not None and thresholds.met(risky):
        exc = "exceptional_unknown" if risky.worst_exceptional is None else "exceptional_loss_possible"
        return Assessment(Verdict.CANDIDATE, risky, (exc, *flags))

    plan = result.best or risky
    if plan is not None and plan.worst_regular < 0:
        return Assessment(Verdict.REJECTED, plan, ("negative_pnl",))
    return Assessment(Verdict.REJECTED, plan, ("below_threshold",))
