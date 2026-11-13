"""US12: premium subscription — pure rules, settings glue and Telegram wiring (no database, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from polybot.domain import premium as rules
from polybot.services.premium import plan_limits, plans_from
from polybot.settings import Settings
from polybot.storage.models import Subscription
from polybot.storage.premium import over_daily_limit

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)


def _settings(**kw) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(odds_api_key=None, premium_enabled=True)
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def _sub(chat_id: int = 1, until: datetime | None = None) -> Subscription:
    return Subscription(chat_id=chat_id, user_id=chat_id, budget=Decimal(100), filters={}, premium_until=until)


# ---------------------------------------------------------------------------- expiry arithmetic
def test_is_premium_and_remaining_days() -> None:
    assert not rules.is_premium(None, NOW)
    assert not rules.is_premium(NOW, NOW)  # expires exactly now -> free
    assert rules.is_premium(NOW + timedelta(seconds=1), NOW)
    assert rules.remaining_days(None, NOW) == 0
    assert rules.remaining_days(NOW + timedelta(hours=23), NOW) == 1
    assert rules.remaining_days(NOW + timedelta(days=30), NOW) == 30
    assert rules.remaining_days(NOW + timedelta(days=29, hours=1), NOW) == 30


def test_extend_adds_to_active_and_restarts_expired() -> None:
    assert rules.extend(None, 30, NOW) == NOW + timedelta(days=30)
    active = NOW + timedelta(days=5)
    assert rules.extend(active, 30, NOW) == NOW + timedelta(days=35)  # buying early never loses days
    expired = NOW - timedelta(days=100)
    assert rules.extend(expired, 30, NOW) == NOW + timedelta(days=30)
    with pytest.raises(ValueError):
        rules.extend(None, 0, NOW)
    with pytest.raises(ValueError):
        rules.is_premium(None, datetime(2026, 1, 1))  # naive datetime is a bug, not a free user


# ---------------------------------------------------------------------------- limits
def test_free_and_premium_limits() -> None:
    free = rules.limits_for(False, free_daily_alerts=3, free_signals_shown=1, free_max_budget=Decimal(250))
    prem = rules.limits_for(True, free_daily_alerts=3, free_signals_shown=1, free_max_budget=Decimal(250))
    assert [rules.alert_allowed(free, n) for n in (0, 2, 3, 10)] == [True, True, False, False]
    assert rules.alert_allowed(prem, 10_000)
    assert rules.budget_allowed(free, Decimal(250)) and not rules.budget_allowed(free, Decimal(251))
    assert rules.budget_allowed(prem, Decimal(5000))
    assert (free.signals_shown, prem.signals_shown) == (1, 5)


def test_plan_limits_follow_settings_and_expiry() -> None:
    st = _settings(free_daily_alerts=2, free_max_budget=Decimal(150))
    assert plan_limits(st, None, NOW).daily_alerts == 2
    assert plan_limits(st, _sub(until=NOW - timedelta(minutes=1)), NOW).max_budget == Decimal(150)
    assert plan_limits(st, _sub(until=NOW + timedelta(days=1)), NOW).premium
    off = _settings(premium_enabled=False)
    assert plan_limits(off, None, NOW).premium  # feature switched off -> nobody is limited
    assert off.free_alert_limit() is None and st.free_alert_limit() == 2


def test_over_daily_limit_skips_premium_chats() -> None:
    subs = [_sub(1), _sub(2), _sub(3, until=NOW + timedelta(days=3)), _sub(4, until=NOW - timedelta(days=3))]
    sent = {1: 3, 2: 2, 3: 50, 4: 3}
    assert over_daily_limit(subs, sent, 3, NOW) == {1, 4}


# ---------------------------------------------------------------------------- plans and payments
def test_plans_from_settings_sorted_and_validated() -> None:
    st = _settings(premium_plans={"90": 600, "30": 250, "7": 0})
    plans = plans_from(st)
    assert [(p.code, p.days, p.stars) for p in plans] == [("30", 30, 250), ("90", 90, 600)]
    assert rules.find_plan(plans, "90") is plans[1] and rules.find_plan(plans, "7") is None


def test_invoice_payload_roundtrip_and_garbage() -> None:
    plan = rules.PremiumPlan("30", 30, 250)
    assert rules.parse_invoice_payload(rules.invoice_payload(plan, -100123)) == ("30", -100123)
    for bad in ("", "premium", "premium::1", "premium:30:x", "other:30:1", "premium:30:1:extra"):
        assert rules.parse_invoice_payload(bad) is None


def test_checkout_rejects_wrong_price_currency_and_plan() -> None:
    from polybot.telegram.premium import check_checkout

    plans = (rules.PremiumPlan("30", 30, 250),)
    ok = check_checkout("premium:30:42", "XTR", 250, plans)
    assert ok == (plans[0], 42)
    assert isinstance(check_checkout("premium:30:42", "XTR", 1, plans), str)  # price changed / tampered
    assert isinstance(check_checkout("premium:30:42", "USD", 250, plans), str)
    assert isinstance(check_checkout("premium:90:42", "XTR", 600, plans), str)  # plan removed
    assert isinstance(check_checkout("nonsense", "XTR", 250, plans), str)


def test_grant_args() -> None:
    assert rules.parse_grant_args("123456789 30") == (123456789, 30)
    assert rules.parse_grant_args("-100200 7") == (-100200, 7)
    for bad in (None, "", "123", "abc 30", "123 0", "123 -5", "123 99999", "1 2 3"):
        assert rules.parse_grant_args(bad) is None


def test_premium_keyboard_and_callback_fit_telegram_limits() -> None:
    from polybot.telegram.premium import PremCb, premium_keyboard

    plans = plans_from(_settings())
    kb = premium_keyboard(plans)
    assert len(kb.inline_keyboard) == len(plans) == 2
    for row in kb.inline_keyboard:
        assert row[0].callback_data and len(row[0].callback_data) <= 64
        assert PremCb.unpack(row[0].callback_data).action == "buy"


def test_status_text_shows_expiry_and_limits() -> None:
    from polybot.telegram.bot import BotContext
    from polybot.telegram.premium import status_text

    ctx = BotContext(_settings(free_daily_alerts=3), sessions=None)  # type: ignore[arg-type]
    free = status_text(None, ctx, NOW)
    assert "<b>Free</b>." in free and "up to 3 alerts" in free
    prem = status_text(_sub(until=NOW + timedelta(days=10)), ctx, NOW)
    assert "Premium is active" in prem and "2026-12-20" in prem and "10 days left" in prem


def test_premium_router_handlers() -> None:
    from polybot.telegram.premium import router

    assert len(router.message.handlers) >= 5  # /premium, payment, /paysupport, /grant, /revoke
    assert len(router.callback_query.handlers) == 1 and len(router.pre_checkout_query.handlers) == 1
