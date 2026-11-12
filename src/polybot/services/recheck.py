"""Re-check one opportunity with fresh quotes for exactly its legs: new revision or close."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from polybot.adapters.base import Adapter
from polybot.codec import dec_market, dec_quote, dec_selection, dec_space, dec_venue
from polybot.domain.enums import MappingStatus
from polybot.domain.models import FxTable, ProviderMarket, Quote
from polybot.matching.markets import CanonicalOutcome, MarketProposal
from polybot.services.pipeline import index_quotes
from polybot.services.scanner import EventInfo, OpportunityDraft, ScanConfig, fingerprint, scan_key


@dataclass(frozen=True, slots=True)
class RecheckResult:
    draft: OpportunityDraft | None
    reasons: tuple[str, ...]


def rebuild(payload: dict[str, Any]) -> tuple[list[MarketProposal], EventInfo, dict[str, Any]]:
    ev = payload["event"]
    event = EventInfo(
        ev["id"], ev["league"], ev["title"], datetime.fromisoformat(ev["start_at"]), ev["home"], ev["away"]
    )
    space = dec_space(payload["space"])
    props = []
    venues = {}
    for leg in payload["legs"]:
        market = dec_market(leg["market"])
        outcome = next(o for o in market.outcomes if o.external_id == leg["outcome_id"])
        props.append(
            MarketProposal(
                market,
                ev["id"],
                payload["key"],
                space,
                (CanonicalOutcome(outcome, dec_selection(leg["selection"])),),
                MappingStatus.APPROVED,
                (),
                market.rules.version,
                {},
            )
        )
        v = dec_venue(leg["venue"])
        venues[v.id] = v
    return props, event, venues


async def fetch_fresh(payload: dict[str, Any], adapters: Sequence[Adapter]) -> list[Quote]:
    by_provider: dict[str, list[ProviderMarket]] = {}
    for leg in payload["legs"]:
        m = dec_market(leg["market"])
        by_provider.setdefault(m.provider, []).append(m)
    quotes: list[Quote] = []
    for a in adapters:
        if a.id in by_provider:
            quotes += await a.snapshot(by_provider[a.id])
    return quotes


def recheck_with(
    payload: dict[str, Any], quotes: Sequence[Quote], cfg: ScanConfig, fx: FxTable, now: datetime
) -> RecheckResult:
    props, event, venues = rebuild(payload)
    wanted = {(leg["venue"]["id"], leg["market"]["external_id"], leg["outcome_id"]) for leg in payload["legs"]}
    fresh = [q for q in quotes if q.key in wanted]
    if len(fresh) < len(wanted):
        return RecheckResult(None, ("quote_missing",))
    res = scan_key(
        payload["key"],
        props[0].space or dec_space(payload["space"]),
        event,
        props,
        index_quotes(fresh),
        venues,
        cfg,
        fx,
        now,
    )
    # Older stored cards used an identity without the budget. Recheck their original legs and
    # publish the result under the new identity so different budgets keep independent revisions.
    match = [
        d
        for d in res.drafts
        if d.fingerprint == payload["fingerprint"]
        or fingerprint(d.canonical_market_key, d.offers) == payload["fingerprint"]
    ]
    if match:
        return RecheckResult(match[0], ())
    return RecheckResult(None, tuple(res.rejections) or ("no_longer_profitable",))


def original_quotes(payload: dict[str, Any]) -> list[Quote]:
    return [dec_quote(leg["quote"]) for leg in payload["legs"]]
