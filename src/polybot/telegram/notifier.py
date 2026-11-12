"""Outbox worker: lease-based claim, retries with backoff, dedup by (chat, fingerprint, revision)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot import metrics
from polybot.storage import repo
from polybot.storage.models import HiddenOpportunity, Opportunity, Outbox, Subscription
from polybot.telegram.cards import render_card
from polybot.telegram.keyboards import card_keyboard

log = logging.getLogger(__name__)


class SendError(Exception):
    def __init__(self, kind: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind  # "retry" | "permanent" | "forbidden" | "uncertain"
        self.retry_after = retry_after


class Sender(Protocol):
    async def send(self, chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None) -> int: ...


class AiogramSender:
    def __init__(self, bot: object) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str, keyboard: InlineKeyboardMarkup | None) -> int:
        from aiogram import Bot
        from aiogram.exceptions import (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramNetworkError,
            TelegramRetryAfter,
        )

        assert isinstance(self.bot, Bot)
        try:
            msg = await self.bot.send_message(chat_id, text, reply_markup=keyboard, disable_web_page_preview=True)
        except TelegramRetryAfter as e:
            raise SendError("retry", str(e), float(e.retry_after)) from e
        except TelegramForbiddenError as e:
            raise SendError("forbidden", str(e)) from e
        except TelegramBadRequest as e:
            raise SendError("permanent", str(e)) from e
        except (TelegramNetworkError, TimeoutError) as e:
            raise SendError("uncertain", str(e)) from e
        return int(msg.message_id)


class Notifier:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        sender: Sender,
        *,
        lease_s: int = 30,
        max_attempts: int = 8,
        batch: int = 20,
    ) -> None:
        self.sessions = sessions
        self.sender = sender
        self.owner = f"notifier-{uuid.uuid4().hex[:8]}"
        self.lease = timedelta(seconds=lease_s)
        self.max_attempts = max_attempts
        self.batch = batch
        self._stop = asyncio.Event()

    async def process_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        async with self.sessions() as s, s.begin():
            rows = await repo.claim_outbox(s, self.owner, now, self.lease, self.batch)
        done = 0
        for row in rows:
            await self._deliver(row, now)
            done += 1
        return done

    async def _deliver(self, row: Outbox, now: datetime) -> None:
        async with self.sessions() as s:
            text, keyboard, stale = None, None, row.expires_at <= now
            if row.opportunity_id is None:
                text = row.text or ""
            else:
                opp = await s.get(Opportunity, row.opportunity_id)
                latest = await repo.latest_revision(s, opp.fingerprint) if opp else None
                sub = await s.get(Subscription, row.chat_id)
                paused = await repo.get_flag(s, repo.PUBLISHING_PAUSED) == "1"
                hidden = await s.get(HiddenOpportunity, (row.chat_id, opp.fingerprint)) if opp else None
                if (
                    opp is None
                    or opp.status != "active"
                    or opp.expires_at <= now
                    or (latest is not None and latest.revision != opp.revision)
                    or sub is None
                    or not sub.active
                    or sub.budget != opp.budget
                    or not repo.subscription_accepts(sub, opp.payload)
                    or hidden is not None
                ):
                    stale = True
                elif paused:
                    # Leave queued signals pending while publication is paused. The next claim
                    # will retry after the lease, or discard the row once its quotes expire.
                    return
                else:
                    header = None if row.kind == "signal" else f"🔁 <b>Update</b> (rev. {opp.revision})"
                    text = render_card(opp.payload, header=header)
                    keyboard = card_keyboard(opp.id, opp.revision, opp.payload)
        if stale or text is None:
            async with self.sessions() as s, s.begin():
                await repo.outbox_done(s, row.id, self.owner, None, now, status="expired")
            metrics.OUTBOX.labels("expired").inc()
            return
        try:
            message_id = await self.sender.send(row.chat_id, text, keyboard)
        except SendError as e:
            async with self.sessions() as s, s.begin():
                if e.kind == "forbidden":
                    await repo.outbox_done(s, row.id, self.owner, None, now, status="failed", error=str(e))
                    sub = await s.get(Subscription, row.chat_id)
                    if sub:
                        sub.active = False
                    status = "failed"
                elif e.kind == "permanent":
                    await repo.outbox_done(s, row.id, self.owner, None, now, status="failed", error=str(e))
                    status = "failed"
                else:
                    if e.kind == "uncertain":
                        log.warning(
                            "telegram delivery uncertain, retrying may duplicate",
                            extra={"outbox_id": row.id, "dedup": row.dedup_key},
                        )
                    status = await repo.outbox_retry(
                        s, row, self.owner, str(e), now, self.max_attempts, retry_after=e.retry_after
                    )
            metrics.OUTBOX.labels(status).inc()
            return
        async with self.sessions() as s, s.begin():
            await repo.outbox_done(s, row.id, self.owner, message_id, now)
        metrics.OUTBOX.labels("sent").inc()

    async def run(self, idle_sleep: float = 1.0) -> None:
        while not self._stop.is_set():
            try:
                n = await self.process_once()
            except Exception:
                log.exception("notifier loop error")
                n = 0
            if n == 0:
                await asyncio.sleep(idle_sleep)

    def stop(self) -> None:
        self._stop.set()
