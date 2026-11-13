"""Premium subscription rules (US12): plans, expiry arithmetic and free-plan limits.

Pure logic: standard library only (no SDK, ORM, Telegram or HTTP), UTC-aware datetimes, ``Decimal`` for money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

PAYLOAD_PREFIX = "premium"
STARS_CURRENCY = "XTR"  # Telegram Stars


@dataclass(frozen=True, slots=True)
class PremiumPlan:
    code: str  # short id used in callback data and invoice payload
    days: int
    stars: int  # price in Telegram Stars

    @property
    def title(self) -> str:
        return f"PolyBot Premium — {self.days} days"


@dataclass(frozen=True, slots=True)
class PlanLimits:
    """What a subscriber may receive. ``None`` means unlimited."""

    premium: bool
    daily_alerts: int | None
    signals_shown: int
    max_budget: Decimal | None


def _aware(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")


def is_premium(until: datetime | None, now: datetime) -> bool:
    _aware(now)
    return until is not None and until > now


def extend(until: datetime | None, days: int, now: datetime) -> datetime:
    """New expiry after buying ``days``: an active premium is extended, an expired one restarts from ``now``."""
    _aware(now)
    if days <= 0:
        raise ValueError("days must be positive")
    start = until if until is not None and until > now else now
    return start + timedelta(days=days)


def remaining_days(until: datetime | None, now: datetime) -> int:
    """Whole days left, rounded up (23 hours left -> 1 day); 0 when not premium."""
    if not is_premium(until, now):
        return 0
    assert until is not None
    left = until - now
    return left.days + (1 if left.seconds or left.microseconds else 0)


def limits_for(
    premium: bool,
    *,
    free_daily_alerts: int,
    free_signals_shown: int,
    free_max_budget: Decimal,
    max_signals_shown: int = 5,
) -> PlanLimits:
    if premium:
        return PlanLimits(True, None, max_signals_shown, None)
    return PlanLimits(False, free_daily_alerts, min(free_signals_shown, max_signals_shown), free_max_budget)


def alert_allowed(limits: PlanLimits, sent_last_24h: int) -> bool:
    return limits.daily_alerts is None or sent_last_24h < limits.daily_alerts


def budget_allowed(limits: PlanLimits, budget: Decimal) -> bool:
    return limits.max_budget is None or budget <= limits.max_budget


def find_plan(plans: tuple[PremiumPlan, ...], code: str) -> PremiumPlan | None:
    return next((p for p in plans if p.code == code), None)


def invoice_payload(plan: PremiumPlan, chat_id: int) -> str:
    return f"{PAYLOAD_PREFIX}:{plan.code}:{chat_id}"


def parse_invoice_payload(payload: str) -> tuple[str, int] | None:
    """``premium:<plan>:<chat_id>`` -> (plan code, chat id); ``None`` for anything else."""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX or not parts[1]:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


def parse_grant_args(raw: str | None, max_days: int = 3650) -> tuple[int, int] | None:
    """Admin ``/grant <chat_id> <days>`` arguments; ``None`` when invalid."""
    parts = (raw or "").split()
    if len(parts) != 2:
        return None
    try:
        chat_id, days = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not 1 <= days <= max_days:
        return None
    return chat_id, days
