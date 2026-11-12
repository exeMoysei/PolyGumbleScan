"""Exact Decimal solver for small (2–3 leg) covering combinations.

Algorithm (MVP, linear payouts per leg):
1. Pick the anchor leg with the fewest admissible sizes inside the budget.
2. For every admissible anchor size, size every other leg so that its winning payout matches the
   anchor's winning payout; try the neighbouring admissible sizes (floor/ceil) and the boundaries.
3. Re-price every candidate plan exactly (book walk, fees, rounding, FX) across all scenarios.
4. Keep the plan with the best worst-case regular P&L; ties -> smaller outlay. Plans that lose money in
   an exceptional scenario are kept separately as "risky".
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from polybot.domain.enums import ScenarioKind, SettlementPolicy, SolveStatus
from polybot.domain.legs import Fill, Leg
from polybot.domain.models import Scenario
from polybot.domain.money import ZERO, ceil_step, floor_step


@dataclass(frozen=True, slots=True)
class PlanLeg:
    leg_index: int
    fill: Fill
    cost: Decimal  # budget currency, incl. fees and FX reserve
    cashflows: tuple[tuple[str, Decimal | None], ...]


@dataclass(frozen=True, slots=True)
class Plan:
    legs: tuple[PlanLeg, ...]
    total_cost: Decimal
    pnl: tuple[tuple[str, Decimal | None], ...]
    worst_regular: Decimal
    worst_exceptional: Decimal | None  # None when some exceptional settlement is unknown
    unknown_exceptional: tuple[str, ...]

    @property
    def roi(self) -> Decimal:
        return self.worst_regular / self.total_cost if self.total_cost > 0 else ZERO

    def pnl_of(self, scenario_id: str) -> Decimal | None:
        for sid, v in self.pnl:
            if sid == scenario_id:
                return v
        raise KeyError(scenario_id)

    def exceptional_safe(self, tolerance: Decimal = ZERO) -> bool:
        return self.worst_exceptional is not None and self.worst_exceptional >= -tolerance

    def sort_key(self) -> tuple[Decimal, Decimal]:
        return (self.worst_regular, -self.total_cost)


@dataclass(frozen=True, slots=True)
class SolverConfig:
    max_anchor_points: int = 20_000
    max_evaluations: int = 200_000
    exceptional_tolerance: Decimal = ZERO  # accepted loss in exceptional scenarios for a normal signal


@dataclass(slots=True)
class SolveResult:
    status: SolveStatus
    best: Plan | None = None  # best plan that does not lose in described exceptional scenarios
    best_risky: Plan | None = None  # best plan overall (may lose / be unknown in exceptional ones)
    evaluated: int = 0
    reasons: list[str] = field(default_factory=list)


def coverage_gaps(legs: Sequence[Leg], scenarios: Sequence[Scenario]) -> list[str]:
    """Regular scenarios in which no leg wins or pushes (a guaranteed loss)."""
    gaps = []
    for sc in scenarios:
        if sc.kind != ScenarioKind.REGULAR:
            continue
        if not any(sc.id in leg.selection.wins or sc.id in leg.selection.pushes for leg in legs):
            # a rule-dependent tie may still be covered by venue rules
            if any(sc.id in leg.selection.undefined for leg in legs):
                continue
            gaps.append(sc.id)
    return gaps


def evaluate(legs: Sequence[Leg], sizes: Sequence[Decimal], scenarios: Sequence[Scenario]) -> Plan | None:
    plan_legs: list[PlanLeg] = []
    total = ZERO
    for i, (leg, size) in enumerate(zip(legs, sizes, strict=True)):
        fill = leg.fill(size)
        if fill is None:
            return None
        cost = leg.to_budget_cost(fill.total_native)
        flows = tuple((sc.id, leg.cashflow(fill, sc)) for sc in scenarios)
        plan_legs.append(PlanLeg(i, fill, cost, flows))
        total += cost
    pnl: list[tuple[str, Decimal | None]] = []
    worst_reg: Decimal | None = None
    worst_exc: Decimal | None = None
    unknown_exc: list[str] = []
    deferred: list[tuple[int, Scenario]] = []
    for j, sc in enumerate(scenarios):
        income = ZERO
        unknown = False
        carried = [legs[pl.leg_index].policy(sc) == SettlementPolicy.CARRY for pl in plan_legs]
        if all(carried):
            # every position survives the postponement: the regular scenarios still decide
            pnl.append((sc.id, None))
            deferred.append((j, sc))
            continue
        for pl, carry in zip(plan_legs, carried, strict=True):
            if carry:
                continue  # worst case: the surviving position loses after the other side was voided
            v = pl.cashflows[j][1]
            if v is None:
                unknown = True
                break
            income += v
        if unknown:
            pnl.append((sc.id, None))
            if sc.kind == ScenarioKind.REGULAR:
                return None  # cannot price a regular scenario: not a valid plan
            unknown_exc.append(sc.id)
            continue
        value = income - total
        pnl.append((sc.id, value))
        if sc.kind == ScenarioKind.REGULAR:
            worst_reg = value if worst_reg is None else min(worst_reg, value)
        else:
            worst_exc = value if worst_exc is None else min(worst_exc, value)
    if worst_reg is None:
        return None
    for j, sc in deferred:
        pnl[j] = (sc.id, worst_reg)
        worst_exc = worst_reg if worst_exc is None else min(worst_exc, worst_reg)
    if unknown_exc:
        worst_exc = None
    return Plan(tuple(plan_legs), total, tuple(pnl), worst_reg, worst_exc, tuple(unknown_exc))


def _grid_count(leg: Leg, upper: Decimal) -> int:
    if upper < leg.min_size:
        return 0
    return int((floor_step(upper - leg.min_size, leg.step)) / leg.step) + 1


def _upper_for_budget(leg: Leg, budget: Decimal) -> Decimal:
    price = leg.quote.best_price
    if price is None or price <= 0:
        return ZERO
    native_budget = budget if leg.fx is None else budget / leg.fx.rate
    upper = native_budget / price if leg.is_prediction else native_budget
    cap = leg.upper_size()
    if cap is not None:
        upper = min(upper, cap)
    return floor_step(upper, leg.step)


def _win_scenario(leg: Leg, scenarios: Sequence[Scenario]) -> Scenario | None:
    for sc in scenarios:
        if sc.kind == ScenarioKind.REGULAR and sc.id in leg.selection.wins:
            return sc
    return None


def _candidates(leg: Leg, target: Decimal, upper: Decimal) -> list[Decimal]:
    x = leg.size_for_payout(target)
    out = {floor_step(x, leg.step), ceil_step(x, leg.step), leg.min_size}
    cap = leg.upper_size()
    res = []
    for c in out:
        if c < leg.min_size:
            c = leg.min_size
        if cap is not None and c > cap:
            c = floor_step(cap, leg.step)
        if c > upper:
            continue
        res.append(c)
    return sorted(set(res))


def solve(
    legs: Sequence[Leg],
    scenarios: Sequence[Scenario],
    budget: Decimal,
    config: SolverConfig | None = None,
) -> SolveResult:
    cfg = config or SolverConfig()
    if len(legs) < 2:
        return SolveResult(SolveStatus.UNSUPPORTED, reasons=["need_at_least_two_legs"])
    gaps = coverage_gaps(legs, scenarios)
    if gaps:
        return SolveResult(SolveStatus.NO_PLAN, reasons=[f"uncovered_scenario:{g}" for g in gaps])
    for leg in legs:
        if leg.quote.best_price is None:
            return SolveResult(SolveStatus.NO_PLAN, reasons=["empty_book"])
        if _win_scenario(leg, scenarios) is None:
            return SolveResult(SolveStatus.UNSUPPORTED, reasons=["leg_without_winning_scenario"])

    uppers = [_upper_for_budget(leg, budget) for leg in legs]
    counts = [_grid_count(leg, up) for leg, up in zip(legs, uppers, strict=True)]
    if min(counts) == 0:
        return SolveResult(SolveStatus.NO_PLAN, reasons=["budget_below_min_size"])
    anchor = min(range(len(legs)), key=lambda i: counts[i])
    if counts[anchor] > cfg.max_anchor_points:
        return SolveResult(SolveStatus.SOLVER_LIMIT, reasons=[f"anchor_points:{counts[anchor]}"])

    a_leg = legs[anchor]
    a_win = _win_scenario(a_leg, scenarios)
    assert a_win is not None
    others = [i for i in range(len(legs)) if i != anchor]

    best: Plan | None = None
    best_risky: Plan | None = None
    evaluated = 0
    size = a_leg.min_size
    while size <= uppers[anchor]:
        a_fill = a_leg.fill(size)
        if a_fill is None:
            break  # deeper sizes cannot be filled either
        if a_leg.to_budget_cost(a_fill.total_native) > budget:
            break
        target = a_leg.cashflow(a_fill, a_win)
        assert target is not None
        options = [_candidates(legs[i], target, uppers[i]) for i in others]
        for combo in itertools.product(*options):
            evaluated += 1
            if evaluated > cfg.max_evaluations:
                return SolveResult(SolveStatus.SOLVER_LIMIT, best, best_risky, evaluated, ["max_evaluations"])
            sizes: list[Decimal] = [ZERO] * len(legs)
            sizes[anchor] = size
            for i, s in zip(others, combo, strict=True):
                sizes[i] = s
            plan = evaluate(legs, sizes, scenarios)
            if plan is None or plan.total_cost > budget:
                continue
            if best_risky is None or plan.sort_key() > best_risky.sort_key():
                best_risky = plan
            if plan.exceptional_safe(cfg.exceptional_tolerance) and (best is None or plan.sort_key() > best.sort_key()):
                best = plan
        size += a_leg.step

    if best is None and best_risky is None:
        return SolveResult(SolveStatus.NO_PLAN, evaluated=evaluated, reasons=["no_feasible_plan"])
    return SolveResult(SolveStatus.OK, best, best_risky, evaluated)
