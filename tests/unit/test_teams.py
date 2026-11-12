import pytest

from polybot.matching.normalize import split_matchup
from polybot.matching.teams import ResolveMethod, TeamRegistry

REG = TeamRegistry.default()


@pytest.mark.parametrize(
    ("league", "raw", "expected"),
    [
        ("nba", "Los Angeles Lakers", "nba:lal"),
        ("nba", "LA Lakers", "nba:lal"),
        ("nba", "Lakers", "nba:lal"),
        ("nba", "Los Angeles L", "nba:lal"),  # Kalshi style
        ("nba", "Los Angeles C", "nba:lac"),
        ("nba", "LA Clippers", "nba:lac"),
        ("nba", "LAL", "nba:lal"),
        ("nba", "lal", "nba:lal"),
        ("nba", "Philadelphia 76ers", "nba:phi"),
        ("nba", "Sixers", "nba:phi"),
        ("nba", "Portland Trail Blazers", "nba:por"),
        ("nba", "Blazers", "nba:por"),
        ("nba", "Golden State", "nba:gsw"),
        ("nba", "New York K", "nba:nyk"),
        ("nba", "Boston", "nba:bos"),  # unique city
        ("nhl", "Montréal Canadiens", "nhl:mtl"),
        ("nhl", "St. Louis Blues", "nhl:stl"),
        ("nhl", "Saint Louis Blues", "nhl:stl"),
        ("nhl", "Utah Hockey Club", "nhl:uta"),
        ("mlb", "Chicago White Sox", "mlb:cws"),
        ("mlb", "White Sox", "mlb:cws"),
        ("mlb", "Oakland Athletics", "mlb:ath"),
        ("nfl", "San Francisco 49ers", "nfl:sf"),
        ("nfl", "Kansas City", "nfl:kc"),
        ("epl", "Man Utd", "epl:mun"),
        ("nba", "New York", "nba:nyk"),  # Nets are Brooklyn: city is unique in the NBA
        ("epl", "Manchester United FC", "epl:mun"),
        ("epl", "Brighton & Hove Albion", "epl:bha"),
        ("epl", "Nott'm Forest", "epl:nfo"),
        ("epl", "Wolverhampton Wanderers", "epl:wol"),
        ("epl", "Tottenham", "epl:tot"),
        ("epl", "Spurs", "epl:tot"),
    ],
)
def test_resolve_known_names(league: str, raw: str, expected: str) -> None:
    res = REG.resolve(league, raw)
    assert res is not None, raw
    assert res.team.id == expected
    assert res.strong


@pytest.mark.parametrize(
    ("league", "raw"),
    [
        ("nba", "Los Angeles"),
        ("nhl", "New York"),
        ("mlb", "Chicago"),
        ("epl", "Manchester"),
        ("nba", "Some Random Team"),
    ],
)
def test_ambiguous_or_unknown_names_do_not_resolve(league: str, raw: str) -> None:
    assert REG.resolve(league, raw) is None


def test_typo_resolves_only_as_fuzzy() -> None:
    res = REG.resolve("nba", "Milwauke Buck")
    assert res is not None and res.team.id == "nba:mil" and res.method == ResolveMethod.FUZZY
    assert not res.strong


def test_contains_resolution_in_titles() -> None:
    res = REG.resolve("nba", "Will the Denver Nuggets win?")
    assert res is not None and res.team.id == "nba:den" and res.method == ResolveMethod.CONTAINS


def test_codes_do_not_cross_leagues() -> None:
    nba = REG.resolve("nba", "PHI")
    nfl = REG.resolve("nfl", "PHI")
    assert nba and nfl and nba.team.id == "nba:phi" and nfl.team.id == "nfl:phi"


@pytest.mark.parametrize(
    ("title", "left", "right", "kind"),
    [
        ("Lakers vs. Celtics", "Lakers", "Celtics", "vs"),
        ("Los Angeles L at Boston Winner?", "Los Angeles L", "Boston", "at"),
        ("LAL @ BOS", "LAL", "BOS", "at"),
        ("Arsenal v Chelsea", "Arsenal", "Chelsea", "vs"),
        ("Arsenal - Chelsea", "Arsenal", "Chelsea", "vs"),
        ("Knicks vs. Heat (Game 3)", "Knicks", "Heat", "vs"),
    ],
)
def test_split_matchup(title: str, left: str, right: str, kind: str) -> None:
    assert split_matchup(title) == (left, right, kind)
