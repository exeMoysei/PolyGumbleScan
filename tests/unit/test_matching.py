"""Event and market matching on TEST DATA fixtures and synthetic events."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polybot.adapters.fixture import fixture_adapters
from polybot.adapters.rules_parser import parse_rules
from polybot.domain.enums import MappingStatus, MarketType, Period, SettlementPolicy
from polybot.domain.models import ProviderEvent, ProviderMarket, ProviderOutcome, StartPrecision
from polybot.matching.catalog import match_catalog
from polybot.matching.events import cluster_events, match, resolve_event
from polybot.matching.markets import compatibility_issues, map_market, revalidate
from polybot.matching.teams import TeamRegistry

FIX = Path(__file__).parent.parent / "fixtures"
REG = TeamRegistry.default()


def ev(
    provider: str,
    ext: str,
    title: str,
    start: datetime,
    *,
    league: str = "nba",
    participants=(),
    home=None,
    away=None,
    precision=StartPrecision.EXACT,
    game=None,
) -> ProviderEvent:
    return ProviderEvent(
        provider=provider,
        external_id=ext,
        sport="basketball",
        league=league,
        title=title,
        participants=tuple(participants),
        start_at=start,
        home=home,
        away=away,
        start_precision=precision,
        date_tz="America/New_York",
        game_number=game,
    )


async def load_all(leagues: list[str]):
    events, markets = [], []
    for a in fixture_adapters(FIX, leagues):
        cat = await a.discover()
        events += cat.events
        markets += cat.markets
    return events, markets


async def test_fixture_events_match_across_three_providers() -> None:
    events, markets = await load_all(["nba", "epl"])
    report = match_catalog(events, markets, REG)
    assert not report.unresolved
    by_id = {c.id: c for c in report.clusters}
    lalbos = by_id["nba-20260115-bos-lal"]
    assert lalbos.providers == {"polymarket", "kalshi", "oddsapi"}
    home, away, known = lalbos.roles()
    assert (home, away, known) == ("nba:bos", "nba:lal", True)
    assert "start_diff:10m" in lalbos.reasons  # Odds API is 10 minutes off
    assert "date_only_match" in lalbos.reasons  # Kalshi only publishes the date
    assert by_id["nba-20260115-mia-nyk"].providers == {"polymarket", "oddsapi"}
    assert by_id["nba-20260115-gsw-phx"].providers == {"polymarket"}
    assert by_id["nba-20260115-den-uta"].providers == {"kalshi"}
    assert by_id["epl-20260117-ars-che"].providers == {"polymarket", "oddsapi"}
    overlap = report.overlap()
    assert overlap[frozenset({"polymarket", "kalshi", "oddsapi"})] == 1


async def test_fixture_market_proposals_share_canonical_keys() -> None:
    events, markets = await load_all(["nba", "epl"])
    report = match_catalog(events, markets, REG)
    keys = report.by_key()
    ml = keys["nba-20260115-bos-lal|moneyline|full_game"]
    assert {p.market.provider for p in ml} == {"polymarket", "kalshi", "oddsapi"}
    for p in ml:
        assert p.status in (MappingStatus.PENDING, MappingStatus.NEEDS_REVIEW)
        assert len(p.outcomes) == 2
    kalshi = [p for p in ml if p.market.provider == "kalshi"]
    sels = {o.selection.key for p in kalshi for o in p.outcomes}
    assert sels == {"win:nba:lal", "not_win:nba:lal", "win:nba:bos", "not_win:nba:bos"}
    epl = keys["epl-20260117-ars-che|match_result|regulation"]
    poly_epl = {o.selection.key for p in epl if p.market.provider == "polymarket" for o in p.outcomes}
    assert poly_epl == {"win:epl:ars", "not_win:epl:ars", "draw", "not_draw", "win:epl:che", "not_win:epl:che"}


def test_far_apart_start_times_do_not_match() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    events = [ev("a", "1", "Lakers vs. Celtics", t), ev("b", "2", "LAL @ BOS", t + timedelta(days=2))]
    clusters, _ = match(events, REG)
    assert len(clusters) == 2


def test_different_opponent_does_not_match() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    clusters, _ = match([ev("a", "1", "Lakers vs. Celtics", t), ev("b", "2", "Lakers vs. Knicks", t)], REG)
    assert len(clusters) == 2


def test_doubleheader_exact_times_split_and_date_only_is_ambiguous() -> None:
    g1 = datetime(2026, 7, 4, 17, 5, tzinfo=UTC)
    g2 = datetime(2026, 7, 4, 23, 10, tzinfo=UTC)
    day = datetime(2026, 7, 4, 4, 0, tzinfo=UTC)  # midnight ET
    events = [
        ev("a", "1", "Yankees vs. Red Sox", g1, league="mlb"),
        ev("a", "2", "Yankees vs. Red Sox", g2, league="mlb"),
        ev("b", "3", "New York Yankees @ Boston Red Sox", g1 + timedelta(minutes=5), league="mlb"),
        ev("b", "4", "New York Yankees @ Boston Red Sox", g2, league="mlb"),
        ev("c", "5", "New York Y at Boston", day, league="mlb", precision=StartPrecision.DATE),
        ev("d", "6", "New York Y at Boston", day, league="mlb", precision=StartPrecision.DATE, game=2),
    ]
    clusters, unresolved = match(events, REG)
    assert not unresolved
    exact = sorted((c for c in clusters if c.start_exact), key=lambda c: c.start_at)
    assert [len(c.members) for c in exact] == [2, 3]  # game-2 venue attached by game number
    assert exact[0].id.endswith("-g1") and exact[1].id.endswith("-g2")
    ambiguous = [c for c in clusters if "ambiguous_doubleheader" in c.reasons]
    assert len(ambiguous) == 1 and ambiguous[0].providers == {"c"}


def test_role_conflict_is_flagged() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    a = ev(
        "a",
        "1",
        "",
        t,
        participants=("Boston Celtics", "Los Angeles Lakers"),
        home="Boston Celtics",
        away="Los Angeles Lakers",
    )
    b = ev("b", "2", "Boston @ Los Angeles L", t)
    clusters, _ = match([a, b], REG)
    assert len(clusters) == 1 and "role_conflict" in clusters[0].reasons
    assert not clusters[0].strong


def test_fuzzy_names_lower_confidence() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    clusters, _ = match([ev("a", "1", "Milwauke Buck vs. Celtics", t), ev("b", "2", "Bucks vs. Celtics", t)], REG)
    assert len(clusters) == 1
    assert clusters[0].confidence < 0.9 and not clusters[0].strong


def test_unknown_team_is_unresolved() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    r = resolve_event(ev("a", "1", "Lakers vs. Harlem Globetrotters", t), REG)
    assert not hasattr(r, "teams")


def _market(provider: str, period: Period, line=None, mtype=MarketType.MONEYLINE, text="") -> ProviderMarket:
    rules = parse_rules(
        provider,
        text
        or "Includes overtime. If canceled, resolve 50-50. If postponed, the market "
        "will remain open until the game has been completed.",
        default_period=period,
    )
    outs = (
        (ProviderOutcome("o1", "Over", "over"), ProviderOutcome("o2", "Under", "under"))
        if mtype == MarketType.TOTAL
        else (ProviderOutcome("o1", "Lakers", "Lakers"), ProviderOutcome("o2", "Celtics", "Celtics"))
    )
    return ProviderMarket(
        provider=provider,
        external_id=f"{provider}-m",
        external_event_id="1",
        market_type=mtype,
        period=period,
        outcomes=outs,
        rules=rules,
        line=line,
        line_unit="points" if line is not None else None,
    )


def test_market_compatibility_checks() -> None:
    a = _market("a", Period.FULL_GAME, Decimal("2.5"), MarketType.TOTAL)
    b = _market("b", Period.FULL_GAME, Decimal("3"), MarketType.TOTAL)
    assert "line_mismatch" in compatibility_issues(a, b)
    c = _market("c", Period.REGULATION, Decimal("2.5"), MarketType.TOTAL, text="Regulation time only.")
    assert "period_mismatch" in compatibility_issues(a, c)


def test_mapping_invalidated_on_rules_or_period_or_line_change() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    clusters, _ = match([ev("a", "1", "Lakers vs. Celtics", t)], REG)
    cluster = clusters[0]
    base = map_market(_market("a", Period.FULL_GAME), cluster, REG)
    assert base.status == MappingStatus.PENDING
    ok = revalidate(MappingStatus.APPROVED, base.rules_version, base.params, base)
    assert ok.status == MappingStatus.APPROVED
    new_rules = map_market(
        _market(
            "a",
            Period.FULL_GAME,
            text="Includes overtime. If canceled, resolve 50-50. "
            "If postponed, the market will remain open until the game has been completed. "
            "Source changed.",
        ),
        cluster,
        REG,
    )
    assert revalidate(MappingStatus.APPROVED, base.rules_version, base.params, new_rules).reason == "rules_changed"
    new_period = map_market(
        _market(
            "a",
            Period.REGULATION,
            text="Includes overtime. If canceled, resolve 50-50. "
            "If postponed, the market will remain open until the game has been completed.",
        ),
        cluster,
        REG,
    )
    res = revalidate(MappingStatus.APPROVED, new_period.rules_version, base.params, new_period)
    assert res.status == MappingStatus.INVALIDATED and "period" in (res.reason or "")
    tot_a = map_market(_market("a", Period.FULL_GAME, Decimal("220.5"), MarketType.TOTAL), cluster, REG)
    tot_b = map_market(_market("a", Period.FULL_GAME, Decimal("221.5"), MarketType.TOTAL), cluster, REG)
    assert tot_a.canonical_market_key != tot_b.canonical_market_key
    res2 = revalidate(MappingStatus.APPROVED, tot_b.rules_version, tot_a.params, tot_b)
    assert res2.status == MappingStatus.INVALIDATED and "line" in (res2.reason or "")


def test_unknown_rules_need_review() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    clusters, _ = match([ev("a", "1", "Lakers vs. Celtics", t)], REG)
    p = map_market(_market("a", Period.FULL_GAME, text="Resolves to the winner."), clusters[0], REG)
    assert p.status == MappingStatus.NEEDS_REVIEW
    assert "rules_cancel_unknown" in p.reasons


@pytest.mark.parametrize(
    ("text", "cancel", "postpone", "ot"),
    [
        (
            "If the game is canceled entirely, with no make-up game, this market will resolve 50-50. If the game is "
            "postponed, this market will remain open until the game has been completed. Includes overtime.",
            SettlementPolicy.HALF,
            SettlementPolicy.CARRY,
            True,
        ),
        (
            'This market only covers 90 minutes plus stoppage time. If the match is canceled, it will resolve to "No".',
            SettlementPolicy.NO_WINS,
            SettlementPolicy.UNKNOWN,
            False,
        ),
        (
            "Bets are void and stakes refunded if the event is cancelled. "
            "If postponed for more than 24 hours, bets are void.",
            SettlementPolicy.REFUND,
            SettlementPolicy.REFUND,
            None,
        ),
    ],
)
def test_rules_parser(text: str, cancel: SettlementPolicy, postpone: SettlementPolicy, ot: bool | None) -> None:
    r = parse_rules("x", text)
    assert (r.on_cancel, r.on_postpone, r.includes_overtime) == (cancel, postpone, ot)


def test_cluster_ids_are_stable_regardless_of_input_order() -> None:
    t = datetime(2026, 1, 16, 0, 30, tzinfo=UTC)
    a = [ev("a", "1", "Lakers vs. Celtics", t), ev("b", "2", "LAL @ BOS", t + timedelta(minutes=3))]
    r1 = cluster_events([resolve_event(e, REG) for e in a])  # type: ignore[misc]
    r2 = cluster_events([resolve_event(e, REG) for e in reversed(a)])  # type: ignore[misc]
    assert [c.id for c in r1] == [c.id for c in r2]
