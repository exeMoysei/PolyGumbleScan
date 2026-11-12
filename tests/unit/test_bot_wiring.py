from polybot.settings import Settings
from polybot.telegram.bot import BotContext, build_bot, build_dispatcher, router
from polybot.telegram.keyboards import MapCb, OppCb, card_keyboard


def test_dispatcher_wiring_and_admin_check() -> None:
    ctx = BotContext(Settings(admin_ids=[1], odds_api_key=None), sessions=None)  # type: ignore[arg-type]
    dp = build_dispatcher(ctx)
    assert dp["ctx"] is ctx
    assert len(router.message.handlers) >= 10 and len(router.callback_query.handlers) >= 5
    assert ctx.is_admin(1) and not ctx.is_admin(2) and not ctx.is_admin(None)
    bot = build_bot("123456:" + "A" * 35)
    assert bot.id == 123456


def test_callback_data_fits_telegram_limit() -> None:
    assert len(OppCb(action="rc", opp_id=10**12, rev=999).pack()) <= 64
    assert len(MapCb(action="a", mapping_id=10**12, rv="abcdef123456").pack()) <= 64
    kb = card_keyboard(
        1,
        1,
        {
            "legs": [
                {"venue": {"name": "Polymarket"}, "url": "https://polymarket.com/x"},
                {"venue": {"name": "Book"}, "url": "https://example.invalid/b"},
            ]
        },
    )
    assert len(kb.inline_keyboard) == 2


def test_main_menu_and_min_profit_parsing() -> None:
    from decimal import Decimal

    from polybot.telegram.bot import parse_min_profit
    from polybot.telegram.keyboards import MenuCb, main_menu_keyboard

    kb = main_menu_keyboard()
    actions = [MenuCb.unpack(b.callback_data).action for row in kb.inline_keyboard for b in row if b.callback_data]
    assert actions == ["signals", "budget", "filters", "help"]
    assert parse_min_profit("2,5", Decimal(5000)) == Decimal("2.50")
    assert parse_min_profit("0", Decimal(5000)) == Decimal("0.00")
    for bad in (None, "", "abc", "-1", "NaN", "999999"):
        assert parse_min_profit(bad, Decimal(5000)) is None


def test_subscription_min_profit_filter() -> None:
    from decimal import Decimal

    from polybot.storage.models import Subscription
    from polybot.storage.repo import subscription_accepts

    payload = {
        "verdict": "signal",
        "route": "prediction_prediction",
        "event": {"league": "nba"},
        "roi": "0.01",
        "min_profit": "2.84",
    }
    sub = Subscription(chat_id=1, user_id=1, budget=Decimal(200), filters={"verdicts": ["signal"], "min_profit": "2.5"})
    assert subscription_accepts(sub, payload)
    sub.filters = {"verdicts": ["signal"], "min_profit": "3"}
    assert not subscription_accepts(sub, payload)
    sub.filters = {"verdicts": ["signal"], "min_profit": None}
    assert subscription_accepts(sub, payload)
