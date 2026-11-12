"""Integration tests need PostgreSQL and Redis; they never need secrets or network access.

Set POLYBOT_TEST_DATABASE_URL (postgresql+asyncpg://...) and POLYBOT_TEST_REDIS_URL to run them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot.storage.db import make_engine, make_sessionmaker
from polybot.storage.models import Base

DB_URL = os.environ.get("POLYBOT_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("POLYBOT_TEST_REDIS_URL")
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if DB_URL and REDIS_URL:
        return
    skip = pytest.mark.skip(reason="POLYBOT_TEST_DATABASE_URL / POLYBOT_TEST_REDIS_URL not set")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    """Apply the real Alembic migrations once (also tests that they run cleanly up and down)."""
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
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert DB_URL
    engine = make_engine(DB_URL)
    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    from redis.asyncio import Redis

    assert REDIS_URL
    r = Redis.from_url(REDIS_URL)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
