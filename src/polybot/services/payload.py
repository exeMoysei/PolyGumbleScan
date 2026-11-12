"""Opportunity payload: everything needed to render the card and to re-check the exact legs later."""

from __future__ import annotations

from typing import Any

from polybot.codec import _d, enc_market, enc_quote, enc_selection, enc_space, enc_venue
from polybot.domain.enums import ScenarioKind
from polybot.services.scanner import OpportunityDraft


def draft_payload(d: OpportunityDraft) -> dict[str, Any]:
    labels = {sc.id: sc.label for sc in d.space.all}
    kinds = {sc.id: sc.kind.value for sc in d.space.all}
    legs = []
    for pl, leg, offer in zip(d.plan.legs, d.legs, d.offers, strict=True):
        available = leg.quote.total_size if leg.is_prediction else leg.max_size
        legs.append(
            {
                "venue": enc_venue(leg.venue),
                "selection": enc_selection(leg.selection),
                "market": enc_market(offer.market),
                "outcome_id": offer.outcome.external_id,
                "quote": enc_quote(leg.quote),
                "size": _d(pl.fill.size),
                "avg_price": _d(pl.fill.avg_price),
                "best_price": _d(leg.quote.best_price),
                "fee": _d(pl.fill.fee),
                "cost": _d(pl.cost),
                "currency": leg.currency,
                "available": _d(available),
                "is_prediction": leg.is_prediction,
                "url": leg.market_url,
                "payout_win": _d(
                    next(
                        (
                            v
                            for sid, v in pl.cashflows
                            if kinds[sid] == ScenarioKind.REGULAR.value and sid in leg.selection.wins and v is not None
                        ),
                        None,
                    )
                ),
                "rules_version": leg.rules.version,
                "rules_url": leg.rules.url,
                "rules": {
                    "cancel": leg.rules.on_cancel.value,
                    "postpone": leg.rules.on_postpone.value,
                    "draw": leg.rules.on_draw.value,
                    "ot": leg.rules.includes_overtime,
                    "assumed": leg.rules.assumed,
                },
            }
        )
    return {
        "fingerprint": d.fingerprint,
        "key": d.canonical_market_key,
        "event": {
            "id": d.event.event_id,
            "league": d.event.league,
            "title": d.event.title,
            "start_at": d.event.start_at.isoformat(),
            "home": d.event.home,
            "away": d.event.away,
        },
        "space": enc_space(d.space),
        "period": d.space.period.value,
        "market_type": d.space.market_type.value,
        "route": d.route.value,
        "verdict": d.verdict.value,
        "reasons": list(d.reasons),
        "legs": legs,
        "pnl": [{"id": sid, "label": labels[sid], "kind": kinds[sid], "value": _d(v)} for sid, v in d.plan.pnl],
        "total_cost": _d(d.plan.total_cost),
        "min_profit": _d(d.plan.worst_regular),
        "worst_exceptional": _d(d.plan.worst_exceptional),
        "roi": _d(d.plan.roi),
        "budget": _d(d.budget),
        "currency": d.budget_currency,
        "snapshot_at": d.snapshot_at.isoformat(),
        "created_at": d.created_at.isoformat(),
        "expires_at": d.expires_at.isoformat(),
        "calc_version": d.calc_version,
        "signature": "|".join(d.material_signature()),
    }
