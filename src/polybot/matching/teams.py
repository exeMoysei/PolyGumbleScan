"""Team registry and name resolution (raw venue name -> stable team id like ``nba:lal``)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz import fuzz

from polybot.matching.normalize import normalize_name
from polybot.matching.teams_data import LEAGUES, MULTIWORD_NICKNAMES, TEAMS_RAW


class ResolveMethod(StrEnum):
    EXACT = "exact"  # normalized alias match
    CODE = "code"  # venue abbreviation
    CONTAINS = "contains"  # exactly one alias contained in a longer string
    FUZZY = "fuzzy"  # similarity match -> always needs review


@dataclass(frozen=True, slots=True)
class Team:
    id: str  # "nba:lal"
    league: str
    sport: str
    code: str
    name: str
    nickname: str
    city: str


@dataclass(frozen=True, slots=True)
class Resolution:
    team: Team
    method: ResolveMethod
    score: float  # 0..100

    @property
    def strong(self) -> bool:
        return self.method != ResolveMethod.FUZZY


@dataclass
class TeamRegistry:
    teams: dict[str, Team] = field(default_factory=dict)
    aliases: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))  # league->alias->id
    codes: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))  # league->CODE->id
    ambiguous: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    # ------------------------------------------------------------- building
    @classmethod
    def default(cls) -> TeamRegistry:
        reg = cls()
        for league, raw in TEAMS_RAW.items():
            for line in raw.strip().splitlines():
                code, name, extra, codes = [*line.split("|"), "", "", ""][:4]
                reg.add_team(
                    league,
                    code.strip(),
                    name.strip(),
                    [a for a in extra.split(";") if a.strip()],
                    [c for c in codes.split(";") if c.strip()],
                )
        reg._finalize_city_aliases()
        return reg

    def add_team(self, league: str, code: str, name: str, extra_aliases: list[str], extra_codes: list[str]) -> Team:
        sport = LEAGUES.get(league, {}).get("sport", "unknown")
        norm = normalize_name(name)
        words = norm.split()
        nickname = words[-1]
        for multi in MULTIWORD_NICKNAMES:
            if norm.endswith(multi):
                nickname = multi
        city = norm[: -len(nickname)].strip() if norm != nickname else norm
        team = Team(f"{league}:{code.lower()}", league, sport, code.upper(), name, nickname, city)
        self.teams[team.id] = team
        self._add_alias(league, norm, team.id)
        if len(words) > 1:
            self._add_alias(league, nickname, team.id)
        if city and city != norm:
            # Kalshi style: "Los Angeles L", "New York K"
            self._add_alias(league, f"{city} {nickname[0]}", team.id)
        for alias in extra_aliases:
            self._add_alias(league, normalize_name(alias), team.id)
        for c in [code, *extra_codes]:
            self._add_code(league, c.strip().upper(), team.id)
        return team

    def add_alias(self, league: str, alias: str, team_id: str) -> None:
        """Runtime alias (admin-confirmed)."""
        self._add_alias(league, normalize_name(alias), team_id, override=True)

    def _add_alias(self, league: str, alias: str, team_id: str, override: bool = False) -> None:
        if not alias:
            return
        current = self.aliases[league].get(alias)
        if current and current != team_id and not override:
            self.ambiguous[league].add(alias)
            del self.aliases[league][alias]
            return
        if alias in self.ambiguous[league] and not override:
            return
        self.aliases[league][alias] = team_id

    def _add_code(self, league: str, code: str, team_id: str) -> None:
        current = self.codes[league].get(code)
        if current and current != team_id:
            return  # first registration wins for codes (primary codes are listed first)
        self.codes[league][code] = team_id

    def _finalize_city_aliases(self) -> None:
        by_league: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for t in self.teams.values():
            if t.city:
                by_league[t.league][t.city].append(t.id)
        for league, cities in by_league.items():
            for city, ids in cities.items():
                if len(ids) == 1:
                    self._add_alias(league, city, ids[0])

    # ------------------------------------------------------------- lookup
    def by_league(self, league: str) -> list[Team]:
        return [t for t in self.teams.values() if t.league == league]

    def resolve(self, league: str, raw: str) -> Resolution | None:
        if not raw or not raw.strip():
            return None
        aliases = self.aliases.get(league, {})
        norm = normalize_name(raw)
        if norm in aliases:
            return Resolution(self.teams[aliases[norm]], ResolveMethod.EXACT, 100.0)
        code = raw.strip().upper()
        if code in self.codes.get(league, {}) and len(code) <= 5:
            return Resolution(self.teams[self.codes[league][code]], ResolveMethod.CODE, 100.0)
        if norm in self.ambiguous.get(league, set()):
            return None
        contained = self._contained(league, norm)
        if contained is not None:
            return contained
        return self._fuzzy(league, norm)

    def resolve_code(self, league: str, code: str) -> Team | None:
        tid = self.codes.get(league, {}).get(code.strip().upper())
        return self.teams[tid] if tid else None

    def _contained(self, league: str, norm: str) -> Resolution | None:
        padded = f" {norm} "
        hits: dict[str, int] = {}
        for alias, tid in self.aliases.get(league, {}).items():
            if len(alias) < 4:
                continue
            if f" {alias} " in padded:
                hits[tid] = max(hits.get(tid, 0), len(alias))
        if len(hits) == 1:
            tid = next(iter(hits))
            return Resolution(self.teams[tid], ResolveMethod.CONTAINS, 95.0)
        return None

    def _fuzzy(self, league: str, norm: str, threshold: float = 88.0, margin: float = 6.0) -> Resolution | None:
        best: dict[str, float] = {}
        for alias, tid in self.aliases.get(league, {}).items():
            score = max(fuzz.ratio(norm, alias), fuzz.token_sort_ratio(norm, alias))
            if score > best.get(tid, 0.0):
                best[tid] = score
        if not best:
            return None
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if top >= threshold and top - second >= margin:
            return Resolution(self.teams[top_id], ResolveMethod.FUZZY, top)
        return None
