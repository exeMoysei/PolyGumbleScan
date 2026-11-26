from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from polybot.data.tables import Base, ExactDecimal, JSONDoc, UTCDateTime

config = context.config
target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Write the portable column types as their PostgreSQL types, so migrations stay plain SQLAlchemy."""
    if type_ == "type":
        if isinstance(obj, ExactDecimal):
            return f"sa.Numeric({obj.precision}, {obj.scale})"
        if isinstance(obj, UTCDateTime):
            return "sa.DateTime(timezone=True)"
        if isinstance(obj, JSONDoc):
            autogen_context.imports.add("from sqlalchemy.dialects import postgresql")  # type: ignore[attr-defined]
            return "postgresql.JSONB(astext_type=sa.Text())"
    return False


def _url() -> str:
    return (
        os.environ.get("POLYBOT_DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or "postgresql+asyncpg://polybot:polybot@localhost:5432/polybot"
    )


def run_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True, render_item=render_item
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, render_item=render_item
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
