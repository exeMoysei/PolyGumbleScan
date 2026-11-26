"""Database engine. PostgreSQL in production; SQLite (one local file) is enough to start and for development."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from polybot.data.tables import Base


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def make_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    if is_sqlite(url):
        engine = create_async_engine(url, echo=echo, connect_args={"timeout": 30})

        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return engine
    return create_async_engine(url, echo=echo, pool_pre_ping=True, pool_size=5, max_overflow=5)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create all tables directly (SQLite / local runs). PostgreSQL uses the Alembic migrations instead."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
