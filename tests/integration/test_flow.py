"""Full flow on PostgreSQL + Redis with TEST DATA fixtures: ingest -> review -> scan -> outbox -> notify."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from polybot.adapters.fixture import fixture_adapters
from polybot.codec import dec_quote
from polybot.domain.enums import MappingStatus
from polybot.domain.models import PriceLevel
from polybot.services.ingest import IngestService
from polybot.services.pipeline import fx_table_from, scan_config_from
from polybot.services.recheck import original_quotes, recheck_with
from polybot.services.replay import replay_db
from polybot.services.scan import ScanService
from polybot.settings import Settings
from polybot.storage import repo
from polybot.storage.models import MarketMapping, Opportunity, Outbox, Subscription
from polybot.storage.quotes import RedisQuoteStore

FIX = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)
ADMIN = 4242


def settings(**kw) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(
        admin_ids=[ADMIN],
        leagues=["nba", "epl"],
        default_budget=Decimal(200),
        odds_api_key=None,
        quote_ttl_s={"polymarket": 3600, "kalshi": 3600, "oddsapi": 3600},
        fx_ttl_s=3600,
    )
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_next: str | None = None

    async def send(self, chat_id, text, keyboard):  # type: ignore[no-untyped-def]
        from polybot.telegram.notifier import SendError

        if self.fail_next:
            kind, self.fail_next = self.fail_next, None
            raise SendError(kind, "simulated")
        self.sent.append((chat_id, text))
        return len(self.sent)


async def _approve_all(sessions) -> int:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        rows = await repo.pending_mappings(s, limit=100)
        for m, _ in rows:
            await repo.decide_mapping(s, m.id, True, ADMIN, "test", NOW)
    return len(rows)


async def _bootstrap(sessions, redis, st=None):  # type: ignore[no-untyped-def]
    st = st or settings()
    store = RedisQuoteStore(redis)
    ingest = IngestService(st, fixture_adapters(FIX, ["nba", "epl"], now=NOW), sessions, store)
    report = await ingest.discover_once(NOW)
    return st, store, ingest, report


async def test_ingest_creates_pending_mappings_and_admin_message(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    _, _, _, report = await _bootstrap(sessions, redis)
    async with sessions() as s:
        statuses = (await s.execute(select(MarketMapping.status, func.count()).group_by(MarketMapping.status))).all()
        admin_msgs = (await s.execute(select(Outbox).where(Outbox.kind == "admin"))).scalars().all()
        st = await repo.stats(s, NOW - timedelta(days=1))
    assert {k for k, _ in statuses} <= {MappingStatus.PENDING.value, MappingStatus.NEEDS_REVIEW.value}
    assert sum(n for _, n in statuses) > 0
    assert admin_msgs and admin_msgs[0].chat_id == ADMIN
    assert st["shared_events"] == 3
    assert len(report.cross_venue_clusters) == 3


async def test_scan_publishes_only_after_approval_and_dedupes(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    st, store, ingest, _ = await _bootstrap(sessions, redis)
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, 1001, 1001, Decimal(200))
    scan = ScanService(st, sessions, store)
    assert await scan.scan(now=NOW) == []  # nothing approved yet
    await _approve_all(sessions)
    await ingest.discover_once(NOW)  # refresh approved set
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    drafts = await scan.scan(now=NOW)
    assert drafts
    async with sessions() as s:
        opps = (await s.execute(select(Opportunity))).scalars().all()
        outbox = (await s.execute(select(Outbox).where(Outbox.kind == "signal"))).scalars().all()
    assert any(o.verdict == "signal" for o in opps)
    assert len(outbox) == len(opps)
    # same inputs again -> no new revision, no new notification
    await scan.scan(now=NOW + timedelta(seconds=5))
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(Opportunity))).scalar() == len(opps)
        assert (
            await s.execute(select(func.count()).select_from(Outbox).where(Outbox.kind != "admin"))
        ).scalar() == len(outbox)


async def test_notifier_lease_retry_and_expiry(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    from polybot.telegram.notifier import Notifier

    st, store, ingest, _ = await _bootstrap(sessions, redis)
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, 1001, 1001, Decimal(200))
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    await ScanService(st, sessions, store).scan(now=NOW)
    sender = FakeSender()
    n1 = Notifier(sessions, sender)
    n2 = Notifier(sessions, sender)
    sender.fail_next = "retry"
    async with sessions() as s:
        pending = (await s.execute(select(func.count()).select_from(Outbox).where(Outbox.status == "pending"))).scalar()
    processed = await n1.process_once(NOW)
    assert processed == pending
    assert await n2.process_once(NOW) == 0  # leased/handled rows are not claimed twice
    async with sessions() as s:
        retry = (await s.execute(select(Outbox).where(Outbox.attempts == 1))).scalars().all()
    assert len(retry) == 1 and retry[0].status == "pending"
    # retry is due later; signal still valid
    assert await n2.process_once(NOW + timedelta(seconds=5)) == 1
    texts = [t for _, t in sender.sent]
    assert sum("СИГНАЛ" in t or "КАНДИДАТ" in t for t in texts) >= 1
    async with sessions() as s:
        st_ = await repo.stats(s, NOW - timedelta(days=1))
    assert st_["users_total"] == 1 and st_["users_active"] == 1
    cards = sum("СИГНАЛ" in t or "КАНДИДАТ" in t for _, t in sender.sent)  # admin notices are not alerts
    assert cards >= 1 and st_["alerts_sent_total"] == cards and st_["alerts_sent_recent"] == cards
    # forbidden -> subscription deactivated
    async with sessions() as s, s.begin():
        await repo.enqueue_text(s, [1001], "hello", "x", NOW)
    sender.fail_next = "forbidden"
    await n1.process_once(NOW)
    async with sessions() as s:
        assert (await s.get(Subscription, 1001)).active is False  # type: ignore[union-attr]


async def test_redis_cache_rejects_late_and_duplicate_updates(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    _, store, ingest, _ = await _bootstrap(sessions, redis)
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    poly = next(a for a in ingest.adapters if a.id == "polymarket")
    n = await ingest.quotes_once(poly)
    assert n > 0
    assert await ingest.quotes_once(poly) == 0  # identical snapshot is a duplicate
    cached = await store.get_markets([("polymarket", "0xcond90001")])
    q = cached[0]
    late = replace(
        q,
        source_at=q.source_at - timedelta(seconds=10),
        levels=(PriceLevel(Decimal("0.01"), Decimal(1)),),
        raw_hash="late",
    )
    newer = replace(q, source_at=q.source_at + timedelta(seconds=10), raw_hash="newer")
    accepted = await store.put_many([late, newer], {"polymarket": 60_000})
    assert [a.raw_hash for a in accepted] == ["newer"]
    again = await store.get_markets([("polymarket", "0xcond90001")])
    assert {x.raw_hash for x in again if x.outcome_external_id == q.outcome_external_id} == {"newer"}


async def test_replay_never_uses_future_quotes(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    st, _, ingest, _ = await _bootstrap(sessions, redis)
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    # a later snapshot where the Lakers price jumps (kills the edge)
    async with sessions() as s:
        docs = await repo.quotes_as_of(s, NOW, timedelta(hours=1))
    lal = next(dec_quote(d) for d in docs if d["outcome"] == "tok-lal-0115")
    future = replace(
        lal,
        source_at=NOW + timedelta(minutes=5),
        received_at=NOW + timedelta(minutes=5),
        levels=(PriceLevel(Decimal("0.60"), Decimal(1000)),),
        raw_hash="future",
    )
    async with sessions() as s, s.begin():
        await repo.store_quote_snapshots(s, [future])
    cfg = scan_config_from(st, Decimal(200))
    async with sessions() as s:
        at_now, _ = await replay_db(s, NOW + timedelta(seconds=1), cfg, fx_table_from(st, NOW))
        later, _ = await replay_db(s, NOW + timedelta(minutes=6), cfg, fx_table_from(st, NOW + timedelta(minutes=6)))
    pp_now = [
        d for d in at_now if d.route.value == "prediction_prediction" and "polymarket" in {o.venue.id for o in d.offers}
    ]
    pp_later = [
        d for d in later if d.route.value == "prediction_prediction" and "polymarket" in {o.venue.id for o in d.offers}
    ]
    assert pp_now and not pp_later


async def test_mapping_invalidated_when_rules_change(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    _, _, ingest, _ = await _bootstrap(sessions, redis)
    await _approve_all(sessions)
    cat = ingest.catalogs["polymarket"]
    m0 = cat.markets[0]
    changed = replace(m0, rules=replace(m0.rules, text=m0.rules.text + " Rules amended."))
    ingest.catalogs["polymarket"].markets[0] = changed

    class Frozen:
        id = "polymarket"
        capabilities = ingest.adapters[0].capabilities

        async def discover(self):  # type: ignore[no-untyped-def]
            return cat

        async def snapshot(self, markets):  # type: ignore[no-untyped-def]
            return []

        async def aclose(self) -> None:
            return None

    ingest.adapters[0] = Frozen()  # type: ignore[assignment]
    await ingest.discover_once(NOW)
    async with sessions() as s:
        row = (await s.execute(select(MarketMapping).where(MarketMapping.status == "invalidated"))).scalars().all()
    assert row and row[0].decision_reason == "rules_changed"


async def test_recheck_updates_or_closes(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    st, store, ingest, _ = await _bootstrap(sessions, redis)
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    drafts = await ScanService(st, sessions, store).scan(now=NOW)
    pp = next(d for d in drafts if d.route.value == "prediction_prediction")
    async with sessions() as s:
        opp = (await s.execute(select(Opportunity).where(Opportunity.fingerprint == pp.fingerprint))).scalar_one()
    cfg = scan_config_from(st, Decimal(200))
    later = NOW + timedelta(seconds=30)
    same = [replace(q, source_at=later, received_at=later) for q in original_quotes(opp.payload)]
    ok = recheck_with(opp.payload, same, cfg, fx_table_from(st, later), later)
    assert ok.draft is not None and ok.draft.fingerprint == pp.fingerprint
    worse = [
        replace(q, levels=(PriceLevel(Decimal("0.60"), Decimal(1000)),)) if q.provider == "polymarket" else q
        for q in same
    ]
    gone = recheck_with(opp.payload, worse, cfg, fx_table_from(st, later), later)
    assert gone.draft is None and gone.reasons
    # cheaper price -> new revision via publish_draft
    better = [
        replace(q, levels=(PriceLevel(Decimal("0.40"), Decimal(1000)),)) if q.provider == "polymarket" else q
        for q in same
    ]
    upd = recheck_with(opp.payload, better, cfg, fx_table_from(st, later), later)
    assert upd.draft is not None
    async with sessions() as s, s.begin():
        res = await repo.publish_draft(s, upd.draft, [], later)
    assert res.material and res.revision == 2


async def test_data_gap_does_not_renotify_identical_signal(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    st, store, ingest, _ = await _bootstrap(sessions, redis)
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, 1001, 1001, Decimal(200))
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    scan = ScanService(st, sessions, store)
    first = await scan.scan(now=NOW)
    async with sessions() as s:
        sent_before = (
            await s.execute(select(func.count()).select_from(Outbox).where(Outbox.kind == "signal"))
        ).scalar()
    await redis.flushdb()  # cache lost (restart): opportunities close for missing inputs
    assert await scan.scan(now=NOW + timedelta(seconds=10)) == []
    async with sessions() as s:
        assert (
            await s.execute(select(func.count()).select_from(Opportunity).where(Opportunity.status == "active"))
        ).scalar() == 0
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    again = await scan.scan(now=NOW + timedelta(seconds=20))
    assert {d.fingerprint for d in again} == {d.fingerprint for d in first}
    async with sessions() as s:
        assert (await s.execute(select(func.max(Opportunity.revision)))).scalar() == 1
        assert (
            await s.execute(select(func.count()).select_from(Outbox).where(Outbox.kind == "signal"))
        ).scalar() == sent_before


async def test_invalidated_mapping_is_reported_once_and_reopens_on_new_params(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    _, _, ingest, _ = await _bootstrap(sessions, redis)
    await _approve_all(sessions)
    cat = ingest.catalogs["polymarket"]
    shifted = [replace(e, start_at=e.start_at + timedelta(minutes=30)) for e in cat.events]

    class Frozen:
        id = "polymarket"
        capabilities = ingest.adapters[0].capabilities

        def __init__(self, events):  # type: ignore[no-untyped-def]
            self.events = events

        async def discover(self):  # type: ignore[no-untyped-def]
            return replace(cat, events=self.events)

        async def snapshot(self, markets):  # type: ignore[no-untyped-def]
            return []

        async def aclose(self) -> None:
            return None

    ingest.adapters[0] = Frozen(shifted)  # type: ignore[assignment]
    await ingest.discover_once(NOW)
    async with sessions() as s:
        inv = (
            await s.execute(
                select(func.count()).select_from(MarketMapping).where(MarketMapping.status == "invalidated")
            )
        ).scalar()
        admin1 = (await s.execute(select(func.count()).select_from(Outbox).where(Outbox.kind == "admin"))).scalar()
    assert inv and inv > 0
    await ingest.discover_once(NOW + timedelta(minutes=2))  # nothing new changed -> no new admin message
    async with sessions() as s:
        admin2 = (await s.execute(select(func.count()).select_from(Outbox).where(Outbox.kind == "admin"))).scalar()
    assert admin2 == admin1
    # the event start changes again (now Polymarket is the earliest) -> back to the review queue
    ingest.adapters[0] = Frozen([replace(e, start_at=e.start_at + timedelta(minutes=-30)) for e in cat.events])  # type: ignore[assignment]
    await ingest.discover_once(NOW + timedelta(minutes=4))
    async with sessions() as s:
        statuses = set((await s.execute(select(MarketMapping.status))).scalars())
    assert statuses & {"pending", "needs_review"}
