"""Queries for followed wallets (US7), alert de-duplication and fan-out of text alerts to subscribers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polybot.data import premium_repo, repo
from polybot.data.tables import FollowedWallet, SeenTrade, Subscription
from polybot.logic.alerts import AlertType, enabled


async def follow(
    s: AsyncSession, chat_id: int, wallet: str, min_usdc: Decimal, label: str | None, max_per_chat: int
) -> str:
    """Returns "added", "updated" or "limit"."""
    row = (
        await s.execute(
            select(FollowedWallet).where(FollowedWallet.chat_id == chat_id, FollowedWallet.wallet == wallet)
        )
    ).scalar_one_or_none()
    if row is not None:
        row.min_usdc, row.label = min_usdc, label or row.label
        return "updated"
    count = (
        await s.execute(select(func.count()).select_from(FollowedWallet).where(FollowedWallet.chat_id == chat_id))
    ).scalar() or 0
    if count >= max_per_chat:
        return "limit"
    s.add(FollowedWallet(chat_id=chat_id, wallet=wallet, min_usdc=min_usdc, label=label))
    return "added"


async def unfollow(s: AsyncSession, chat_id: int, wallet: str) -> bool:
    res = await s.execute(
        delete(FollowedWallet).where(FollowedWallet.chat_id == chat_id, FollowedWallet.wallet == wallet)
    )
    return bool(getattr(res, "rowcount", 0))


async def followed_by_chat(s: AsyncSession, chat_id: int) -> list[FollowedWallet]:
    q = select(FollowedWallet).where(FollowedWallet.chat_id == chat_id).order_by(FollowedWallet.id)
    return list((await s.execute(q)).scalars())


async def followers_by_wallet(s: AsyncSession) -> dict[str, list[FollowedWallet]]:
    out: dict[str, list[FollowedWallet]] = defaultdict(list)
    for row in (await s.execute(select(FollowedWallet))).scalars():
        out[row.wallet].append(row)
    return dict(out)


async def claim_new(s: AsyncSession, keys: Iterable[str], at: datetime) -> set[str]:
    """Keys not seen before; they are recorded in the same transaction."""
    wanted = list(dict.fromkeys(keys))
    if not wanted:
        return set()
    seen = set((await s.execute(select(SeenTrade.key).where(SeenTrade.key.in_(wanted)))).scalars())
    fresh = [k for k in wanted if k not in seen]
    for k in fresh:
        s.add(SeenTrade(key=k, at=at))
    await s.flush()
    return set(fresh)


async def purge_seen(s: AsyncSession, before: datetime) -> None:
    await s.execute(delete(SeenTrade).where(SeenTrade.at < before))


def recipients(subs: Sequence[Subscription], alert: AlertType) -> list[Subscription]:
    return [sub for sub in subs if sub.active and enabled(sub.filters, alert)]


async def send_alert(
    s: AsyncSession,
    subs: Sequence[Subscription],
    kind: str,
    alert: AlertType,
    text: str,
    dedup: str,
    now: datetime,
    free_daily_alerts: int | None,
    ttl: timedelta = timedelta(hours=1),
) -> int:
    """Queue a text alert for every subscriber who wants this type and still has free-plan quota."""
    targets = recipients(subs, alert)
    if free_daily_alerts is not None and targets:
        sent = await premium_repo.alerts_sent_since(s, [t.chat_id for t in targets], now - timedelta(hours=24))
        limited = premium_repo.over_daily_limit(targets, sent, free_daily_alerts, now)
        targets = [t for t in targets if t.chat_id not in limited]
    if not targets:
        return 0
    return await repo.enqueue_text(s, [t.chat_id for t in targets], text, dedup, now, ttl=ttl, kind=kind)
