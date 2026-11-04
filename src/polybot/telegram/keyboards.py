from __future__ import annotations

from typing import Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class OppCb(CallbackData, prefix="o"):
    action: str  # rc = recheck, rl = rules, hd = hide
    opp_id: int
    rev: int


class MapCb(CallbackData, prefix="m"):
    action: str  # a = approve, r = reject
    mapping_id: int
    rv: str  # rules version the admin is looking at


class FltCb(CallbackData, prefix="f"):
    field: str
    value: str


def card_keyboard(opp_id: int, rev: int, payload: dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🔄 Перепроверить", callback_data=OppCb(action="rc", opp_id=opp_id, rev=rev).pack()
            ),
            InlineKeyboardButton(text="📜 Правила", callback_data=OppCb(action="rl", opp_id=opp_id, rev=rev).pack()),
            InlineKeyboardButton(text="🙈 Скрыть", callback_data=OppCb(action="hd", opp_id=opp_id, rev=rev).pack()),
        ]
    ]
    links = [
        InlineKeyboardButton(text=f"↗ {leg['venue']['name']}", url=leg["url"])
        for leg in payload["legs"]
        if leg.get("url", "").startswith("https://")
    ]
    if links:
        rows.append(links[:3])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mapping_keyboard(mapping_id: int, rules_version: str) -> InlineKeyboardMarkup:
    rv = rules_version[:12]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=MapCb(action="a", mapping_id=mapping_id, rv=rv).pack()
                ),
                InlineKeyboardButton(
                    text="⛔ Отклонить", callback_data=MapCb(action="r", mapping_id=mapping_id, rv=rv).pack()
                ),
            ]
        ]
    )


def filters_keyboard(filters: dict[str, Any]) -> InlineKeyboardMarkup:
    verdicts = set(filters.get("verdicts") or ["signal"])
    routes = set(filters.get("routes") or [])

    def mark(on: bool) -> str:
        return "☑" if on else "☐"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{mark('signal' in verdicts)} Сигналы",
                    callback_data=FltCb(field="verdict", value="signal").pack(),
                ),
                InlineKeyboardButton(
                    text=f"{mark('candidate' in verdicts)} Кандидаты",
                    callback_data=FltCb(field="verdict", value="candidate").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{mark(not routes or 'prediction_prediction' in routes)} prediction↔prediction",
                    callback_data=FltCb(field="route", value="prediction_prediction").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{mark(not routes or 'prediction_sportsbook' in routes)} prediction↔sportsbook",
                    callback_data=FltCb(field="route", value="prediction_sportsbook").pack(),
                )
            ],
            [
                InlineKeyboardButton(text="ROI ≥ 0.5%", callback_data=FltCb(field="min_roi", value="0.005").pack()),
                InlineKeyboardButton(text="ROI ≥ 1%", callback_data=FltCb(field="min_roi", value="0.01").pack()),
                InlineKeyboardButton(text="ROI ≥ 2%", callback_data=FltCb(field="min_roi", value="0.02").pack()),
            ],
        ]
    )


def toggle_filter(filters: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    f = dict(filters or {})
    if field == "verdict":
        cur = set(f.get("verdicts") or ["signal"])
        cur ^= {value}
        f["verdicts"] = sorted(cur) or ["signal"]
    elif field == "route":
        all_routes = {"prediction_prediction", "prediction_sportsbook"}
        cur = set(f.get("routes") or all_routes)
        cur ^= {value}
        f["routes"] = sorted(cur) if cur and cur != all_routes else []
    elif field == "min_roi":
        f["min_roi"] = None if f.get("min_roi") == value else value
    return f
