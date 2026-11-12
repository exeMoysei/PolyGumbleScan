"""Cross-venue event matching.

Steps: resolve both participants of every provider event to stable team ids, group by
(league, unordered team pair), then cluster by start time. Venue events that only publish a date
(e.g. Kalshi tickers) attach to the single exact-time cluster on that local date; doubleheaders
without a game number are left for review.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from polybot.domain.models import ProviderEvent, StartPrecision
from polybot.matching.normalize import split_matchup
from polybot.matching.teams import Resolution, ResolveMethod, TeamRegistry

LEAGUE_TZ: dict[str, str] = {
    "nba": "America/New_York",
    "nfl": "America/New_York",
    "nhl": "America/New_York",
    "mlb": "America/New_York",
    "epl": "Europe/London",
}

DEFAULT_WINDOW = timedelta(hours=3)


def league_date(league: str, at: datetime) -> date:
    return at.astimezone(ZoneInfo(LEAGUE_TZ.get(league, "UTC"))).date()


@dataclass(frozen=True, slots=True)
class ResolvedEvent:
    event: ProviderEvent
    first: Resolution
    second: Resolution
    home_id: str | None
    away_id: str | None
    issues: tuple[str, ...] = ()

    @property
    def teams(self) -> frozenset[str]:
        return frozenset({self.first.team.id, self.second.team.id})

    @property
    def provider(self) -> str:
        return self.event.provider

    @property
    def strong(self) -> bool:
        return self.first.strong and self.second.strong

    def local_date(self) -> date:
        if self.event.start_precision == StartPrecision.DATE:
            return self.event.start_at.astimezone(ZoneInfo(self.event.date_tz)).date()
        return league_date(self.event.league, self.event.start_at)


@dataclass(frozen=True, slots=True)
class Unresolved:
    event: ProviderEvent
    reason: str


def _participants(ev: ProviderEvent) -> tuple[list[str], str | None]:
    if len(ev.participants) == 2:
        return list(ev.participants), None
    parsed = split_matchup(ev.title)
    if parsed:
        left, right, kind = parsed
        return [left, right], kind
    return [], None


def resolve_event(ev: ProviderEvent, registry: TeamRegistry) -> ResolvedEvent | Unresolved:
    names, sep_kind = _participants(ev)
    if len(names) != 2:
        return Unresolved(ev, "cannot_parse_participants")
    issues: list[str] = []
    resolved: list[Resolution] = []
    for i, name in enumerate(names):
        res = registry.resolve(ev.league, name)
        code = ev.abbreviations[i] if i < len(ev.abbreviations) else None
        by_code = registry.resolve_code(ev.league, code) if code else None
        if res is None and by_code is not None:
            res = Resolution(by_code, ResolveMethod.CODE, 100.0)
        if res is None:
            return Unresolved(ev, f"unknown_team:{name}")
        if by_code is not None and by_code.id != res.team.id:
            issues.append(f"code_name_conflict:{code}:{name}")
        resolved.append(res)
    first, second = resolved
    if first.team.id == second.team.id:
        return Unresolved(ev, "same_team_twice")
    home_id = away_id = None
    if ev.home and ev.away:
        h = registry.resolve(ev.league, ev.home)
        a = registry.resolve(ev.league, ev.away)
        if h and a and {h.team.id, a.team.id} == {first.team.id, second.team.id}:
            home_id, away_id = h.team.id, a.team.id
        else:
            issues.append("roles_unresolved")
    elif sep_kind == "at":
        away_id, home_id = first.team.id, second.team.id
    for r in resolved:
        if not r.strong:
            issues.append(f"fuzzy_team:{r.team.id}:{r.score:.0f}")
    return ResolvedEvent(ev, first, second, home_id, away_id, tuple(issues))


@dataclass
class EventCluster:
    league: str
    sport: str
    teams: frozenset[str]
    start_at: datetime
    start_exact: bool
    members: list[ResolvedEvent] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    game_number: int | None = None
    id: str = ""

    @property
    def providers(self) -> set[str]:
        return {m.provider for m in self.members}

    @property
    def local_date(self) -> date:
        return league_date(self.league, self.start_at)

    def roles(self) -> tuple[str, str, bool]:
        """(home, away, known). Majority vote of members that state roles."""
        votes: dict[tuple[str, str], int] = defaultdict(int)
        for m in self.members:
            if m.home_id and m.away_id:
                votes[(m.home_id, m.away_id)] += 1
        if not votes:
            a, b = sorted(self.teams)
            return a, b, False
        ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
        (home, away), _ = ranked[0]
        return home, away, True

    @property
    def confidence(self) -> float:
        score = 1.0
        for r in self.reasons:
            if r.startswith("fuzzy_team"):
                score -= 0.2
            elif r.startswith("start_diff_major"):
                score -= 0.25
            elif r.startswith("start_diff"):
                score -= 0.1
            elif r == "date_only_match":
                score -= 0.05
            elif r == "role_conflict":
                score -= 0.2
            elif r.startswith("ambiguous"):
                score -= 0.4
            elif r.startswith("code_name_conflict"):
                score -= 0.3
            else:
                score -= 0.1
        return max(0.0, round(score, 2))

    @property
    def strong(self) -> bool:
        return self.confidence >= 0.9 and all(m.strong for m in self.members)


def _close_enough(a: datetime, b: datetime, window: timedelta) -> bool:
    return abs(a - b) <= window


def cluster_events(
    resolved: list[ResolvedEvent],
    window: timedelta = DEFAULT_WINDOW,
) -> list[EventCluster]:
    groups: dict[tuple[str, frozenset[str]], list[ResolvedEvent]] = defaultdict(list)
    for r in resolved:
        groups[(r.event.league, r.teams)].append(r)

    out: list[EventCluster] = []
    for (league, teams), members in groups.items():
        exact = sorted(
            (m for m in members if m.event.start_precision == StartPrecision.EXACT), key=lambda m: m.event.start_at
        )
        dated = [m for m in members if m.event.start_precision == StartPrecision.DATE]
        clusters: list[EventCluster] = []
        for m in exact:
            options = [
                c
                for c in clusters
                if m.provider not in c.providers and _close_enough(c.start_at, m.event.start_at, window)
            ]
            if options:
                c = min(options, key=lambda c: abs(c.start_at - m.event.start_at))
                c.members.append(m)
            else:
                clusters.append(EventCluster(league, m.event.sport, teams, m.event.start_at, True, [m]))
        for m in dated:
            same_day = [c for c in clusters if c.start_exact and c.local_date == m.local_date()]
            if m.event.game_number and len(same_day) >= m.event.game_number:
                target = sorted(same_day, key=lambda c: c.start_at)[m.event.game_number - 1]
                if m.provider not in target.providers:
                    target.members.append(m)
                    target.reasons.append("date_only_match")
                    continue
            free = [c for c in same_day if m.provider not in c.providers]
            if len(same_day) == 1 and free:
                free[0].members.append(m)
                free[0].reasons.append("date_only_match")
                continue
            c = EventCluster(league, m.event.sport, teams, m.event.start_at, False, [m])
            if len(same_day) > 1:
                c.reasons.append("ambiguous_doubleheader")
            clusters.append(c)
        _finalize(league, teams, clusters)
        out.extend(clusters)
    return out


def _finalize(league: str, teams: frozenset[str], clusters: list[EventCluster]) -> None:
    by_day: dict[date, list[EventCluster]] = defaultdict(list)
    for c in clusters:
        by_day[c.local_date].append(c)
        exact_starts = [m.event.start_at for m in c.members if m.event.start_precision == StartPrecision.EXACT]
        if len(exact_starts) > 1:
            spread = max(exact_starts) - min(exact_starts)
            minutes = int(spread.total_seconds() // 60)
            if spread > timedelta(hours=1):
                c.reasons.append(f"start_diff_major:{minutes}m")
            elif spread > timedelta(minutes=5):
                c.reasons.append(f"start_diff:{minutes}m")
            c.start_at = min(exact_starts)
        votes = {(m.home_id, m.away_id) for m in c.members if m.home_id and m.away_id}
        if len(votes) > 1:
            c.reasons.append("role_conflict")
        for m in c.members:
            c.reasons.extend(i for i in m.issues if i != "roles_unresolved")
    for day, cs in by_day.items():
        exact = sorted((c for c in cs if c.start_exact), key=lambda c: c.start_at)
        for n, c in enumerate(exact, start=1):
            game_numbers = {m.event.game_number for m in c.members if m.event.game_number}
            c.game_number = next(iter(game_numbers)) if len(game_numbers) == 1 else (n if len(exact) > 1 else None)
            c.id = canonical_event_id(league, day, teams, c.game_number)
        for c in cs:
            if c.start_exact:
                continue
            c.game_number = c.members[0].event.game_number
            c.id = canonical_event_id(league, day, teams, c.game_number)
            if len(exact) > 0 or (c.game_number is None and len(cs) > 1):
                # no exact-time anchor matched: keep it separate and visibly provisional
                c.id += f"-tbd-{short_hash(*sorted(m.provider + m.event.external_id for m in c.members))}"


def canonical_event_id(league: str, day: date, teams: frozenset[str], game_number: int | None) -> str:
    codes = "-".join(sorted(t.split(":", 1)[1] for t in teams))
    suffix = f"-g{game_number}" if game_number else ""
    return f"{league}-{day:%Y%m%d}-{codes}{suffix}"


def short_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def match(
    events: list[ProviderEvent], registry: TeamRegistry, window: timedelta = DEFAULT_WINDOW
) -> tuple[list[EventCluster], list[Unresolved]]:
    resolved: list[ResolvedEvent] = []
    unresolved: list[Unresolved] = []
    for ev in events:
        r = resolve_event(ev, registry)
        if isinstance(r, Unresolved):
            unresolved.append(r)
        else:
            resolved.append(r)
    return cluster_events(resolved, window), unresolved
