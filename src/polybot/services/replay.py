"""Replay: recompute opportunities from a historical quote snapshot (never uses quotes after ``at``)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from polybot.codec import dec_quote
from polybot.domain.models import FxTable
from polybot.services.pipeline import index_quotes
from polybot.services.scan import load_bundles
from polybot.services.scanner import OpportunityDraft, ScanConfig, scan_key
from polybot.storage import repo


async def replay_db(
    s: AsyncSession, at: datetime, cfg: ScanConfig, fx: FxTable, lookback: timedelta = timedelta(hours=1)
) -> tuple[list[OpportunityDraft], dict[str, int]]:
    """Mapping approvals are taken as they are now; quotes strictly as of ``at``."""
    docs = await repo.quotes_as_of(s, at, lookback)
    quotes = [dec_quote(d) for d in docs]
    quotes = [q for q in quotes if q.source_at <= at and q.received_at <= at]
    idx = index_quotes(quotes)
    bundles = await load_bundles(s)
    venues = await repo.venues(s)
    drafts: list[OpportunityDraft] = []
    rejections: dict[str, int] = {}
    for key, b in bundles.items():
        res = scan_key(key, b.space, b.event, b.proposals, idx, venues, cfg, fx, at)
        drafts += res.drafts
        for k, v in res.rejections.items():
            rejections[k] = rejections.get(k, 0) + v
    return drafts, rejections
