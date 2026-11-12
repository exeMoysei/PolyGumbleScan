from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

MONEY = Numeric(24, 8)
TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        Decimal: MONEY,
        datetime: TS,
    }


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(64))  # adapter / data source
    kind: Mapped[str] = mapped_column(String(16))  # prediction | sportsbook | exchange
    name: Mapped[str] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(16))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    sport: Mapped[str] = mapped_column(String(32))
    league: Mapped[str] = mapped_column(String(16), index=True)
    home_team_id: Mapped[str] = mapped_column(String(32))
    away_team_id: Mapped[str] = mapped_column(String(32))
    roles_known: Mapped[bool] = mapped_column(Boolean, default=False)
    start_at: Mapped[datetime] = mapped_column(TS, index=True)
    start_exact: Mapped[bool] = mapped_column(Boolean, default=True)
    game_number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal(1))
    reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class ProviderEventRow(Base):
    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"))
    external_id: Mapped[str] = mapped_column(String(160))
    league: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    participants: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    start_at: Mapped[datetime] = mapped_column(TS)
    start_precision: Mapped[str] = mapped_column(String(8))
    canonical_event_id: Mapped[str | None] = mapped_column(String(96), ForeignKey("canonical_events.id"), index=True)
    url: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class RuleSetRow(Base):
    __tablename__ = "rule_sets"
    __table_args__ = (UniqueConstraint("provider", "version"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    text_hash: Mapped[str] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class MarketRow(Base):
    __tablename__ = "markets"
    __table_args__ = (UniqueConstraint("provider", "external_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), ForeignKey("providers.id"))
    external_id: Mapped[str] = mapped_column(String(160))
    external_event_id: Mapped[str] = mapped_column(String(160))
    market_type: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(16))
    line: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    line_unit: Mapped[str | None] = mapped_column(String(16))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    rules_version: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)  # codec-encoded ProviderMarket
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class OutcomeRow(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("market_id", "external_outcome_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("markets.id", ondelete="CASCADE"))
    external_outcome_id: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(128))
    selection_key: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(256))


class MarketMapping(Base):
    __tablename__ = "market_mappings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("markets.id", ondelete="CASCADE"), unique=True)
    canonical_event_id: Mapped[str] = mapped_column(String(96), ForeignKey("canonical_events.id"))
    canonical_market_key: Mapped[str] = mapped_column(String(192), index=True)
    rules_version: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    params_fingerprint: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    approved_rules_version: Mapped[str | None] = mapped_column(String(32))
    approved_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)  # outcomes -> selections, space
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class QuoteSnapshot(Base):
    """Raw-ish quote history for reproducibility and replay (bounded retention)."""

    __tablename__ = "quote_snapshots"
    __table_args__ = (Index("ix_quote_snapshots_lookup", "provider", "market_external_id", "source_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    venue_id: Mapped[str] = mapped_column(String(96))
    provider: Mapped[str] = mapped_column(String(64))
    market_external_id: Mapped[str] = mapped_column(String(160))
    outcome_external_id: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    best_price: Mapped[Decimal | None] = mapped_column(MONEY)
    source_at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS, index=True)
    sequence: Mapped[int | None] = mapped_column(BigInteger)
    raw_hash: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)  # codec-encoded Quote


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("fingerprint", "revision"),
        Index("ix_opportunities_active", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(40), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    calc_version: Mapped[str] = mapped_column(String(32))
    canonical_market_key: Mapped[str] = mapped_column(String(192), index=True)
    canonical_event_id: Mapped[str] = mapped_column(String(96))
    route: Mapped[str] = mapped_column(String(32))
    verdict: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    budget: Mapped[Decimal] = mapped_column(MONEY)
    budget_currency: Mapped[str] = mapped_column(String(8))
    total_cost: Mapped[Decimal] = mapped_column(MONEY)
    min_profit: Mapped[Decimal] = mapped_column(MONEY)
    roi: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    signature: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    snapshot_at: Mapped[datetime] = mapped_column(TS)
    expires_at: Mapped[datetime] = mapped_column(TS)
    closed_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(TS)


class ScanRejection(Base):
    __tablename__ = "scan_rejections"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    canonical_market_key: Mapped[str] = mapped_column(String(192))
    reason: Mapped[str] = mapped_column(String(64), index=True)
    count: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), index=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    budget: Mapped[Decimal] = mapped_column(MONEY)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_claim", "status", "next_attempt_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("opportunities.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)  # technical / admin notifications
    kind: Mapped[str] = mapped_column(String(16), default="signal")  # signal | update | close | tech
    dedup_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|sent|failed|expired|uncertain
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(TS)
    expires_at: Mapped[datetime] = mapped_column(TS)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(TS)


class HiddenOpportunity(Base):
    __tablename__ = "hidden_opportunities"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class SystemFlag(Base):
    __tablename__ = "system_flags"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("league", "alias"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    league: Mapped[str] = mapped_column(String(16))
    alias: Mapped[str] = mapped_column(String(128))
    team_id: Mapped[str] = mapped_column(String(32))
    added_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class AdminAction(Base):
    __tablename__ = "admin_actions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(192))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
