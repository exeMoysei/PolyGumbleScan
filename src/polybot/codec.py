"""JSON-safe encoding of domain objects (Decimal -> str, datetime -> ISO UTC)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from polybot.domain.enums import (
    FreshnessSource,
    MarketType,
    Period,
    QuoteKind,
    QuoteStatus,
    SettlementPolicy,
    VenueKind,
)
from polybot.domain.models import (
    PriceLevel,
    ProviderMarket,
    ProviderOutcome,
    Quote,
    RuleSet,
    Selection,
    Venue,
)
from polybot.domain.scenarios import ScenarioSpace, build_space


def _d(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


def _pd(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _dt(v: datetime) -> str:
    return v.isoformat()


def _pdt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def enc_quote(q: Quote) -> dict[str, Any]:
    return {
        "venue_id": q.venue_id,
        "provider": q.provider,
        "market": q.market_external_id,
        "outcome": q.outcome_external_id,
        "kind": q.kind.value,
        "levels": [[_d(lv.price), _d(lv.size)] for lv in q.levels],
        "currency": q.currency,
        "source_at": _dt(q.source_at),
        "received_at": _dt(q.received_at),
        "freshness": q.freshness.value,
        "sequence": q.sequence,
        "status": q.status.value,
        "min_size": _d(q.min_size),
        "size_step": _d(q.size_step),
        "max_size": _d(q.max_size),
        "tick_size": _d(q.tick_size),
        "fee_params": [list(p) for p in q.fee_params],
        "url": q.url,
        "raw_hash": q.raw_hash,
    }


def dec_quote(d: dict[str, Any]) -> Quote:
    return Quote(
        venue_id=d["venue_id"],
        provider=d["provider"],
        market_external_id=d["market"],
        outcome_external_id=d["outcome"],
        kind=QuoteKind(d["kind"]),
        levels=tuple(PriceLevel(Decimal(p), _pd(s)) for p, s in d["levels"]),
        currency=d["currency"],
        source_at=_pdt(d["source_at"]),
        received_at=_pdt(d["received_at"]),
        freshness=FreshnessSource(d["freshness"]),
        sequence=d.get("sequence"),
        status=QuoteStatus(d["status"]),
        min_size=_pd(d.get("min_size")),
        size_step=_pd(d.get("size_step")),
        max_size=_pd(d.get("max_size")),
        tick_size=_pd(d.get("tick_size")),
        fee_params=tuple((str(a), str(b)) for a, b in d.get("fee_params", [])),
        url=d.get("url"),
        raw_hash=d.get("raw_hash"),
    )


def enc_rules(r: RuleSet) -> dict[str, Any]:
    return {
        "provider": r.provider,
        "period": r.period.value,
        "on_cancel": r.on_cancel.value,
        "on_postpone": r.on_postpone.value,
        "on_draw": r.on_draw.value,
        "cutoff": r.postpone_cutoff_hours,
        "ot": r.includes_overtime,
        "source": r.result_source,
        "url": r.url,
        "text": r.text,
        "assumed": r.assumed,
        "version": r.version,
    }


def dec_rules(d: dict[str, Any]) -> RuleSet:
    return RuleSet(
        provider=d["provider"],
        period=Period(d["period"]),
        on_cancel=SettlementPolicy(d["on_cancel"]),
        on_postpone=SettlementPolicy(d["on_postpone"]),
        on_draw=SettlementPolicy(d.get("on_draw", "unknown")),
        postpone_cutoff_hours=d.get("cutoff"),
        includes_overtime=d.get("ot"),
        result_source=d.get("source"),
        url=d.get("url"),
        text=d.get("text", ""),
        assumed=bool(d.get("assumed")),
    )


def enc_selection(s: Selection) -> dict[str, Any]:
    return {
        "key": s.key,
        "label": s.label,
        "wins": sorted(s.wins),
        "pushes": sorted(s.pushes),
        "undefined": sorted(s.undefined),
        "negated": s.negated,
    }


def dec_selection(d: dict[str, Any]) -> Selection:
    return Selection(
        key=d["key"],
        label=d["label"],
        wins=frozenset(d["wins"]),
        pushes=frozenset(d["pushes"]),
        undefined=frozenset(d.get("undefined", [])),
        negated=bool(d.get("negated")),
    )


def enc_market(m: ProviderMarket) -> dict[str, Any]:
    return {
        "provider": m.provider,
        "external_id": m.external_id,
        "event": m.external_event_id,
        "type": m.market_type.value,
        "period": m.period.value,
        "outcomes": [
            {"id": o.external_id, "label": o.label, "subject": o.subject, "negated": o.negated} for o in m.outcomes
        ],
        "rules": enc_rules(m.rules),
        "line": _d(m.line),
        "unit": m.line_unit,
        "url": m.url,
        "title": m.title,
        "status": m.status,
        "fee_params": [list(p) for p in m.fee_params],
    }


def dec_market(d: dict[str, Any]) -> ProviderMarket:
    return ProviderMarket(
        provider=d["provider"],
        external_id=d["external_id"],
        external_event_id=d["event"],
        market_type=MarketType(d["type"]),
        period=Period(d["period"]),
        outcomes=tuple(
            ProviderOutcome(o["id"], o["label"], o["subject"], bool(o.get("negated"))) for o in d["outcomes"]
        ),
        rules=dec_rules(d["rules"]),
        line=_pd(d.get("line")),
        line_unit=d.get("unit"),
        url=d.get("url"),
        title=d.get("title", ""),
        status=d.get("status", "open"),
        fee_params=tuple((str(a), str(b)) for a, b in d.get("fee_params", [])),
    )


def enc_space(s: ScenarioSpace) -> dict[str, Any]:
    return {
        "sport": s.sport,
        "type": s.market_type.value,
        "period": s.period.value,
        "teams": list(s.teams),
        "line": _d(s.line),
        "labels": {sc.id: sc.label for sc in s.all},
    }


def dec_space(d: dict[str, Any]) -> ScenarioSpace:
    home, away = d["teams"]
    space = build_space(d["sport"], MarketType(d["type"]), Period(d["period"]), (home, away), _pd(d.get("line")))
    labels: dict[str, str] = d.get("labels") or {}
    if labels:
        space = replace(
            space,
            regular=tuple(replace(sc, label=labels.get(sc.id, sc.label)) for sc in space.regular),
            exceptional=tuple(replace(sc, label=labels.get(sc.id, sc.label)) for sc in space.exceptional),
        )
    return space


def enc_venue(v: Venue) -> dict[str, Any]:
    return {"id": v.id, "source": v.source, "kind": v.kind.value, "name": v.name, "region": v.region}


def dec_venue(d: dict[str, Any]) -> Venue:
    return Venue(d["id"], d["source"], VenueKind(d["kind"]), d["name"], d.get("region"))
