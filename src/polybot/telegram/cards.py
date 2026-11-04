"""Pure rendering of opportunity cards (Telegram HTML)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any

from polybot.domain.money import fmt_money

REASONS_RU = {
    "limits_unknown": "лимиты площадки неизвестны",
    "aggregator_freshness": "свежесть цены подтверждена только агрегатором",
    "rules_assumed": "правила букмекера взяты по умолчанию — сверить",
    "exceptional_loss_possible": "возможен убыток при отмене/переносе",
    "exceptional_unknown": "исход при отмене/переносе не описан правилами",
    "no_longer_profitable": "вилка исчезла",
    "quote_missing": "котировка недоступна",
    "quote_stale": "котировка устарела",
    "quote_not_open": "рынок закрыт/приостановлен",
    "event_started": "событие началось",
    "negative_pnl": "отрицательный результат",
    "below_threshold": "прибыль ниже порога",
    "no_edge_top_of_book": "нет перевеса по лучшим ценам",
    "fx_stale": "курс валюты устарел",
    "fx_missing": "нет курса валюты",
    "solver_limit": "превышен лимит перебора",
}
POLICY_RU = {
    "win": "выигрыш",
    "lose": "проигрыш",
    "refund": "возврат ставки (комиссии не возвращаются)",
    "half": "расчёт 50/50",
    "no_wins": "расчёт «Нет»",
    "carry": "позиция ждёт переигровки",
    "unknown": "❓ не указано",
}
SPORT_ICON = {"nba": "🏀", "nfl": "🏈", "nhl": "🏒", "mlb": "⚾", "epl": "⚽"}
PERIOD_RU = {"full_game": "весь матч (вкл. овертайм)", "regulation": "основное время"}
MARKET_RU = {"moneyline": "Победитель", "match_result": "Исход 1X2", "total": "Тотал"}
ROUTE_RU = {
    "prediction_prediction": "prediction ↔ prediction",
    "prediction_sportsbook": "prediction ↔ sportsbook",
    "sportsbook_sportsbook": "sportsbook ↔ sportsbook",
}


def reason_ru(code: str) -> str:
    base = code.split(":")[0]
    return REASONS_RU.get(base, code)


def _signed(v: Decimal) -> str:
    s = fmt_money(v)
    return s if v < 0 else f"+{s}"


def _t(iso: str, fmt: str = "%d.%m %H:%M") -> str:
    return datetime.fromisoformat(iso).strftime(fmt) + " UTC"


def render_card(p: dict[str, Any], *, header: str | None = None) -> str:
    ccy = p["currency"]
    signal = p["verdict"] == "signal"
    title = header or ("✅ <b>СИГНАЛ</b>" if signal else "🟡 <b>КАНДИДАТ</b> (с риском)")
    ev = p["event"]
    lines = [
        f"{title} · {ROUTE_RU.get(p['route'], p['route'])}",
        f"{SPORT_ICON.get(ev['league'], '🎯')} <b>{escape(ev['league'].upper())}</b> · {escape(ev['title'])}",
        f"🕒 Старт: {_t(ev['start_at'])} · {MARKET_RU.get(p['market_type'], p['market_type'])}, "
        f"{PERIOD_RU.get(p['period'], p['period'])}",
        "",
        f"<b>Ставки</b> (бюджет {fmt_money(Decimal(p['budget']), ccy)}):",
    ]
    for i, leg in enumerate(p["legs"], start=1):
        size, avg, best = Decimal(leg["size"]), Decimal(leg["avg_price"]), Decimal(leg["best_price"])
        avail = leg.get("available")
        avail_s = f"доступно {Decimal(avail):,.0f}".replace(",", " ") if avail is not None else "лимит: unknown"
        lines.append(f"{i}) <b>{escape(leg['venue']['name'])}</b> — {escape(leg['selection']['label'])}")
        if leg["is_prediction"]:
            fee = Decimal(leg["fee"] or "0")
            fee_s = f", комиссия {fmt_money(fee)}" if fee else ""
            lines.append(
                f"   купить {size:f} конт. по ср. {avg:.4f} (лучшая {best}){fee_s} = "
                f"<b>{fmt_money(Decimal(leg['cost']), ccy)}</b> · {avail_s}"
            )
        else:
            lines.append(f"   ставка <b>{fmt_money(size, leg['currency'])}</b> @ {best} · {avail_s}")
        if leg.get("payout_win"):
            lines.append(f"   выплата при выигрыше: {fmt_money(Decimal(leg['payout_win']), ccy)}")
    lines += ["", "<b>Результат по сценариям:</b>"]
    regular = [x for x in p["pnl"] if x["kind"] == "regular"]
    exceptional = [x for x in p["pnl"] if x["kind"] == "exceptional"]
    for x in regular:
        lines.append(f"• {escape(x['label'])}: <b>{_signed(Decimal(x['value']))}</b>")
    if exceptional:
        lines.append("<i>Исключения:</i>")
        for x in exceptional:
            v = "❓ не определено" if x["value"] is None else _signed(Decimal(x["value"]))
            lines.append(f"• {escape(x['label'])}: {v}")
    lines += [
        "",
        f"💰 Мин. P&amp;L: <b>{_signed(Decimal(p['min_profit']))} {ccy}</b> · ROI "
        f"{Decimal(p['roi']) * 100:.2f}% · вложено {fmt_money(Decimal(p['total_cost']), ccy)}",
    ]
    if p.get("reasons"):
        lines.append("⚠️ " + "; ".join(reason_ru(r) for r in p["reasons"]))
    links = " · ".join(
        f'<a href="{escape(leg["url"])}">{escape(leg["venue"]["name"])}</a>' for leg in p["legs"] if leg.get("url")
    )
    lines.append(
        f"📸 Снимок: {_t(p['snapshot_at'], '%H:%M:%S')} · до {_t(p['expires_at'], '%H:%M:%S')} · "
        f"рев. {p.get('revision', 1)}"
    )
    if links:
        lines.append(f"🔗 {links}")
    lines.append("<i>Ставки размещаете вы сами. Проверьте цену и лимит перед входом.</i>")
    return "\n".join(lines)


def render_rules(p: dict[str, Any]) -> str:
    lines = ["📜 <b>Правила расчёта по ногам</b>"]
    for leg in p["legs"]:
        r = leg["rules"]
        ot = {True: "да", False: "нет", None: "не указано"}[r.get("ot")]
        lines += [
            f"\n<b>{escape(leg['venue']['name'])}</b> — {escape(leg['selection']['label'])}"
            + (" <i>(правила по умолчанию — сверить)</i>" if r.get("assumed") else ""),
            f"• отмена: {POLICY_RU.get(r['cancel'], r['cancel'])}",
            f"• перенос: {POLICY_RU.get(r['postpone'], r['postpone'])}",
            f"• ничья (если нет такого исхода): {POLICY_RU.get(r['draw'], r['draw'])}",
            f"• овертайм учитывается: {ot}",
        ]
        if leg.get("rules_url"):
            lines.append(f'• <a href="{escape(leg["rules_url"])}">источник правил</a>')
        lines.append(f"• версия правил: <code>{escape(leg['rules_version'])}</code>")
    return "\n".join(lines)


def render_closed(p: dict[str, Any], reasons: list[str]) -> str:
    ev = p["event"]
    why = "; ".join(reason_ru(r) for r in reasons) or "вилка исчезла"
    return (
        f"❌ <b>Сигнал закрыт</b> · {escape(ev['title'])}\nПричина: {escape(why)}\n"
        f"Последняя ревизия: {p.get('revision', 1)}"
    )
