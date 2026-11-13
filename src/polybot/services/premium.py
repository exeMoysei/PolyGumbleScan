"""Premium (US12) glue between settings and the pure rules in ``polybot.domain.premium``."""

from __future__ import annotations

from datetime import datetime

from polybot.domain.premium import PlanLimits, PremiumPlan, is_premium, limits_for
from polybot.settings import Settings
from polybot.storage.models import Subscription


def plans_from(settings: Settings) -> tuple[PremiumPlan, ...]:
    """Plans for sale, shortest first. Settings: ``POLYBOT_PREMIUM_PLANS='{"30": 250, "90": 600}'`` (days -> Stars)."""
    plans = [
        PremiumPlan(code=str(int(days)), days=int(days), stars=int(stars))
        for days, stars in settings.premium_plans.items()
    ]
    return tuple(sorted((p for p in plans if p.days > 0 and p.stars > 0), key=lambda p: p.days))


def plan_limits(settings: Settings, sub: Subscription | None, now: datetime) -> PlanLimits:
    premium = not settings.premium_enabled or (sub is not None and is_premium(sub.premium_until, now))
    return limits_for(
        premium,
        free_daily_alerts=settings.free_daily_alerts,
        free_signals_shown=settings.free_signals_shown,
        free_max_budget=settings.free_max_budget,
    )
