"""US12 on PostgreSQL: free daily alert limit in the outbox, idempotent payments, admin grant/revoke."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from polybot.domain.premium import PremiumPlan
from polybot.services.scan import ScanService
from polybot.storage import premium as premium_repo
from polybot.storage import repo
from polybot.storage.models import AdminAction, Opportunity, Outbox, Payment, Subscription
from tests.integration.test_flow import ADMIN, NOW, _approve_all, _bootstrap, settings

FREE_CHAT, PREMIUM_CHAT = 2001, 2002


async def test_free_chat_gets_daily_limit_premium_gets_everything(sessions, redis) -> None:  # type: ignore[no-untyped-def]
    st = settings(premium_enabled=True, free_daily_alerts=2)
    st, store, ingest, _ = await _bootstrap(sessions, redis, st)
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, FREE_CHAT, FREE_CHAT, Decimal(200))
        await repo.ensure_subscription(s, PREMIUM_CHAT, PREMIUM_CHAT, Decimal(200))
        assert await premium_repo.grant(s, PREMIUM_CHAT, 30, NOW, ADMIN) is not None
    await _approve_all(sessions)
    await ingest.discover_once(NOW)
    for a in ingest.adapters:
        await ingest.quotes_once(a)
    await ScanService(st, sessions, store).scan(now=NOW)
    async with sessions() as s:
        opps = (await s.execute(select(func.count()).select_from(Opportunity))).scalar()
        per_chat = dict(
            (
                await s.execute(
                    select(Outbox.chat_id, func.count()).where(Outbox.kind == "signal").group_by(Outbox.chat_id)
                )
            ).all()
        )
    assert opps is not None and opps > 2
    assert per_chat[PREMIUM_CHAT] == opps
    assert per_chat[FREE_CHAT] == 2
    async with sessions() as s:
        sent = await premium_repo.alerts_sent_since(s, [FREE_CHAT, PREMIUM_CHAT], NOW - timedelta(hours=24))
        # 25 hours later the window has moved on
        later = await premium_repo.alerts_sent_since(s, [FREE_CHAT], NOW + timedelta(hours=1))
    assert sent == {FREE_CHAT: 2, PREMIUM_CHAT: opps}
    assert later == {}


async def test_payment_is_applied_once_and_extends(sessions) -> None:  # type: ignore[no-untyped-def]
    plan = PremiumPlan("30", 30, 250)
    async with sessions() as s, s.begin():
        await repo.ensure_subscription(s, FREE_CHAT, FREE_CHAT, Decimal(100))
    kw = dict(chat_id=FREE_CHAT, user_id=FREE_CHAT, plan=plan, amount=250, currency="XTR", budget_if_new=Decimal(100))
    async with sessions() as s, s.begin():
        first = await premium_repo.record_payment(s, charge_id="ch-1", now=NOW, **kw)  # type: ignore[arg-type]
    async with sessions() as s, s.begin():
        again = await premium_repo.record_payment(s, charge_id="ch-1", now=NOW + timedelta(minutes=1), **kw)  # type: ignore[arg-type]
    async with sessions() as s, s.begin():
        second = await premium_repo.record_payment(s, charge_id="ch-2", now=NOW + timedelta(days=1), **kw)  # type: ignore[arg-type]
    assert first.created and first.premium_until == NOW + timedelta(days=30)
    assert not again.created and again.premium_until == first.premium_until  # re-delivered update
    assert second.created and second.premium_until == NOW + timedelta(days=60)  # extends, no lost days
    async with sessions() as s:
        assert (await s.execute(select(func.count()).select_from(Payment))).scalar() == 2
        sub = await s.get(Subscription, FREE_CHAT)
        st = await premium_repo.stats(s, NOW + timedelta(days=2))
    assert sub is not None and sub.premium_until == second.premium_until
    assert st["premium_active"] == 1


async def test_payment_before_start_creates_subscription(sessions) -> None:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        res = await premium_repo.record_payment(
            s,
            chat_id=3003,
            user_id=3003,
            charge_id="ch-new",
            plan=PremiumPlan("90", 90, 600),
            amount=600,
            currency="XTR",
            now=NOW,
            budget_if_new=Decimal(100),
        )
    async with sessions() as s:
        sub = await s.get(Subscription, 3003)
    assert res.created and sub is not None and sub.active and sub.premium_until == NOW + timedelta(days=90)
    assert "signal" in sub.filters["verdicts"]


async def test_admin_grant_and_revoke_are_audited(sessions) -> None:  # type: ignore[no-untyped-def]
    async with sessions() as s, s.begin():
        assert await premium_repo.grant(s, 999, 30, NOW, ADMIN) is None  # no /start yet
        await repo.ensure_subscription(s, FREE_CHAT, FREE_CHAT, Decimal(100))
    async with sessions() as s, s.begin():
        sub = await premium_repo.grant(s, FREE_CHAT, 7, NOW, ADMIN)
        assert sub is not None and sub.premium_until == NOW + timedelta(days=7)
    async with sessions() as s, s.begin():
        sub = await premium_repo.revoke(s, FREE_CHAT, NOW, ADMIN)
        assert sub is not None and sub.premium_until is None
    async with sessions() as s:
        actions = (await s.execute(select(AdminAction.action).order_by(AdminAction.id))).scalars().all()
    assert actions == ["premium_grant", "premium_revoke"]
