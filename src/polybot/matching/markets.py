"""Market mapping: canonical market key, outcome -> selection mapping, rules checks and invalidation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from polybot.domain.enums import MappingStatus, MarketType, Period, SettlementPolicy
from polybot.domain.models import ProviderMarket, ProviderOutcome, Selection
from polybot.domain.scenarios import ScenarioSpace, UnsupportedMarket, build_space
from polybot.matching.events import EventCluster
from polybot.matching.teams import TeamRegistry

DRAW_WORDS = {"draw", "tie", "x"}


def canonical_market_key(event_id: str, market_type: MarketType, period: Period, line: Decimal | None) -> str:
    line_part = "" if line is None else f"|{line.normalize():f}"
    return f"{event_id}|{market_type.value}|{period.value}{line_part}"


@dataclass(frozen=True, slots=True)
class CanonicalOutcome:
    outcome: ProviderOutcome
    selection: Selection


@dataclass(frozen=True, slots=True)
class MarketProposal:
    market: ProviderMarket
    event_id: str
    canonical_market_key: str
    space: ScenarioSpace | None
    outcomes: tuple[CanonicalOutcome, ...]
    status: MappingStatus
    reasons: tuple[str, ...]
    rules_version: str
    params: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return params_fingerprint(self.params)


def params_fingerprint(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


def market_params(market: ProviderMarket, cluster: EventCluster) -> dict[str, Any]:
    return {
        "event": cluster.id,
        "teams": sorted(cluster.teams),
        "start": cluster.start_at.replace(second=0, microsecond=0).isoformat(),
        "type": market.market_type.value,
        "period": market.period.value,
        "line": None if market.line is None else f"{market.line.normalize():f}",
        "unit": market.line_unit,
    }


def rules_issues(market: ProviderMarket, space: ScenarioSpace | None) -> list[str]:
    r = market.rules
    issues: list[str] = []
    if market.period == Period.UNKNOWN or r.period == Period.UNKNOWN:
        issues.append("period_unknown")
    if r.period != Period.UNKNOWN and r.period != market.period:
        issues.append("period_rules_conflict")
    if r.includes_overtime is True and market.period == Period.REGULATION:
        issues.append("overtime_conflict")
    if r.includes_overtime is False and market.period == Period.FULL_GAME and space and not space.has_draw():
        issues.append("overtime_conflict")
    if r.on_cancel == SettlementPolicy.UNKNOWN:
        issues.append("rules_cancel_unknown")
    if r.on_postpone == SettlementPolicy.UNKNOWN:
        issues.append("rules_postpone_unknown")
    if (
        space is not None
        and market.market_type == MarketType.MONEYLINE
        and space.has_draw()
        and r.on_draw == SettlementPolicy.UNKNOWN
    ):
        issues.append("rules_tie_unknown")
    if r.assumed:
        issues.append("rules_assumed_default")
    return issues


def map_outcome(outcome: ProviderOutcome, space: ScenarioSpace, league: str, registry: TeamRegistry) -> Selection | str:
    subject = outcome.subject.strip()
    low = subject.lower()
    if space.market_type == MarketType.TOTAL:
        if low.startswith("over"):
            return space.under() if outcome.negated else space.over()
        if low.startswith("under"):
            return space.over() if outcome.negated else space.under()
        return f"unknown_total_outcome:{subject}"
    if low in DRAW_WORDS:
        if not space.has_draw():
            return "draw_outcome_in_no_draw_space"
        return space.not_draw() if outcome.negated else space.draw()
    res = registry.resolve(league, subject)
    if res is None:
        return f"unknown_outcome_team:{subject}"
    if res.team.id not in space.teams:
        return f"outcome_team_not_in_event:{res.team.id}"
    if not res.strong:
        return f"fuzzy_outcome_team:{res.team.id}"
    label = res.team.name
    if outcome.negated:
        return space.not_team_win(res.team.id, f"Not {label}")
    return space.team_win(res.team.id, label)


def map_market(market: ProviderMarket, cluster: EventCluster, registry: TeamRegistry) -> MarketProposal:
    home, away, _ = cluster.roles()
    reasons: list[str] = []
    space: ScenarioSpace | None = None
    params = market_params(market, cluster)
    key = canonical_market_key(cluster.id, market.market_type, market.period, market.line)
    labels = {t: registry.teams[t].name for t in (home, away) if t in registry.teams}
    try:
        space = build_space(cluster.sport, market.market_type, market.period, (home, away), market.line, labels)
    except UnsupportedMarket as exc:
        return MarketProposal(
            market,
            cluster.id,
            key,
            None,
            (),
            MappingStatus.REJECTED,
            (f"unsupported:{exc}",),
            market.rules.version,
            params,
        )
    outcomes: list[CanonicalOutcome] = []
    for o in market.outcomes:
        sel = map_outcome(o, space, cluster.league, registry)
        if isinstance(sel, str):
            reasons.append(sel)
        else:
            outcomes.append(CanonicalOutcome(o, sel))
    reasons.extend(rules_issues(market, space))
    reasons.extend(r for r in cluster.reasons if r != "date_only_match")
    if not cluster.strong:
        reasons.append(f"event_confidence:{cluster.confidence}")
    status = MappingStatus.NEEDS_REVIEW if reasons else MappingStatus.PENDING
    return MarketProposal(
        market,
        cluster.id,
        key,
        space,
        tuple(outcomes),
        status,
        tuple(dict.fromkeys(reasons)),
        market.rules.version,
        params,
    )


def compatibility_issues(a: ProviderMarket, b: ProviderMarket) -> list[str]:
    """Why two markets on the same event cannot be combined."""
    issues = []
    if a.market_type != b.market_type:
        issues.append("market_type_mismatch")
    if a.period != b.period:
        issues.append("period_mismatch")
    if a.line != b.line:
        issues.append("line_mismatch")
    if (a.line_unit or None) != (b.line_unit or None):
        issues.append("unit_mismatch")
    if (
        a.rules.includes_overtime is not None
        and b.rules.includes_overtime is not None
        and a.rules.includes_overtime != b.rules.includes_overtime
    ):
        issues.append("overtime_mismatch")
    return issues


@dataclass(frozen=True, slots=True)
class Revalidation:
    status: MappingStatus
    reason: str | None


def revalidate(
    status: MappingStatus,
    approved_rules_version: str | None,
    approved_params: dict[str, Any] | None,
    proposal: MarketProposal,
) -> Revalidation:
    """An approval is tied to the rules version and key parameters; any change resets it."""
    if status != MappingStatus.APPROVED:
        return Revalidation(status, None)
    if approved_rules_version != proposal.rules_version:
        return Revalidation(MappingStatus.INVALIDATED, "rules_changed")
    if approved_params is not None:
        changed = sorted(
            k for k in set(approved_params) | set(proposal.params) if approved_params.get(k) != proposal.params.get(k)
        )
        if changed:
            return Revalidation(MappingStatus.INVALIDATED, "params_changed:" + ",".join(changed))
    return Revalidation(MappingStatus.APPROVED, None)
