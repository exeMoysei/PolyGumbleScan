"""Run everything in one process: data collection, scanner, Telegram bot and notifications.

This is the simplest way to start PolyBot locally (``python -m polybot run``): with the default settings it uses a
SQLite file and an in-memory quote cache, so neither PostgreSQL, Redis nor Docker is needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from polybot.data.db import create_schema, is_sqlite, make_engine, make_sessionmaker
from polybot.data.quote_cache import MemoryQuoteStore, QuoteStore, RedisQuoteStore
from polybot.settings import Settings

log = logging.getLogger(__name__)


@dataclass
class Resources:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    store: QuoteStore


def build_resources(settings: Settings) -> Resources:
    engine = make_engine(settings.database_url)
    store: QuoteStore
    if settings.redis_url:
        from redis.asyncio import Redis

        store = RedisQuoteStore(Redis.from_url(settings.redis_url))
    else:
        store = MemoryQuoteStore()
    return Resources(engine, make_sessionmaker(engine), store)


async def prepare_database(settings: Settings, engine: AsyncEngine) -> None:
    """SQLite: create the tables on first start. PostgreSQL: run ``polybot migrate`` (Alembic) instead."""
    if is_sqlite(settings.database_url):
        await create_schema(engine)


async def run_all(settings: Settings) -> None:
    from polybot.services.ingest import IngestService
    from polybot.services.runtime import build_adapters
    from polybot.services.scan import ScanService
    from polybot.services.wallets import WalletWatcher

    res = build_resources(settings)
    await prepare_database(settings, res.engine)
    adapters = build_adapters(settings)
    ingest = IngestService(settings, adapters, res.sessions, res.store)
    scan = ScanService(settings, res.sessions, res.store)
    wallets = WalletWatcher(settings, res.sessions)
    stop = asyncio.Event()
    stoppers: list[Callable[[], None]] = [ingest.stop, scan.stop, wallets.stop, stop.set]

    jobs: list[Coroutine[Any, Any, None]] = [ingest.run(), scan.run(), wallets.run()]
    bot_main: Coroutine[Any, Any, None] | None = None
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    if settings.telegram_bot_token is not None:
        from polybot.bot.handlers import COMMANDS, BotContext, build_bot, build_dispatcher
        from polybot.bot.notifier import AiogramSender, Notifier

        bot = build_bot(settings.telegram_bot_token.get_secret_value())
        dp = build_dispatcher(BotContext(settings, res.sessions, adapters))
        notifier = Notifier(
            res.sessions, AiogramSender(bot), lease_s=settings.outbox_lease_s, max_attempts=settings.outbox_max_attempts
        )
        stoppers.append(notifier.stop)
        jobs.append(notifier.run())
        closers.append(bot.session.close)

        async def _polling() -> None:
            await bot.set_my_commands(COMMANDS)
            await dp.start_polling(bot, handle_signals=False)

        bot_main = _polling()

        pending: set[asyncio.Future[Any]] = set()

        def _stop_polling() -> None:
            fut = asyncio.ensure_future(dp.stop_polling())
            pending.add(fut)
            fut.add_done_callback(pending.discard)

        stoppers.append(_stop_polling)
    else:
        log.warning("POLYBOT_TELEGRAM_BOT_TOKEN is not set: collecting and scanning without the Telegram bot")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - windows
            loop.add_signal_handler(sig, lambda: [s() for s in stoppers])

    tasks = [asyncio.create_task(j) for j in jobs]
    if bot_main is not None:
        tasks.append(asyncio.create_task(bot_main))
    for t in tasks:
        t.add_done_callback(_report_crash)
    log.info("polybot is running", extra={"database": res.engine.url.render_as_string(hide_password=True)})
    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for close in closers:
            await close()
        for a in adapters:
            await a.aclose()
        await res.engine.dispose()


def _report_crash(task: asyncio.Task[Any]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("a polybot job stopped with an error", exc_info=task.exception())
