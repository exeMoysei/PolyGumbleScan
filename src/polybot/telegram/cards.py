"""Pure rendering of opportunity cards (Telegram HTML)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any

from polybot.domain.money import fmt_money

REASONS_EN = {
    "limits_unknown": "venue limits are unknown",
    "aggregator_freshness": "price freshness is confirmed only by the aggregator",
    "rules_assumed": "sportsbook rules are assumed — verify them",
    "exceptional_loss_possible": "a cancellation or postponement may cause a loss",
    "exceptional_unknown": "cancellation or postponement settlement is unknown",
    "no_longer_profitable": "the opportunity is no longer profitable",
    "quote_missing": "quote is unavailable",
    "quote_stale": "quote has expired",
    "quote_not_open": "market is closed or suspended",
    "event_started": "event has started",
    "negative_pnl": "negative P&L",
    "below_threshold": "profit is below the threshold",
    "no_edge_top_of_book": "no edge at the best prices",
    "fx_stale": "exchange rate has expired",
    "fx_missing": "exchange rate is unavailable",
    "solver_limit": "solver evaluation limit exceeded",
    "mapping_invalidated": "market approval or settlement rules have changed",
    "superseded": "a newer revision is available",
    "ttl": "quote has expired",
}
POLICY_EN = {
    "win": "win",
    "lose": "loss",
    "refund": "stake refunded (fees are not refunded)",
    "half": "50/50 settlement",
    "no_wins": "NO wins",
    "carry": "position carries over to the rescheduled event",
    "unknown": "❓ unknown",
}
SPORT_ICON = {"nba": "🏀", "nfl": "🏈", "nhl": "🏒", "mlb": "⚾", "epl": "⚽"}
PERIOD_EN = {"full_game": "full game (including overtime)", "regulation": "regulation time"}
MARKET_EN = {"moneyline": "Winner", "match_result": "Match result (1X2)", "total": "Total"}
ROUTE_EN = {
    "prediction_prediction": "prediction ↔ prediction",
    "prediction_sportsbook": "prediction ↔ sportsbook",
    "sportsbook_sportsbook": "sportsbook ↔ sportsbook",
}


def reason_en(code: str) -> str:
    base = code.split(":")[0]
    return REASONS_EN.get(base, code)


def english_label(label: str) -> str:
    """Render generated labels from payloads saved before the English-only UI update."""
    exact = {
        "Матч отменён": "Event cancelled",
        "Перенос за пределы отсечки": "Postponed beyond the cutoff",
        "Ничья": "Draw",
        "Не ничья": "Not a draw",
    }
    if label in exact:
        return exact[label]
    for old, new in (
        ("Победа ", "Win: "),
        ("НЕ ", "NOT "),
        ("не ", "NOT "),
        ("Больше ", "Over "),
        ("Меньше ", "Under "),
        ("Тотал ", "Total "),
    ):
        if label.startswith(old):
            return new + label[len(old) :].replace("(возврат)", "(refund)")
    return label


def _signed(v: Decimal) -> str:
    s = fmt_money(v)
    return s if v < 0 else f"+{s}"


def _t(iso: str, fmt: str = "%d.%m %H:%M") -> str:
    return datetime.fromisoformat(iso).strftime(fmt) + " UTC"


def render_card(p: dict[str, Any], *, header: str | None = None) -> str:
    ccy = p["currency"]
    signal = p["verdict"] == "signal"
    title = header or ("✅ <b>SIGNAL</b>" if signal else "🟡 <b>CANDIDATE</b> (risk flagged)")
    ev = p["event"]
    lines = [
        f"{title} · {ROUTE_EN.get(p['route'], p['route'])}",
        f"{SPORT_ICON.get(ev['league'], '🎯')} <b>{escape(ev['league'].upper())}</b> · {escape(ev['title'])}",
        f"🕒 Start: {_t(ev['start_at'])} · {MARKET_EN.get(p['market_type'], p['market_type'])}, "
        f"{PERIOD_EN.get(p['period'], p['period'])}",
        "",
        f"<b>Bets</b> (budget {fmt_money(Decimal(p['budget']), ccy)}):",
    ]
    for i, leg in enumerate(p["legs"], start=1):
        size, avg, best = Decimal(leg["size"]), Decimal(leg["avg_price"]), Decimal(leg["best_price"])
        avail = leg.get("available")
        avail_s = f"available {Decimal(avail):,.0f}".replace(",", " ") if avail is not None else "limit: unknown"
        lines.append(f"{i}) <b>{escape(leg['venue']['name'])}</b> — {escape(english_label(leg['selection']['label']))}")
        if leg["is_prediction"]:
            fee = Decimal(leg["fee"] or "0")
            fee_s = f", fee {fmt_money(fee)}" if fee else ""
            lines.append(
                f"   buy {size:f} contracts at avg. {avg:.4f} (best {best}){fee_s} = "
                f"<b>{fmt_money(Decimal(leg['cost']), ccy)}</b> · {avail_s}"
            )
        else:
            lines.append(f"   stake <b>{fmt_money(size, leg['currency'])}</b> @ {best} · {avail_s}")
        if leg.get("payout_win"):
            lines.append(f"   winning payout: {fmt_money(Decimal(leg['payout_win']), ccy)}")
    lines += ["", "<b>P&amp;L by scenario:</b>"]
    regular = [x for x in p["pnl"] if x["kind"] == "regular"]
    exceptional = [x for x in p["pnl"] if x["kind"] == "exceptional"]
    for x in regular:
        lines.append(f"• {escape(english_label(x['label']))}: <b>{_signed(Decimal(x['value']))}</b>")
    if exceptional:
        lines.append("<i>Exceptions:</i>")
        for x in exceptional:
            v = "❓ unknown" if x["value"] is None else _signed(Decimal(x["value"]))
            lines.append(f"• {escape(english_label(x['label']))}: {v}")
    lines += [
        "",
        f"💰 Min. P&amp;L: <b>{_signed(Decimal(p['min_profit']))} {ccy}</b> · ROI "
        f"{Decimal(p['roi']) * 100:.2f}% · invested {fmt_money(Decimal(p['total_cost']), ccy)}",
    ]
    if p.get("reasons"):
        lines.append("⚠️ " + escape("; ".join(reason_en(r) for r in p["reasons"])))
    links = " · ".join(
        f'<a href="{escape(leg["url"])}">{escape(leg["venue"]["name"])}</a>' for leg in p["legs"] if leg.get("url")
    )
    lines.append(
        f"📸 Snapshot: {_t(p['snapshot_at'], '%H:%M:%S')} · expires {_t(p['expires_at'], '%H:%M:%S')} · "
        f"rev. {p.get('revision', 1)}"
    )
    if links:
        lines.append(f"🔗 {links}")
    lines.append("<i>Place bets yourself. Verify the price and limit before placing a bet.</i>")
    return "\n".join(lines)


def render_rules(p: dict[str, Any]) -> str:
    lines = ["📜 <b>Settlement rules by leg</b>"]
    for leg in p["legs"]:
        r = leg["rules"]
        ot = {True: "yes", False: "no", None: "unknown"}[r.get("ot")]
        lines += [
            f"\n<b>{escape(leg['venue']['name'])}</b> — {escape(english_label(leg['selection']['label']))}"
            + (" <i>(assumed rules — verify)</i>" if r.get("assumed") else ""),
            f"• cancellation: {POLICY_EN.get(r['cancel'], r['cancel'])}",
            f"• postponement: {POLICY_EN.get(r['postpone'], r['postpone'])}",
            f"• draw (if no draw selection): {POLICY_EN.get(r['draw'], r['draw'])}",
            f"• overtime included: {ot}",
        ]
        if leg.get("rules_url"):
            lines.append(f'• <a href="{escape(leg["rules_url"])}">rules source</a>')
        lines.append(f"• rules version: <code>{escape(leg['rules_version'])}</code>")
    return "\n".join(lines)


def render_closed(p: dict[str, Any], reasons: list[str]) -> str:
    ev = p["event"]
    why = "; ".join(reason_en(r) for r in reasons) or "the opportunity is no longer profitable"
    return (
        f"❌ <b>Signal closed</b> · {escape(ev['title'])}\nReason: {escape(why)}\nLast revision: {p.get('revision', 1)}"
    )
