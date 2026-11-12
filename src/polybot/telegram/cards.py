"""Pure rendering of opportunity cards (Telegram HTML)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any

from polybot.domain.money import fmt_money

REASONS = {
    "limits_unknown": "venue limits unknown",
    "aggregator_freshness": "price freshness confirmed only by the aggregator",
    "rules_assumed": "bookmaker rules are assumed defaults — verify them",
    "exceptional_loss_possible": "a loss is possible if the game is cancelled or postponed",
    "exceptional_unknown": "settlement on cancellation/postponement is not covered by the rules",
    "no_longer_profitable": "the opportunity is gone",
    "quote_missing": "quote unavailable",
    "quote_stale": "quote is stale",
    "quote_not_open": "market closed or suspended",
    "event_started": "the event has started",
    "negative_pnl": "negative result",
    "below_threshold": "profit below the threshold",
    "no_edge_top_of_book": "no edge at the best prices",
    "fx_stale": "FX rate is stale",
    "fx_missing": "FX rate missing",
    "solver_limit": "solver limit exceeded",
}
POLICY = {
    "win": "win",
    "lose": "loss",
    "refund": "stake refunded (fees are not refunded)",
    "half": "settles 50/50",
    "no_wins": 'settles "No"',
    "carry": "position stays open until the game is played",
    "unknown": "❓ not stated",
}
SPORT_ICON = {"nba": "🏀", "nfl": "🏈", "nhl": "🏒", "mlb": "⚾", "epl": "⚽"}
PERIODS = {"full_game": "full game (incl. overtime)", "regulation": "regulation time"}
MARKETS = {"moneyline": "Winner", "match_result": "1X2 result", "total": "Total"}
ROUTES = {
    "prediction_prediction": "prediction ↔ prediction",
    "prediction_sportsbook": "prediction ↔ sportsbook",
    "sportsbook_sportsbook": "sportsbook ↔ sportsbook",
}


def reason_text(code: str) -> str:
    base = code.split(":")[0]
    return REASONS.get(base, code)


def _signed(v: Decimal) -> str:
    s = fmt_money(v)
    return s if v < 0 else f"+{s}"


def _t(iso: str, fmt: str = "%d.%m %H:%M") -> str:
    return datetime.fromisoformat(iso).strftime(fmt) + " UTC"


def render_card(p: dict[str, Any], *, header: str | None = None) -> str:
    ccy = p["currency"]
    signal = p["verdict"] == "signal"
    title = header or ("✅ <b>SIGNAL</b>" if signal else "🟡 <b>CANDIDATE</b> (with risk)")
    ev = p["event"]
    lines = [
        f"{title} · {ROUTES.get(p['route'], p['route'])}",
        f"{SPORT_ICON.get(ev['league'], '🎯')} <b>{escape(ev['league'].upper())}</b> · {escape(ev['title'])}",
        f"🕒 Start: {_t(ev['start_at'])} · {MARKETS.get(p['market_type'], p['market_type'])}, "
        f"{PERIODS.get(p['period'], p['period'])}",
        "",
        f"<b>Bets</b> (budget {fmt_money(Decimal(p['budget']), ccy)}):",
    ]
    for i, leg in enumerate(p["legs"], start=1):
        size, avg, best = Decimal(leg["size"]), Decimal(leg["avg_price"]), Decimal(leg["best_price"])
        avail = leg.get("available")
        avail_s = f"available {Decimal(avail):,.0f}".replace(",", " ") if avail is not None else "limit: unknown"
        lines.append(f"{i}) <b>{escape(leg['venue']['name'])}</b> — {escape(leg['selection']['label'])}")
        if leg["is_prediction"]:
            fee = Decimal(leg["fee"] or "0")
            fee_s = f", fee {fmt_money(fee)}" if fee else ""
            lines.append(
                f"   buy {size:f} contracts at avg {avg:.4f} (best {best}){fee_s} = "
                f"<b>{fmt_money(Decimal(leg['cost']), ccy)}</b> · {avail_s}"
            )
        else:
            lines.append(f"   stake <b>{fmt_money(size, leg['currency'])}</b> @ {best} · {avail_s}")
        if leg.get("payout_win"):
            lines.append(f"   payout if it wins: {fmt_money(Decimal(leg['payout_win']), ccy)}")
    lines += ["", "<b>Result by scenario:</b>"]
    regular = [x for x in p["pnl"] if x["kind"] == "regular"]
    exceptional = [x for x in p["pnl"] if x["kind"] == "exceptional"]
    for x in regular:
        lines.append(f"• {escape(x['label'])}: <b>{_signed(Decimal(x['value']))}</b>")
    if exceptional:
        lines.append("<i>Exceptions:</i>")
        for x in exceptional:
            v = "❓ undefined" if x["value"] is None else _signed(Decimal(x["value"]))
            lines.append(f"• {escape(x['label'])}: {v}")
    lines += [
        "",
        f"💰 Min P&amp;L: <b>{_signed(Decimal(p['min_profit']))} {ccy}</b> · ROI "
        f"{Decimal(p['roi']) * 100:.2f}% · invested {fmt_money(Decimal(p['total_cost']), ccy)}",
    ]
    if p.get("reasons"):
        lines.append("⚠️ " + "; ".join(reason_text(r) for r in p["reasons"]))
    links = " · ".join(
        f'<a href="{escape(leg["url"])}">{escape(leg["venue"]["name"])}</a>' for leg in p["legs"] if leg.get("url")
    )
    lines.append(
        f"📸 Snapshot: {_t(p['snapshot_at'], '%H:%M:%S')} · valid until {_t(p['expires_at'], '%H:%M:%S')} · "
        f"rev. {p.get('revision', 1)}"
    )
    if links:
        lines.append(f"🔗 {links}")
    lines.append("<i>You place the bets yourself. Check the price and the limit before entering.</i>")
    return "\n".join(lines)


def render_rules(p: dict[str, Any]) -> str:
    lines = ["📜 <b>Settlement rules per leg</b>"]
    for leg in p["legs"]:
        r = leg["rules"]
        ot = {True: "yes", False: "no", None: "not stated"}[r.get("ot")]
        lines += [
            f"\n<b>{escape(leg['venue']['name'])}</b> — {escape(leg['selection']['label'])}"
            + (" <i>(assumed default rules — verify)</i>" if r.get("assumed") else ""),
            f"• cancellation: {POLICY.get(r['cancel'], r['cancel'])}",
            f"• postponement: {POLICY.get(r['postpone'], r['postpone'])}",
            f"• tie (when the market has no draw outcome): {POLICY.get(r['draw'], r['draw'])}",
            f"• overtime counts: {ot}",
        ]
        if leg.get("rules_url"):
            lines.append(f'• <a href="{escape(leg["rules_url"])}">rules source</a>')
        lines.append(f"• rules version: <code>{escape(leg['rules_version'])}</code>")
    return "\n".join(lines)


def render_closed(p: dict[str, Any], reasons: list[str]) -> str:
    ev = p["event"]
    why = "; ".join(reason_text(r) for r in reasons) or "the opportunity is gone"
    return (
        f"❌ <b>Signal closed</b> · {escape(ev['title'])}\nReason: {escape(why)}\nLast revision: {p.get('revision', 1)}"
    )
