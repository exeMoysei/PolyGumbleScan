"""Integration tests: the whole flow against a real database, without secrets or network access.

By default they run on SQLite (a temporary file) with the in-memory quote cache, so plain ``pytest`` covers them.
Set POLYBOT_TEST_DATABASE_URL (postgresql+asyncpg://...) and POLYBOT_TEST_REDIS_URL to run them on
PostgreSQL + Redis, as CI does.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot.data.db import create_schema, make_engine, make_sessionmaker
from polybot.data.quote_cache import MemoryQuoteStore, QuoteStore, RedisQuoteStore
from polybot.data.tables import Base

DB_URL = os.environ.get("POLYBOT_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("POLYBOT_TEST_REDIS_URL")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


class MemoryCache:
    """Stands in for Redis when POLYBOT_TEST_REDIS_URL is not set."""

    def __init__(self) -> None:
        self.store = MemoryQuoteStore()

    async def flushdb(self) -> None:
        self.store.data.clear()


def quote_store(cache: Any) -> QuoteStore:
    return cache.store if isinstance(cache, MemoryCache) else RedisQuoteStore(cache)


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    """On PostgreSQL apply the real Alembic migrations once (also tests that they run cleanly up and down)."""
    if not DB_URL:
        return
    from alembic import command
    from alembic.config import Config

    os.environ["POLYBOT_DATABASE_URL"] = DB_URL
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if DB_URL:
        engine = make_engine(DB_URL)
        async with engine.begin() as conn:
            tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    else:
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'polybot.db'}")
        await create_schema(engine)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[Any]:
    if not REDIS_URL:
        yield MemoryCache()
        return
    from redis.asyncio import Redis

    r = Redis.from_url(REDIS_URL)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
