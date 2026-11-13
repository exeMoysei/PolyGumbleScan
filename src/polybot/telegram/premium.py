"""Premium subscription in Telegram (US12): /premium, payment in Telegram Stars, admin /grant and /revoke.

Payment flow (Telegram Stars, currency ``XTR``, no payment provider token):
/premium -> plan button -> invoice -> pre_checkout_query (validated here) -> successful_payment -> premium extended.
A payment is applied once per ``telegram_payment_charge_id``, so a re-delivered update never extends twice.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from polybot.domain import premium as rules
from polybot.services.premium import plans_from
from polybot.storage import premium as premium_repo
from polybot.storage.models import Subscription

if TYPE_CHECKING:  # the handlers receive the context from the dispatcher; no runtime import cycle with bot.py
    from polybot.telegram.bot import BotContext

log = logging.getLogger(__name__)
router = Router(name="polybot-premium")


class PremCb(CallbackData, prefix="p"):
    action: str  # buy
    plan: str


def premium_keyboard(plans: tuple[rules.PremiumPlan, ...]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⭐ {p.days} days — {p.stars} Stars", callback_data=PremCb(action="buy", plan=p.code).pack()
                )
            ]
            for p in plans
        ]
    )


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def status_text(sub: Subscription | None, ctx: BotContext, now: datetime) -> str:
    st = ctx.settings
    until = sub.premium_until if sub else None
    if rules.is_premium(until, now):
        assert until is not None
        head = f"⭐ <b>Premium is active</b> until {_fmt(until)} ({rules.remaining_days(until, now)} days left)."
    else:
        head = "Your plan: <b>Free</b>."
    return (
        f"{head}\n\n"
        "<b>Free</b>\n"
        f"• up to {st.free_daily_alerts} alerts per 24 hours\n"
        f"• /signals shows {st.free_signals_shown} card(s)\n"
        f"• budget up to {st.free_max_budget:.0f} {st.budget_currency}\n\n"
        "<b>Premium</b>\n"
        "• every alert, no daily limit\n"
        "• /signals shows all active cards\n"
        f"• budget up to {st.max_budget:.0f} {st.budget_currency}\n\n"
        "Buying again extends the current period. Payment in Telegram Stars."
    )


@router.message(Command("premium"))
async def cmd_premium(message: Message, ctx: BotContext) -> None:
    now = datetime.now(UTC)
    async with ctx.sessions() as s:
        sub = await s.get(Subscription, message.chat.id)
        stats = (
            await premium_repo.stats(s, now)
            if ctx.is_admin(message.from_user.id if message.from_user else None)
            else None
        )
    text = status_text(sub, ctx, now)
    if stats is not None:
        paid = ", ".join(f"{v['count']}× / {v['amount']} {cur}" for cur, v in stats["payments_30d"].items()) or "—"
        text += f"\n\n<b>Admin:</b> active premium: {stats['premium_active']}; payments in 30 days: {escape(paid)}"
    await message.answer(text, reply_markup=premium_keyboard(plans_from(ctx.settings)))


@router.callback_query(PremCb.filter(F.action == "buy"))
async def cb_buy(query: CallbackQuery, callback_data: PremCb, ctx: BotContext) -> None:
    msg = query.message
    if not isinstance(msg, Message):
        return
    plan = rules.find_plan(plans_from(ctx.settings), callback_data.plan)
    if plan is None:
        await query.answer("This plan is no longer available — open /premium again", show_alert=True)
        return
    await query.answer()
    await msg.answer_invoice(
        title=plan.title,
        description=f"{plan.days} days of PolyBot alerts without the free-plan limits.",
        payload=rules.invoice_payload(plan, msg.chat.id),
        currency=rules.STARS_CURRENCY,
        prices=[LabeledPrice(label=f"{plan.days} days", amount=plan.stars)],
    )


def check_checkout(
    payload: str, currency: str, amount: int, plans: tuple[rules.PremiumPlan, ...]
) -> tuple[rules.PremiumPlan, int] | str:
    """Validate an invoice before Telegram charges the user. Returns (plan, chat_id) or an error message."""
    parsed = rules.parse_invoice_payload(payload)
    if parsed is None:
        return "Unknown invoice."
    plan = rules.find_plan(plans, parsed[0])
    if plan is None:
        return "This plan is no longer available. Open /premium again."
    if currency != rules.STARS_CURRENCY or amount != plan.stars:
        return "The price has changed. Open /premium again."
    return plan, parsed[1]


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery, ctx: BotContext) -> None:
    result = check_checkout(query.invoice_payload, query.currency, query.total_amount, plans_from(ctx.settings))
    if isinstance(result, str):
        await query.answer(ok=False, error_message=result)
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message, ctx: BotContext) -> None:
    pay = message.successful_payment
    assert pay is not None
    result = check_checkout(pay.invoice_payload, pay.currency, pay.total_amount, plans_from(ctx.settings))
    if isinstance(result, str):
        # Telegram has already charged the user: never drop it silently, let an admin sort it out
        log.error("payment does not match a plan", extra={"charge_id": pay.telegram_payment_charge_id})
        await message.answer(
            "Payment received, but it could not be matched to a plan. "
            "An admin will check it — use /paysupport and keep this message."
        )
        return
    plan, _ = result  # credited to the chat where the payment happened
    user_id = message.from_user.id if message.from_user else message.chat.id
    async with ctx.sessions() as s, s.begin():
        res = await premium_repo.record_payment(
            s,
            chat_id=message.chat.id,
            user_id=user_id,
            charge_id=pay.telegram_payment_charge_id,
            plan=plan,
            amount=pay.total_amount,
            currency=pay.currency,
            now=datetime.now(UTC),
            budget_if_new=ctx.settings.default_budget,
        )
    if res.created:
        await message.answer(f"⭐ Thank you! Premium is active until {_fmt(res.premium_until)}.")


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, ctx: BotContext) -> None:
    contact = ctx.settings.support_contact
    where = f"Write to {escape(contact)}" if contact else "Contact the bot administrator"
    await message.answer(
        "<b>Payment support</b>\n"
        f"{where}, and include the date of the payment. "
        "Premium is a digital service; if alerts did not work because of us, we refund the Stars."
    )


# ---------------------------------------------------------------------------- admin
@router.message(Command("grant"))
async def cmd_grant(message: Message, command: CommandObject, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    parsed = rules.parse_grant_args(command.args)
    if parsed is None:
        await message.answer("Format: /grant &lt;chat_id&gt; &lt;days&gt;  (e.g. /grant 123456789 30)")
        return
    chat_id, days = parsed
    async with ctx.sessions() as s, s.begin():
        sub = await premium_repo.grant(s, chat_id, days, datetime.now(UTC), message.from_user.id)
        until = sub.premium_until if sub else None
    if until is None:
        await message.answer(f"Chat {chat_id} has no subscription (the user must press /start first).")
        return
    await message.answer(f"⭐ Premium for chat {chat_id} extended until {_fmt(until)}.")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    try:
        chat_id = int((command.args or "").strip())
    except ValueError:
        await message.answer("Format: /revoke &lt;chat_id&gt;")
        return
    async with ctx.sessions() as s, s.begin():
        sub = await premium_repo.revoke(s, chat_id, datetime.now(UTC), message.from_user.id)
    await message.answer(f"Premium removed for chat {chat_id}." if sub else f"Chat {chat_id} has no subscription.")
