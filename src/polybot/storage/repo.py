"""Queries and transactions. Every function takes an open session; callers own the transaction."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from polybot.codec import enc_market, enc_quote, enc_rules, enc_selection, enc_space
from polybot.domain.enums import MappingStatus, OpportunityStatus, Verdict
from polybot.domain.models import Capabilities, ProviderEvent, ProviderMarket, Quote, Venue
from polybot.matching.events import EventCluster
from polybot.matching.markets import MarketProposal, revalidate
from polybot.services.payload import draft_payload
from polybot.services.scanner import OpportunityDraft
from polybot.storage.models import (
    AdminAction,
    CanonicalEvent,
    HiddenOpportunity,
    MarketMapping,
    MarketRow,
    Opportunity,
    Outbox,
    OutcomeRow,
    Provider,
    ProviderEventRow,
    QuoteSnapshot,
    RuleSetRow,
    ScanRejection,
    Subscription,
    SystemFlag,
    TeamAlias,
)

PUBLISHING_PAUSED = "publishing_paused"


# ----------------------------------------------------------------------------- providers / catalog
async def upsert_venues(s: AsyncSession, venues: Iterable[Venue], caps: dict[str, Capabilities]) -> None:
    for v in venues:
        cap = caps.get(v.source)
        stmt = insert(Provider).values(
            id=v.id,
            source=v.source,
            kind=v.kind.value,
            name=v.name,
            region=v.region,
            capabilities=cap.as_dict() if cap else {},
            enabled=True,
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[Provider.id],
                set_={"name": stmt.excluded.name, "capabilities": stmt.excluded.capabilities, "updated_at": func.now()},
            )
        )


async def upsert_source(s: AsyncSession, source: str, kind: str, caps: Capabilities | None) -> None:
    """Data source row (adapter); venues reference their source by id."""
    stmt = insert(Provider).values(
        id=source,
        source=source,
        kind=kind,
        name=source,
        region=None,
        capabilities=caps.as_dict() if caps else {},
        enabled=True,
    )
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=[Provider.id], set_={"capabilities": stmt.excluded.capabilities, "updated_at": func.now()}
        )
    )


async def venues(s: AsyncSession) -> dict[str, Venue]:
    from polybot.domain.enums import VenueKind

    rows = await s.execute(select(Provider))
    return {p.id: Venue(p.id, p.source, VenueKind(p.kind), p.name, p.region) for p in rows.scalars()}


async def upsert_events(s: AsyncSession, events: Sequence[ProviderEvent]) -> None:
    for e in events:
        stmt = insert(ProviderEventRow).values(
            provider=e.provider,
            external_id=e.external_id,
            league=e.league,
            title=e.title,
            participants=list(e.participants),
            start_at=e.start_at,
            start_precision=e.start_precision.value,
            url=e.url,
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[ProviderEventRow.provider, ProviderEventRow.external_id],
                set_={
                    "title": stmt.excluded.title,
                    "start_at": stmt.excluded.start_at,
                    "participants": stmt.excluded.participants,
                    "updated_at": func.now(),
                },
            )
        )


async def upsert_markets(s: AsyncSession, markets: Sequence[ProviderMarket]) -> dict[tuple[str, str], int]:
    ids: dict[tuple[str, str], int] = {}
    for m in markets:
        r = m.rules
        rs = insert(RuleSetRow).values(
            provider=m.provider, version=r.version, text_hash=r.text_hash, url=r.url, text=r.text, fields=enc_rules(r)
        )
        await s.execute(rs.on_conflict_do_nothing(index_elements=[RuleSetRow.provider, RuleSetRow.version]))
        stmt = insert(MarketRow).values(
            provider=m.provider,
            external_id=m.external_id,
            external_event_id=m.external_event_id,
            market_type=m.market_type.value,
            period=m.period.value,
            line=m.line,
            line_unit=m.line_unit,
            url=m.url,
            title=m.title[:256],
            status=m.status,
            rules_version=r.version,
            data=enc_market(m),
        )
        res = await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[MarketRow.provider, MarketRow.external_id],
                set_={
                    "status": stmt.excluded.status,
                    "rules_version": stmt.excluded.rules_version,
                    "data": stmt.excluded.data,
                    "period": stmt.excluded.period,
                    "line": stmt.excluded.line,
                    "url": stmt.excluded.url,
                    "updated_at": func.now(),
                },
            ).returning(MarketRow.id)
        )
        mid = res.scalar_one()
        ids[(m.provider, m.external_id)] = mid
        for o in m.outcomes:
            os_ = insert(OutcomeRow).values(
                market_id=mid,
                external_outcome_id=o.external_id,
                label=o.label[:128],
                description=f"{'NOT ' if o.negated else ''}{o.subject}"[:256],
            )
            await s.execute(
                os_.on_conflict_do_nothing(index_elements=[OutcomeRow.market_id, OutcomeRow.external_outcome_id])
            )
    return ids


async def upsert_clusters(s: AsyncSession, clusters: Sequence[EventCluster], titles: dict[str, str]) -> None:
    for c in clusters:
        home, away, known = c.roles()
        stmt = insert(CanonicalEvent).values(
            id=c.id,
            sport=c.sport,
            league=c.league,
            home_team_id=home,
            away_team_id=away,
            roles_known=known,
            start_at=c.start_at,
            start_exact=c.start_exact,
            game_number=c.game_number,
            title=titles.get(c.id, c.id)[:256],
            confidence=Decimal(str(c.confidence)),
            reasons=list(c.reasons),
        )
        await s.execute(
            stmt.on_conflict_do_update(
                index_elements=[CanonicalEvent.id],
                set_={
                    "start_at": stmt.excluded.start_at,
                    "confidence": stmt.excluded.confidence,
                    "reasons": stmt.excluded.reasons,
                    "home_team_id": stmt.excluded.home_team_id,
                    "away_team_id": stmt.excluded.away_team_id,
                    "roles_known": stmt.excluded.roles_known,
                    "updated_at": func.now(),
                },
            )
        )
        for m in c.members:
            await s.execute(
                update(ProviderEventRow)
                .where(ProviderEventRow.provider == m.provider, ProviderEventRow.external_id == m.event.external_id)
                .values(canonical_event_id=c.id)
            )


# ----------------------------------------------------------------------------- mappings
def _proposal_doc(p: MarketProposal) -> dict[str, Any]:
    return {
        "outcomes": [
            {"outcome_id": co.outcome.external_id, "label": co.outcome.label, "selection": enc_selection(co.selection)}
            for co in p.outcomes
        ],
        "space": enc_space(p.space) if p.space else None,
        "market": enc_market(p.market),
    }


@dataclass(frozen=True, slots=True)
class MappingChange:
    mapping_id: int
    canonical_market_key: str
    provider: str
    market_external_id: str
    status: MappingStatus
    previous: MappingStatus | None
    reasons: tuple[str, ...]


async def sync_mapping(
    s: AsyncSession, market_id: int, p: MarketProposal, *, auto_approve: bool = False, now: datetime
) -> MappingChange | None:
    """Create or revalidate the mapping of one market. Returns a change worth telling admins about."""
    row = (await s.execute(select(MarketMapping).where(MarketMapping.market_id == market_id))).scalar_one_or_none()
    doc = _proposal_doc(p)
    if row is None:
        status = p.status
        if auto_approve and status == MappingStatus.PENDING:
            status = MappingStatus.APPROVED
        row = MarketMapping(
            market_id=market_id,
            canonical_event_id=p.event_id,
            canonical_market_key=p.canonical_market_key,
            rules_version=p.rules_version,
            params=p.params,
            params_fingerprint=p.fingerprint,
            status=status.value,
            reasons=list(p.reasons),
            proposal=doc,
        )
        if status == MappingStatus.APPROVED:
            row.approved_rules_version, row.approved_params = p.rules_version, p.params
            row.decided_at, row.decision_reason = now, "auto_approved_strong_match"
        s.add(row)
        await s.flush()
        return MappingChange(
            row.id, p.canonical_market_key, p.market.provider, p.market.external_id, status, None, p.reasons
        )
    prev = MappingStatus(row.status)
    rv = revalidate(prev, row.approved_rules_version, row.approved_params, p)
    changed_params = row.params_fingerprint != p.fingerprint or row.rules_version != p.rules_version
    row.rules_version, row.params, row.params_fingerprint = p.rules_version, p.params, p.fingerprint
    row.canonical_market_key, row.canonical_event_id, row.proposal = p.canonical_market_key, p.event_id, doc
    if prev == MappingStatus.APPROVED and rv.status == MappingStatus.INVALIDATED:
        row.status, row.reasons, row.decision_reason = rv.status.value, [rv.reason or "changed"], rv.reason
        return MappingChange(
            row.id,
            p.canonical_market_key,
            p.market.provider,
            p.market.external_id,
            rv.status,
            prev,
            (rv.reason or "changed",),
        )
    if prev in (MappingStatus.REJECTED, MappingStatus.INVALIDATED) and changed_params:
        row.status, row.reasons = p.status.value, list(p.reasons)
        return MappingChange(
            row.id, p.canonical_market_key, p.market.provider, p.market.external_id, p.status, prev, p.reasons
        )
    if prev in (MappingStatus.PENDING, MappingStatus.NEEDS_REVIEW):
        row.status, row.reasons = p.status.value, list(p.reasons)
    return None


async def decide_mapping(
    s: AsyncSession, mapping_id: int, approve: bool, user_id: int, reason: str | None, now: datetime
) -> MarketMapping | None:
    row = await s.get(MarketMapping, mapping_id, with_for_update=True)
    if row is None:
        return None
    if approve:
        row.status = MappingStatus.APPROVED.value
        row.approved_rules_version, row.approved_params = row.rules_version, row.params
    else:
        row.status = MappingStatus.REJECTED.value
    row.decided_by, row.decided_at, row.decision_reason = user_id, now, reason
    s.add(
        AdminAction(
            user_id=user_id,
            action="approve" if approve else "reject",
            target=f"mapping:{mapping_id}",
            details={"reason": reason, "rules_version": row.rules_version},
        )
    )
    return row


async def approved_markets(s: AsyncSession) -> set[tuple[str, str, str]]:
    """{(provider, market_external_id, rules_version)} with a valid approval."""
    rows = await s.execute(
        select(
            MarketRow.provider,
            MarketRow.external_id,
            MarketMapping.approved_rules_version,
            MarketMapping.approved_params,
            MarketMapping.params,
        )
        .join(MarketMapping, MarketMapping.market_id == MarketRow.id)
        .where(MarketMapping.status == MappingStatus.APPROVED.value)
    )
    out = set()
    for prov, ext, rv, ap, params in rows:
        if rv and ap == params:
            out.add((prov, ext, rv))
    return out


async def pending_mappings(s: AsyncSession, limit: int = 10) -> list[tuple[MarketMapping, MarketRow]]:
    rows = await s.execute(
        select(MarketMapping, MarketRow)
        .join(MarketRow, MarketRow.id == MarketMapping.market_id)
        .where(
            MarketMapping.status.in_(
                [MappingStatus.PENDING.value, MappingStatus.NEEDS_REVIEW.value, MappingStatus.INVALIDATED.value]
            )
        )
        .order_by(MarketMapping.canonical_market_key, MarketMapping.id)
        .limit(limit)
    )
    return [(m, r) for m, r in rows]


async def add_team_alias(s: AsyncSession, league: str, alias: str, team_id: str, user_id: int) -> None:
    stmt = insert(TeamAlias).values(league=league, alias=alias, team_id=team_id, added_by=user_id)
    await s.execute(
        stmt.on_conflict_do_update(index_elements=[TeamAlias.league, TeamAlias.alias], set_={"team_id": team_id})
    )


async def team_aliases(s: AsyncSession) -> list[tuple[str, str, str]]:
    rows = await s.execute(select(TeamAlias.league, TeamAlias.alias, TeamAlias.team_id))
    return [(str(a), str(b), str(c)) for a, b, c in rows]


# ----------------------------------------------------------------------------- quotes history
async def store_quote_snapshots(s: AsyncSession, quotes: Sequence[Quote]) -> int:
    if not quotes:
        return 0
    rows = [
        dict(
            venue_id=q.venue_id,
            provider=q.provider,
            market_external_id=q.market_external_id,
            outcome_external_id=q.outcome_external_id,
            status=q.status.value,
            best_price=q.best_price,
            source_at=q.source_at,
            received_at=q.received_at,
            sequence=q.sequence,
            raw_hash=q.raw_hash,
            data=enc_quote(q),
        )
        for q in quotes
    ]
    await s.execute(insert(QuoteSnapshot), rows)
    return len(rows)


async def quotes_as_of(s: AsyncSession, at: datetime, lookback: timedelta) -> list[dict[str, Any]]:
    """Latest snapshot per (venue, market, outcome) with source_at <= at (never future data)."""
    sub = (
        select(
            QuoteSnapshot.venue_id,
            QuoteSnapshot.market_external_id,
            QuoteSnapshot.outcome_external_id,
            func.max(QuoteSnapshot.id).label("mid"),
        )
        .where(QuoteSnapshot.source_at <= at, QuoteSnapshot.received_at <= at, QuoteSnapshot.source_at >= at - lookback)
        .group_by(QuoteSnapshot.venue_id, QuoteSnapshot.market_external_id, QuoteSnapshot.outcome_external_id)
        .subquery()
    )
    rows = await s.execute(select(QuoteSnapshot.data).join(sub, QuoteSnapshot.id == sub.c.mid))
    return [r for (r,) in rows]


async def purge_old(s: AsyncSession, before: datetime) -> int:
    res = await s.execute(delete(QuoteSnapshot).where(QuoteSnapshot.received_at < before))
    await s.execute(delete(ScanRejection).where(ScanRejection.at < before))
    return int(getattr(res, "rowcount", 0) or 0)


async def record_rejections(s: AsyncSession, key: str, counts: dict[str, int]) -> None:
    if counts:
        await s.execute(
            insert(ScanRejection), [dict(canonical_market_key=key, reason=r[:64], count=n) for r, n in counts.items()]
        )


# ----------------------------------------------------------------------------- subscriptions / flags
async def get_flag(s: AsyncSession, key: str) -> str | None:
    row = await s.get(SystemFlag, key)
    return row.value if row else None


async def set_flag(s: AsyncSession, key: str, value: str, user_id: int | None) -> None:
    stmt = insert(SystemFlag).values(key=key, value=value, updated_by=user_id)
    await s.execute(
        stmt.on_conflict_do_update(
            index_elements=[SystemFlag.key], set_={"value": value, "updated_by": user_id, "updated_at": func.now()}
        )
    )
    if user_id is not None:
        s.add(AdminAction(user_id=user_id, action="flag", target=key, details={"value": value}))


async def ensure_subscription(s: AsyncSession, chat_id: int, user_id: int, budget: Decimal) -> Subscription:
    sub = await s.get(Subscription, chat_id)
    if sub is None:
        sub = Subscription(
            chat_id=chat_id,
            user_id=user_id,
            budget=budget,
            active=True,
            filters={"verdicts": [Verdict.SIGNAL.value, Verdict.CANDIDATE.value]},
        )
        s.add(sub)
    else:
        sub.active = True
    return sub


async def active_subscriptions(s: AsyncSession) -> list[Subscription]:
    return list((await s.execute(select(Subscription).where(Subscription.active.is_(True)))).scalars())


def subscription_accepts(sub: Subscription, payload: dict[str, Any]) -> bool:
    f = sub.filters or {}
    verdicts = f.get("verdicts") or [Verdict.SIGNAL.value]
    if payload["verdict"] not in verdicts:
        return False
    if f.get("routes") and payload["route"] not in f["routes"]:
        return False
    if f.get("leagues") and payload["event"]["league"] not in f["leagues"]:
        return False
    if f.get("min_roi") and Decimal(payload["roi"]) < Decimal(str(f["min_roi"])):
        return False
    return not (f.get("min_profit") and Decimal(payload["min_profit"]) < Decimal(str(f["min_profit"])))


# ----------------------------------------------------------------------------- opportunities + outbox
def _sig_hash(sig: str) -> str:
    return hashlib.sha256(sig.encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PublishResult:
    opportunity_id: int
    revision: int
    created: bool
    material: bool
    outbox_rows: int


async def publish_draft(
    s: AsyncSession,
    d: OpportunityDraft,
    subscribers: Sequence[Subscription],
    now: datetime,
    paused: bool = False,
    reactivate_window: timedelta = timedelta(minutes=30),
) -> PublishResult:
    """Insert/refresh an opportunity and enqueue notifications in the SAME transaction."""
    payload = draft_payload(d)
    sig = _sig_hash(payload["signature"])
    cur = (
        await s.execute(
            select(Opportunity)
            .where(Opportunity.fingerprint == d.fingerprint, Opportunity.status == OpportunityStatus.ACTIVE.value)
            .order_by(Opportunity.revision.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cur is not None and cur.signature == sig:
        cur.expires_at, cur.updated_at = d.expires_at, now
        return PublishResult(cur.id, cur.revision, False, False, 0)
    if cur is None:
        # identical revision closed by a data gap (restart, feed outage, TTL): reactivate, do not re-notify
        last = (
            await s.execute(
                select(Opportunity)
                .where(Opportunity.fingerprint == d.fingerprint)
                .order_by(Opportunity.revision.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            last is not None
            and last.signature == sig
            and last.closed_at is not None
            and now - last.closed_at <= reactivate_window
            and not str(last.closed_reason or "").startswith(("recheck", "mapping"))
        ):
            last.status, last.closed_reason, last.closed_at = OpportunityStatus.ACTIVE.value, None, None
            last.expires_at, last.updated_at = d.expires_at, now
            return PublishResult(last.id, last.revision, False, False, 0)
    revision = 1
    if cur is not None:
        cur.status, cur.closed_reason, cur.closed_at = OpportunityStatus.CLOSED.value, "superseded", now
        revision = cur.revision + 1
    else:
        last_rev = (
            await s.execute(select(func.max(Opportunity.revision)).where(Opportunity.fingerprint == d.fingerprint))
        ).scalar()
        revision = (last_rev or 0) + 1
    payload["revision"] = revision
    opp = Opportunity(
        fingerprint=d.fingerprint,
        revision=revision,
        calc_version=d.calc_version,
        canonical_market_key=d.canonical_market_key,
        canonical_event_id=d.event.event_id,
        route=d.route.value,
        verdict=d.verdict.value,
        status=OpportunityStatus.ACTIVE.value,
        budget=d.budget,
        budget_currency=d.budget_currency,
        total_cost=d.plan.total_cost,
        min_profit=d.plan.worst_regular,
        roi=d.plan.roi,
        signature=sig,
        payload=payload,
        snapshot_at=d.snapshot_at,
        expires_at=d.expires_at,
    )
    s.add(opp)
    await s.flush()
    rows = 0
    if not paused:
        hidden = set(
            (
                await s.execute(select(HiddenOpportunity.chat_id).where(HiddenOpportunity.fingerprint == d.fingerprint))
            ).scalars()
        )
        for sub in subscribers:
            if sub.chat_id in hidden or Decimal(sub.budget) != d.budget or not subscription_accepts(sub, payload):
                continue
            stmt = insert(Outbox).values(
                opportunity_id=opp.id,
                revision=revision,
                chat_id=sub.chat_id,
                kind="signal" if revision == 1 else "update",
                dedup_key=f"{sub.chat_id}:{d.fingerprint}:{revision}",
                expires_at=d.expires_at,
                next_attempt_at=now,
            )
            res = await s.execute(stmt.on_conflict_do_nothing(index_elements=[Outbox.dedup_key]))
            rows += int(getattr(res, "rowcount", 0) or 0)
    return PublishResult(opp.id, revision, cur is None, True, rows)


async def close_opportunities(
    s: AsyncSession, *, keys: set[str], keep: set[str], budget: Decimal, reason: str, now: datetime
) -> int:
    """Close active opportunities of scanned keys that the latest scan no longer produced."""
    if not keys:
        return 0
    stmt = (
        update(Opportunity)
        .where(
            Opportunity.status == OpportunityStatus.ACTIVE.value,
            Opportunity.canonical_market_key.in_(keys),
            Opportunity.budget == budget,
            Opportunity.fingerprint.not_in(keep) if keep else Opportunity.id.is_not(None),
        )
        .values(status=OpportunityStatus.CLOSED.value, closed_reason=reason, closed_at=now)
    )
    res = await s.execute(stmt)
    return int(getattr(res, "rowcount", 0) or 0)


async def expire_opportunities(s: AsyncSession, now: datetime) -> int:
    res = await s.execute(
        update(Opportunity)
        .where(Opportunity.status == OpportunityStatus.ACTIVE.value, Opportunity.expires_at < now)
        .values(status=OpportunityStatus.EXPIRED.value, closed_reason="ttl", closed_at=now)
    )
    await s.execute(update(Outbox).where(Outbox.status == "pending", Outbox.expires_at < now).values(status="expired"))
    return int(getattr(res, "rowcount", 0) or 0)


async def invalidate_by_markets(s: AsyncSession, keys: set[str], now: datetime) -> int:
    if not keys:
        return 0
    res = await s.execute(
        update(Opportunity)
        .where(Opportunity.status == OpportunityStatus.ACTIVE.value, Opportunity.canonical_market_key.in_(keys))
        .values(status=OpportunityStatus.CLOSED.value, closed_reason="mapping_invalidated", closed_at=now)
    )
    return int(getattr(res, "rowcount", 0) or 0)


async def claim_outbox(s: AsyncSession, owner: str, now: datetime, lease: timedelta, limit: int = 20) -> list[Outbox]:
    ids = (
        select(Outbox.id)
        .where(
            Outbox.status == "pending",
            Outbox.next_attempt_at <= now,
            or_(Outbox.lease_until.is_(None), Outbox.lease_until < now),
        )
        .order_by(Outbox.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    res = await s.execute(
        update(Outbox)
        .where(Outbox.id.in_(ids.scalar_subquery()))
        .values(lease_owner=owner, lease_until=now + lease)
        .returning(Outbox)
    )
    return list(res.scalars())


async def outbox_done(
    s: AsyncSession,
    row_id: int,
    owner: str,
    message_id: int | None,
    now: datetime,
    status: str = "sent",
    error: str | None = None,
) -> bool:
    res = await s.execute(
        update(Outbox)
        .where(Outbox.id == row_id, Outbox.lease_owner == owner)
        .values(status=status, message_id=message_id, sent_at=now, lease_owner=None, lease_until=None, last_error=error)
    )
    return bool(getattr(res, "rowcount", 0))


async def outbox_retry(s: AsyncSession, row: Outbox, owner: str, error: str, now: datetime, max_attempts: int) -> str:
    attempts = row.attempts + 1
    delay = timedelta(seconds=min(2**attempts, 300))
    status = "pending"
    if attempts >= max_attempts:
        status = "failed"
    if now + delay > row.expires_at:
        status = "expired"
    await s.execute(
        update(Outbox)
        .where(Outbox.id == row.id, Outbox.lease_owner == owner)
        .values(
            attempts=attempts,
            status=status,
            next_attempt_at=now + delay,
            lease_owner=None,
            lease_until=None,
            last_error=error[:500],
        )
    )
    return status


async def enqueue_text(
    s: AsyncSession,
    chat_ids: Sequence[int],
    text: str,
    dedup: str,
    now: datetime,
    ttl: timedelta = timedelta(hours=6),
    kind: str = "tech",
) -> int:
    n = 0
    for chat_id in chat_ids:
        stmt = insert(Outbox).values(
            opportunity_id=None,
            revision=0,
            chat_id=chat_id,
            kind=kind,
            text=text,
            dedup_key=f"{kind}:{chat_id}:{dedup}"[:128],
            expires_at=now + ttl,
            next_attempt_at=now,
        )
        res = await s.execute(stmt.on_conflict_do_nothing(index_elements=[Outbox.dedup_key]))
        n += int(getattr(res, "rowcount", 0) or 0)
    return n


async def active_opportunities(
    s: AsyncSession, chat_budget: Decimal | None = None, limit: int = 10, now: datetime | None = None
) -> list[Opportunity]:
    q = select(Opportunity).where(Opportunity.status == OpportunityStatus.ACTIVE.value)
    if now is not None:
        q = q.where(Opportunity.expires_at >= now)
    if chat_budget is not None:
        q = q.where(Opportunity.budget == chat_budget)
    q = q.order_by((Opportunity.verdict == Verdict.SIGNAL.value).desc(), Opportunity.min_profit.desc()).limit(limit)
    return list((await s.execute(q)).scalars())


async def latest_revision(s: AsyncSession, fingerprint: str) -> Opportunity | None:
    return (
        await s.execute(
            select(Opportunity)
            .where(Opportunity.fingerprint == fingerprint)
            .order_by(Opportunity.revision.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def hide(s: AsyncSession, chat_id: int, fingerprint: str) -> None:
    await s.execute(insert(HiddenOpportunity).values(chat_id=chat_id, fingerprint=fingerprint).on_conflict_do_nothing())


async def stats(s: AsyncSession, since: datetime) -> dict[str, Any]:
    by_status = dict((await s.execute(select(MarketMapping.status, func.count()).group_by(MarketMapping.status))).all())
    opp = dict(
        (
            await s.execute(
                select(Opportunity.verdict, func.count())
                .where(Opportunity.created_at >= since)
                .group_by(Opportunity.verdict)
            )
        ).all()
    )
    rej = dict(
        (
            await s.execute(
                select(ScanRejection.reason, func.sum(ScanRejection.count))
                .where(ScanRejection.at >= since)
                .group_by(ScanRejection.reason)
                .order_by(func.sum(ScanRejection.count).desc())
                .limit(10)
            )
        ).all()
    )
    shared = (
        await s.execute(
            select(func.count()).select_from(
                select(ProviderEventRow.canonical_event_id)
                .where(ProviderEventRow.canonical_event_id.is_not(None))
                .group_by(ProviderEventRow.canonical_event_id)
                .having(func.count(func.distinct(ProviderEventRow.provider)) > 1)
                .subquery()
            )
        )
    ).scalar()
    outbox = dict(
        (
            await s.execute(
                select(Outbox.status, func.count()).where(Outbox.created_at >= since).group_by(Outbox.status)
            )
        ).all()
    )
    return {"mappings": by_status, "opportunities": opp, "rejections": rej, "shared_events": shared, "outbox": outbox}
