"""Scenario spaces: the complete list of ways an event can settle for a canonical market.

Regular scenarios are the normal results of the game. Exceptional ones (cancellation, postponement past
the cut-off) are evaluated separately, because every venue settles them by its own rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.domain.enums import MarketType, Period, ScenarioKind
from polybot.domain.models import Scenario, Selection

CANCELLED = Scenario("cancelled", ScenarioKind.EXCEPTIONAL, "Game cancelled")
POSTPONED = Scenario("postponed", ScenarioKind.EXCEPTIONAL, "Postponed past the cut-off")
EXCEPTIONAL_SCENARIOS: tuple[Scenario, ...] = (CANCELLED, POSTPONED)

DRAW_ID = "draw"


class UnsupportedMarket(ValueError):
    pass


def draw_possible(sport: str, period: Period) -> bool:
    """Can the *game* end level for the given settlement period?"""
    sport = sport.lower()
    if period == Period.REGULATION:
        return True
    if sport in {"soccer", "football_soccer"}:
        # league matches: "full game" for soccer means 90' + stoppage time
        return True
    # NFL regular-season ties exist; basketball, hockey (incl. OT/SO), baseball (extra innings) cannot draw
    return sport in {"american_football"}


def win_id(team_id: str) -> str:
    return f"win:{team_id}"


@dataclass(frozen=True, slots=True)
class ScenarioSpace:
    sport: str
    market_type: MarketType
    period: Period
    teams: tuple[str, str]  # (home, away) canonical team ids
    line: Decimal | None
    regular: tuple[Scenario, ...]
    exceptional: tuple[Scenario, ...] = EXCEPTIONAL_SCENARIOS

    @property
    def all(self) -> tuple[Scenario, ...]:
        return self.regular + self.exceptional

    @property
    def regular_ids(self) -> frozenset[str]:
        return frozenset(s.id for s in self.regular)

    def has_draw(self) -> bool:
        return DRAW_ID in self.regular_ids

    # -------------------------------------------------- selections
    def team_win(self, team_id: str, label: str | None = None) -> Selection:
        self._require_team(team_id)
        undefined = (
            frozenset({DRAW_ID}) if self.has_draw() and self.market_type == MarketType.MONEYLINE else frozenset()
        )
        return Selection(
            key=f"win:{team_id}",
            label=label or team_id,
            wins=frozenset({win_id(team_id)}),
            undefined=undefined,
        )

    def not_team_win(self, team_id: str, label: str | None = None) -> Selection:
        """ "No" on a binary "team wins" contract: every regular scenario except the team winning."""
        self._require_team(team_id)
        undefined = (
            frozenset({DRAW_ID}) if self.has_draw() and self.market_type == MarketType.MONEYLINE else frozenset()
        )
        wins = self.regular_ids - {win_id(team_id)} - undefined
        return Selection(
            key=f"not_win:{team_id}", label=label or f"not {team_id}", wins=wins, undefined=undefined, negated=True
        )

    def draw(self, label: str = "Draw") -> Selection:
        if not self.has_draw():
            raise UnsupportedMarket("draw is impossible in this scenario space")
        return Selection(key="draw", label=label, wins=frozenset({DRAW_ID}))

    def not_draw(self, label: str = "Not a draw") -> Selection:
        if not self.has_draw():
            raise UnsupportedMarket("draw is impossible in this scenario space")
        return Selection(key="not_draw", label=label, wins=self.regular_ids - {DRAW_ID}, negated=True)

    def over(self, label: str | None = None) -> Selection:
        self._require_total()
        pushes = frozenset({"push"}) if "push" in self.regular_ids else frozenset()
        return Selection(
            key=f"over:{self.line}", label=label or f"Over {self.line}", wins=frozenset({"over"}), pushes=pushes
        )

    def under(self, label: str | None = None) -> Selection:
        self._require_total()
        pushes = frozenset({"push"}) if "push" in self.regular_ids else frozenset()
        return Selection(
            key=f"under:{self.line}", label=label or f"Under {self.line}", wins=frozenset({"under"}), pushes=pushes
        )

    def _require_team(self, team_id: str) -> None:
        if team_id not in self.teams:
            raise UnsupportedMarket(f"team {team_id} is not a participant")
        if self.market_type not in (MarketType.MONEYLINE, MarketType.MATCH_RESULT):
            raise UnsupportedMarket("team selections need a winner market")

    def _require_total(self) -> None:
        if self.market_type != MarketType.TOTAL or self.line is None:
            raise UnsupportedMarket("over/under needs a total market with a line")


def build_space(
    sport: str,
    market_type: MarketType,
    period: Period,
    teams: tuple[str, str],
    line: Decimal | None = None,
    team_labels: dict[str, str] | None = None,
) -> ScenarioSpace:
    if period == Period.UNKNOWN:
        raise UnsupportedMarket("settlement period is unknown")
    labels = team_labels or {}
    home, away = teams
    if market_type in (MarketType.MONEYLINE, MarketType.MATCH_RESULT):
        regular = [
            Scenario(win_id(home), ScenarioKind.REGULAR, f"{labels.get(home, home)} win"),
            Scenario(win_id(away), ScenarioKind.REGULAR, f"{labels.get(away, away)} win"),
        ]
        if market_type == MarketType.MATCH_RESULT or draw_possible(sport, period):
            regular.insert(1, Scenario(DRAW_ID, ScenarioKind.REGULAR, "Draw"))
        return ScenarioSpace(sport, market_type, period, teams, None, tuple(regular))
    if market_type == MarketType.TOTAL:
        if line is None:
            raise UnsupportedMarket("total without a line")
        frac = line % 1
        if frac == Decimal("0.5"):
            regular = [
                Scenario("over", ScenarioKind.REGULAR, f"Total > {line}"),
                Scenario("under", ScenarioKind.REGULAR, f"Total < {line}"),
            ]
        elif frac == 0:
            regular = [
                Scenario("over", ScenarioKind.REGULAR, f"Total > {line}"),
                Scenario("push", ScenarioKind.REGULAR, f"Total = {line} (push)"),
                Scenario("under", ScenarioKind.REGULAR, f"Total < {line}"),
            ]
        else:
            raise UnsupportedMarket(f"asian/quarter line {line} is not supported in MVP")
        return ScenarioSpace(sport, market_type, period, teams, line, tuple(regular))
    raise UnsupportedMarket(f"market type {market_type} is not supported in MVP")
