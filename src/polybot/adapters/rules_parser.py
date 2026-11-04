"""Keyword-based extraction of settlement rules from venue rule texts.

Anything not recognised stays UNKNOWN; such markets go to the admin review queue.
"""

from __future__ import annotations

import re

from polybot.domain.enums import Period, SettlementPolicy
from polybot.domain.models import RuleSet

_OT_YES = re.compile(
    r"includ\w*\s+(any\s+)?(overtime|extra\s+innings|ot\b|shoot-?outs?)|"
    r"(overtime|extra innings)\s+(periods?\s+)?(are|is|will be)\s+(included|counted)|"
    r"including\s+(any\s+)?(overtime|extra)|after\s+overtime|inclusive of overtime",
    re.IGNORECASE,
)
_OT_NO = re.compile(
    r"(regulation|regular)\s+time\s+only|excluding\s+(any\s+)?(overtime|extra time)|"
    r"(overtime|extra time)\s+(is|are|does|do|will)\s+not\s+(count|be counted|included|be included)|"
    r"\b90\s+minutes\b|(stoppage|injury)\s+time|at the end of regulation|"
    r"does not include (overtime|extra time)",
    re.IGNORECASE,
)
_CANCEL_HALF = re.compile(r"(cancel+ed|abandoned|not played)[^.]*?(50-50|50/50|fifty)", re.IGNORECASE)
_CANCEL_NO = re.compile(r"(cancel+ed|abandoned|not played)[^.]*?resolve[sd]?\s+(to\s+)?[\"“]?no\b", re.IGNORECASE)
_CANCEL_VOID = re.compile(
    r"(cancel+ed|abandoned)[^.]*?(void|refund|returned)|"
    r"(void|refund)[^.]*?(cancel+ed|abandoned)",
    re.IGNORECASE,
)
_POSTPONE_CARRY = re.compile(
    r"postponed[^.]*?(remain open|stay open|until the game (has been|is) (completed|played))", re.IGNORECASE
)
_POSTPONE_HALF = re.compile(r"postponed[^.]*?(50-50|50/50)", re.IGNORECASE)
_POSTPONE_VOID = re.compile(r"postponed[^.]*?(void|refund)|(void|refund)[^.]*?postponed", re.IGNORECASE)
_POSTPONE_NO = re.compile(r"postponed[^.]*?resolve[sd]?\s+(to\s+)?[\"“]?no\b", re.IGNORECASE)
_TIE_HALF = re.compile(r"(tie|draw)[^.]*?(50-50|50/50)", re.IGNORECASE)
_TIE_NO = re.compile(r"(tie|draw)[^.]*?resolve[sd]?\s+(to\s+)?[\"“]?no\b", re.IGNORECASE)
_CUTOFF = re.compile(r"(\d+)\s*(hours|hrs|days)", re.IGNORECASE)
_SOURCE = re.compile(r"(official\s+(statistics|results?|scores?)\s+(of|from|provided by)\s+[^.]+)", re.IGNORECASE)


def parse_rules(
    provider: str, text: str, *, default_period: Period = Period.UNKNOWN, url: str | None = None
) -> RuleSet:
    period = default_period
    includes_ot: bool | None = None
    if _OT_NO.search(text):
        includes_ot = False
        period = Period.REGULATION
    elif _OT_YES.search(text):
        includes_ot = True
        period = Period.FULL_GAME

    on_cancel = SettlementPolicy.UNKNOWN
    if _CANCEL_HALF.search(text):
        on_cancel = SettlementPolicy.HALF
    elif _CANCEL_NO.search(text):
        on_cancel = SettlementPolicy.NO_WINS
    elif _CANCEL_VOID.search(text):
        on_cancel = SettlementPolicy.REFUND

    on_postpone = SettlementPolicy.UNKNOWN
    if _POSTPONE_CARRY.search(text):
        on_postpone = SettlementPolicy.CARRY
    elif _POSTPONE_HALF.search(text):
        on_postpone = SettlementPolicy.HALF
    elif _POSTPONE_NO.search(text):
        on_postpone = SettlementPolicy.NO_WINS
    elif _POSTPONE_VOID.search(text):
        on_postpone = SettlementPolicy.REFUND

    on_draw = SettlementPolicy.UNKNOWN
    if _TIE_HALF.search(text):
        on_draw = SettlementPolicy.HALF
    elif _TIE_NO.search(text):
        on_draw = SettlementPolicy.NO_WINS

    cutoff = None
    m = re.search(r"postponed[^.]*", text, re.IGNORECASE)
    if m:
        c = _CUTOFF.search(m.group(0))
        if c:
            n = int(c.group(1))
            cutoff = n * 24 if c.group(2).lower().startswith("day") else n
    src = _SOURCE.search(text)
    return RuleSet(
        provider=provider,
        period=period,
        on_cancel=on_cancel,
        on_postpone=on_postpone,
        on_draw=on_draw,
        postpone_cutoff_hours=cutoff,
        includes_overtime=includes_ot,
        result_source=src.group(1).strip() if src else None,
        url=url,
        text=text,
    )


def sportsbook_default_rules(provider: str, sport: str, period: Period, url: str | None = None) -> RuleSet:
    """Documented industry-default sportsbook rules. Marked ``assumed`` -> always admin-reviewed."""
    on_draw = SettlementPolicy.REFUND if sport == "american_football" else SettlementPolicy.UNKNOWN
    text = (
        f"ASSUMED DEFAULT sportsbook rules ({sport}, {period.value}): moneyline includes overtime unless "
        "stated; void (stake refunded) when the event is cancelled or not played within the book's "
        "cut-off; ties in 2-way markets are a push. Verify against the bookmaker's house rules."
    )
    return RuleSet(
        provider=provider,
        period=period,
        on_cancel=SettlementPolicy.REFUND,
        on_postpone=SettlementPolicy.REFUND,
        on_draw=on_draw,
        postpone_cutoff_hours=24,
        includes_overtime=(period == Period.FULL_GAME),
        result_source="bookmaker house rules",
        url=url,
        text=text,
        assumed=True,
    )
