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
