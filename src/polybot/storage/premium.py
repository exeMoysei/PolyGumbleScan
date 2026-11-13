"""Premium subscription queries (US12). Every function takes an open session; callers own the transaction."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polybot.domain import premium as rules
from polybot.domain.enums import Verdict
from polybot.storage.models import AdminAction, Outbox, Payment, Subscription

# push notifications that count towards the free daily limit (technical/admin messages do not)
ALERT_KINDS = ("signal", "update")


async def alerts_sent_since(s: AsyncSession, chat_ids: Iterable[int], since: datetime) -> dict[int, int]:
    """Alerts queued per chat since ``since`` (queued, sent or failed — every attempt to alert counts)."""
    ids = list(set(chat_ids))
    if not ids:
        return {}
    rows = await s.execute(
        select(Outbox.chat_id, func.count())
        .where(Outbox.chat_id.in_(ids), Outbox.kind.in_(ALERT_KINDS), Outbox.created_at >= since)
        .group_by(Outbox.chat_id)
    )
    return {int(chat): int(n) for chat, n in rows.all()}


def over_daily_limit(
    subscribers: Iterable[Subscription], sent: dict[int, int], daily_limit: int, now: datetime
) -> set[int]:
    """Chats on the free plan that already got ``daily_limit`` alerts in the last 24 hours."""
    out: set[int] = set()
    for sub in subscribers:
        if rules.is_premium(sub.premium_until, now):
            continue
        if sent.get(sub.chat_id, 0) >= daily_limit:
            out.add(sub.chat_id)
    return out


async def grant(s: AsyncSession, chat_id: int, days: int, now: datetime, admin_id: int) -> Subscription | None:
    """Admin grant (gift, refund compensation, tests). Extends an active premium."""
    sub = await s.get(Subscription, chat_id, with_for_update=True)
    if sub is None:
        return None
    sub.premium_until = rules.extend(sub.premium_until, days, now)
    s.add(
        AdminAction(
            user_id=admin_id,
            action="premium_grant",
            target=str(chat_id),
            details={"days": days, "until": sub.premium_until.isoformat()},
        )
    )
    return sub


async def revoke(s: AsyncSession, chat_id: int, now: datetime, admin_id: int) -> Subscription | None:
    sub = await s.get(Subscription, chat_id, with_for_update=True)
    if sub is None:
        return None
    previous = sub.premium_until
    sub.premium_until = None
    s.add(
        AdminAction(
            user_id=admin_id,
            action="premium_revoke",
            target=str(chat_id),
            details={"previous_until": previous.isoformat() if previous else None, "at": now.isoformat()},
        )
    )
    return sub


@dataclass(frozen=True, slots=True)
class PaymentResult:
    premium_until: datetime
    created: bool  # False = this charge was already processed (Telegram re-delivered the update)


async def record_payment(
    s: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
    charge_id: str,
    plan: rules.PremiumPlan,
    amount: int,
    currency: str,
    now: datetime,
    budget_if_new: Decimal,
) -> PaymentResult:
    """Store a successful payment and extend premium exactly once per ``charge_id``."""
    done = (await s.execute(select(Payment).where(Payment.charge_id == charge_id))).scalar_one_or_none()
    if done is not None:
        return PaymentResult(done.premium_until, False)
    sub = await s.get(Subscription, chat_id, with_for_update=True)
    if sub is None:  # paid before /start in this chat — create the subscription instead of losing the payment
        sub = Subscription(
            chat_id=chat_id,
            user_id=user_id,
            budget=budget_if_new,
            active=True,
            filters={"verdicts": [Verdict.SIGNAL.value, Verdict.CANDIDATE.value]},
        )
        s.add(sub)
    sub.premium_until = rules.extend(sub.premium_until, plan.days, now)
    s.add(
        Payment(
            chat_id=chat_id,
            user_id=user_id,
            provider="telegram_stars" if currency == rules.STARS_CURRENCY else currency.lower(),
            charge_id=charge_id,
            plan=plan.code,
            days=plan.days,
            amount=amount,
            currency=currency,
            premium_until=sub.premium_until,
        )
    )
    await s.flush()
    return PaymentResult(sub.premium_until, True)


async def stats(s: AsyncSession, now: datetime) -> dict[str, Any]:
    active = (
        await s.execute(select(func.count()).select_from(Subscription).where(Subscription.premium_until > now))
    ).scalar() or 0
    since = now - timedelta(days=30)
    paid = (
        await s.execute(
            select(Payment.currency, func.count(), func.sum(Payment.amount))
            .where(Payment.created_at >= since)
            .group_by(Payment.currency)
        )
    ).all()
    return {
        "premium_active": int(active),
        "payments_30d": {cur: {"count": int(n), "amount": int(total or 0)} for cur, n, total in paid},
    }
