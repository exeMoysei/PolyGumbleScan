"""End-to-end offline pipeline on TEST DATA fixtures: parse -> match -> map -> scan."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polybot.adapters.fixture import fixture_adapters
from polybot.domain.enums import Route, Verdict
from polybot.domain.models import FxRate, FxTable
from polybot.matching.teams import TeamRegistry
from polybot.services.pipeline import collect, index_quotes, run_offline
from polybot.services.scanner import ScanConfig

FIX = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)  # 90 minutes before tip-off
REG = TeamRegistry.default()


def fx(now: datetime = NOW) -> FxTable:
    t = FxTable("USD")
    t.add(FxRate("USDC", "USD", Decimal("1"), now, timedelta(minutes=15), Decimal("30")))
    return t


def approve_all(_p: object) -> bool:
    return True


async def run(cfg: ScanConfig | None = None, fxt: FxTable | None = None, now: datetime = NOW):
    world = await collect(fixture_adapters(FIX, ["nba", "epl"], now=NOW))
    assert not world.errors
    return run_offline(world, REG, cfg or ScanConfig(budget=Decimal(200)), fxt or fx(), now, approve_all)


async def test_prediction_prediction_signal_on_fixture() -> None:
    _, scan = await run()
    pp = [d for d in scan.drafts if d.route == Route.PREDICTION_PREDICTION]
    assert pp, scan.rejections
    best = pp[0]
    assert best.verdict == Verdict.SIGNAL
    assert {o.venue.id for o in best.offers} == {"polymarket", "kalshi"}
    assert best.plan.worst_regular >= Decimal(1)
    assert best.event.title == "Los Angeles Lakers @ Boston Celtics"
    # Polymarket Lakers (0.42) + Kalshi Celtics YES (0.54)
    sel = {o.selection.key for o in best.offers}
    assert sel == {"win:nba:lal", "win:nba:bos"}


async def test_prediction_sportsbook_is_candidate() -> None:
    _, scan = await run()
    ps = [d for d in scan.drafts if d.route == Route.PREDICTION_SPORTSBOOK]
    assert ps
    assert all(d.verdict == Verdict.CANDIDATE for d in ps)
    assert all("aggregator_freshness" in d.reasons or "exceptional_loss_possible" in d.reasons for d in ps)


async def test_epl_two_legs_cover_three_results() -> None:
    _, scan = await run()
    epl = [d for d in scan.drafts if d.canonical_market_key.startswith("epl-")]
    assert epl, scan.rejections
    sels = {o.selection.key for o in epl[0].offers}
    assert sels == {"win:epl:ars", "not_win:epl:ars"}
    assert {s for s, _ in epl[0].plan.pnl} >= {"win:epl:ars", "draw", "win:epl:che"}


async def test_sportsbook_only_route_disabled_by_default() -> None:
    _, scan = await run()
    assert all(d.route != Route.SPORTSBOOK_SPORTSBOOK for d in scan.drafts)
    assert scan.rejections["route_disabled:sportsbook_sportsbook"] > 0


async def test_stale_quotes_and_fx_block_signals() -> None:
    later = NOW + timedelta(minutes=30)  # beyond venue TTL
    _, scan = await run(now=later)
    assert not [d for d in scan.drafts if d.route == Route.PREDICTION_PREDICTION]
    assert scan.rejections["quote_stale:polymarket"] > 0
    stale_fx = FxTable("USD")
    stale_fx.add(FxRate("USDC", "USD", Decimal("1"), NOW - timedelta(hours=2), timedelta(minutes=15)))
    _, scan2 = await run(fxt=stale_fx)
    assert not [d for d in scan2.drafts if "polymarket" in {o.venue.id for o in d.offers}]
    assert scan2.rejections["fx_stale:USDC"] > 0


async def test_no_signal_after_event_start() -> None:
    _, scan = await run(now=datetime(2026, 1, 16, 0, 29, tzinfo=UTC))
    assert not [d for d in scan.drafts if d.canonical_market_key.startswith("nba-20260115-bos-lal")]


async def test_unapproved_mappings_never_scan() -> None:
    world = await collect(fixture_adapters(FIX, ["nba"], now=NOW))
    _, scan = run_offline(world, REG, ScanConfig(budget=Decimal(200)), fx(), NOW, lambda p: False)
    assert scan.drafts == [] and scan.keys_scanned == 0


async def test_late_quote_does_not_overwrite_newer() -> None:
    world = await collect(fixture_adapters(FIX, ["nba"], now=NOW))
    q = world.quotes[0]
    newer = replace(q, source_at=NOW + timedelta(seconds=5), levels=q.levels[:1])
    older = replace(q, source_at=NOW - timedelta(seconds=30))
    idx = index_quotes([newer, older])
    assert idx[(q.provider, q.market_external_id, q.outcome_external_id)][0].source_at == newer.source_at


async def test_recalculation_is_deterministic() -> None:
    _, a = await run()
    _, b = await run()
    assert [d.fingerprint for d in a.drafts] == [d.fingerprint for d in b.drafts]
    assert [d.material_signature() for d in a.drafts] == [d.material_signature() for d in b.drafts]


async def test_live_fixture_clock_shifts_events_into_future() -> None:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    world = await collect(fixture_adapters(FIX, ["nba"], live=True))
    now = _dt.now(_UTC)
    assert all(e.start_at > now for e in world.events if e.start_precision.value == "exact")
    report, scan = run_offline(world, REG, ScanConfig(budget=Decimal(200)), fx(now), now, approve_all)
    assert any(c.id.endswith("bos-lal") and len(c.providers) == 3 for c in report.clusters)
    assert any(d.verdict == Verdict.SIGNAL for d in scan.drafts)


async def test_quote_polling_survives_cache_outage() -> None:
    from polybot.services.ingest import IngestService
    from polybot.settings import Settings

    class BrokenStore:
        async def put_many(self, quotes, ttl_ms):  # type: ignore[no-untyped-def]
            raise ConnectionError("redis down")

        async def get_markets(self, markets):  # type: ignore[no-untyped-def]
            raise ConnectionError("redis down")

    adapters = fixture_adapters(FIX, ["nba"], now=NOW)
    svc = IngestService(Settings(odds_api_key=None), adapters, None, BrokenStore())  # type: ignore[arg-type]
    svc.catalogs["polymarket"] = await adapters[0].discover()
    svc.approved = {("polymarket", m.external_id) for m in svc.catalogs["polymarket"].markets}
    assert await svc.quotes_once(adapters[0]) == 0  # logged and counted, loop keeps running
