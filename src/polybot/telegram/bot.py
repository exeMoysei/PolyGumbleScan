"""aiogram 3 bot: user commands, card actions and admin review (long polling, one process per token)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import BotCommand, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polybot import metrics
from polybot.adapters.base import Adapter
from polybot.domain.enums import MappingStatus
from polybot.services.pipeline import fx_table_from, scan_config_from
from polybot.services.recheck import fetch_fresh, recheck_with
from polybot.settings import Settings
from polybot.storage import repo
from polybot.storage.models import MarketMapping, Opportunity, Subscription
from polybot.telegram.cards import reason_text, render_card, render_closed, render_rules
from polybot.telegram.keyboards import (
    FltCb,
    MapCb,
    MenuCb,
    OppCb,
    card_keyboard,
    filters_keyboard,
    main_menu_keyboard,
    mapping_keyboard,
    toggle_filter,
)

log = logging.getLogger(__name__)
router = Router(name="polybot")

HELP = (
    "<b>PolyBot</b> looks for combinations of bets on one event across prediction markets and bookmakers "
    "where the payout covers the outlay in every regular outcome.\n\n"
    "/signals — active signals for your budget\n"
    "/budget 250 — set the budget for one combination\n"
    "/filters — what to send (signals/candidates, routes, ROI)\n"
    "/minprofit 2.5 — minimum profit for notifications (0 clears it)\n"
    "/stop — pause notifications\n"
    "/help — help\n\n"
    "✅ <b>Signal</b> — verified rules, known limits, no loss in the described exceptions.\n"
    "🟡 <b>Candidate</b> — carries risk (unknown limit, price only from an aggregator, loss on cancellation).\n"
    "You place the bets yourself; the bot holds no funds and does not trade."
)
ADMIN_HELP = (
    "\n\n<b>Admin:</b> /pending — mapping review queue, /pause, /resume — publishing, /stats, "
    "/alias &lt;league&gt; &lt;alias&gt; &lt;team_id&gt;"
)


@dataclass
class BotContext:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    adapters: list[Adapter] = field(default_factory=list)

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.settings.admin_ids


def _owner_ok(sub: Subscription | None, user_id: int) -> bool:
    return sub is not None and sub.user_id == user_id


# ---------------------------------------------------------------------------- user commands
@router.message(Command("start"))
async def cmd_start(message: Message, ctx: BotContext) -> None:
    assert message.from_user is not None
    async with ctx.sessions() as s, s.begin():
        sub = await repo.ensure_subscription(s, message.chat.id, message.from_user.id, ctx.settings.default_budget)
        budget = sub.budget
    text = HELP + (ADMIN_HELP if ctx.is_admin(message.from_user.id) else "")
    await message.answer(
        f"Subscription active. Budget: {Decimal(budget):.2f} {ctx.settings.budget_currency}.\n\n{text}",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("Menu:", reply_markup=main_menu_keyboard())


@router.callback_query(MenuCb.filter())
async def cb_menu(query: CallbackQuery, callback_data: MenuCb, ctx: BotContext) -> None:
    msg = query.message
    if not isinstance(msg, Message):
        return
    await query.answer()
    if callback_data.action == "signals":
        await _send_signals(msg, ctx)
    elif callback_data.action == "filters":
        await _send_filters(msg, query.from_user.id, ctx)
    elif callback_data.action == "budget":
        async with ctx.sessions() as s:
            sub = await s.get(Subscription, msg.chat.id)
        budget = Decimal(sub.budget) if sub else ctx.settings.default_budget
        await msg.answer(f"Current budget: {budget:.2f} {ctx.settings.budget_currency}. Change it: /budget 250")
    else:
        await msg.answer(HELP + (ADMIN_HELP if ctx.is_admin(query.from_user.id) else ""))


@router.message(Command("help"))
async def cmd_help(message: Message, ctx: BotContext) -> None:
    uid = message.from_user.id if message.from_user else None
    await message.answer(HELP + (ADMIN_HELP if ctx.is_admin(uid) else ""))


@router.message(Command("stop"))
async def cmd_stop(message: Message, ctx: BotContext) -> None:
    async with ctx.sessions() as s, s.begin():
        sub = await s.get(Subscription, message.chat.id)
        if sub:
            sub.active = False
    await message.answer("Notifications paused. /start turns them back on.")


@router.message(Command("budget"))
async def cmd_budget(message: Message, command: CommandObject, ctx: BotContext) -> None:
    assert message.from_user is not None
    async with ctx.sessions() as s, s.begin():
        sub = await repo.ensure_subscription(s, message.chat.id, message.from_user.id, ctx.settings.default_budget)
        if not command.args:
            await message.answer(
                f"Current budget: {Decimal(sub.budget):.2f} {ctx.settings.budget_currency}. Change it: /budget 250"
            )
            return
        try:
            value = Decimal(command.args.strip().replace(",", "."))
        except InvalidOperation:
            await message.answer("Could not read the amount. Example: /budget 250")
            return
        if not (Decimal(10) <= value <= ctx.settings.max_budget):
            await message.answer(f"The budget must be between 10 and {ctx.settings.max_budget}.")
            return
        sub.budget = value.quantize(Decimal(1))
    await message.answer(
        f"Budget set: {value.quantize(Decimal(1))} {ctx.settings.budget_currency}. "
        "Signals sized for it appear on the next scanner cycle."
    )


def _filters_text(filters: dict[str, Any], currency: str) -> str:
    mp = filters.get("min_profit")
    line = f"min profit {mp} {currency}" if mp else "no min profit set (/minprofit 2.5)"
    return f"What to send ({line}):"


async def _send_filters(message: Message, user_id: int, ctx: BotContext) -> None:
    async with ctx.sessions() as s, s.begin():
        sub = await repo.ensure_subscription(s, message.chat.id, user_id, ctx.settings.default_budget)
        filters = dict(sub.filters or {})
    await message.answer(_filters_text(filters, ctx.settings.budget_currency), reply_markup=filters_keyboard(filters))


@router.message(Command("filters"))
async def cmd_filters(message: Message, ctx: BotContext) -> None:
    assert message.from_user is not None
    await _send_filters(message, message.from_user.id, ctx)


def parse_min_profit(raw: str | None, maximum: Decimal) -> Decimal | None:
    """Parse the /minprofit argument; ``None`` means the value is not acceptable."""
    try:
        value = Decimal((raw or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > maximum:
        return None
    return value.quantize(Decimal("0.01"))


@router.message(Command("minprofit"))
async def cmd_minprofit(message: Message, command: CommandObject, ctx: BotContext) -> None:
    assert message.from_user is not None
    value = parse_min_profit(command.args, ctx.settings.max_budget)
    if value is None:
        await message.answer("Format: /minprofit 2.5 (in the budget currency). /minprofit 0 removes the threshold.")
        return
    async with ctx.sessions() as s, s.begin():
        sub = await repo.ensure_subscription(s, message.chat.id, message.from_user.id, ctx.settings.default_budget)
        filters = dict(sub.filters or {})
        filters["min_profit"] = str(value) if value > 0 else None
        sub.filters = filters
    if value > 0:
        await message.answer(
            f"Only signals with a minimum profit of {value} {ctx.settings.budget_currency} or more will be sent."
        )
    else:
        await message.answer("Profit threshold removed.")


@router.callback_query(FltCb.filter())
async def cb_filter(query: CallbackQuery, callback_data: FltCb, ctx: BotContext) -> None:
    msg = query.message
    if not isinstance(msg, Message):
        return
    async with ctx.sessions() as s, s.begin():
        sub = await s.get(Subscription, msg.chat.id)
        if not _owner_ok(sub, query.from_user.id):
            await query.answer("This is not your subscription", show_alert=True)
            return
        assert sub is not None
        sub.filters = toggle_filter(sub.filters or {}, callback_data.field, callback_data.value)
        filters = dict(sub.filters)
    await msg.edit_reply_markup(reply_markup=filters_keyboard(filters))
    await query.answer("Saved")


async def _send_signals(message: Message, ctx: BotContext) -> None:
    async with ctx.sessions() as s:
        sub = await s.get(Subscription, message.chat.id)
        budget = Decimal(sub.budget) if sub else ctx.settings.default_budget
        opps = await repo.active_opportunities(s, budget, limit=5, now=datetime.now(UTC))
        if sub:
            opps = [o for o in opps if repo.subscription_accepts(sub, o.payload)]
    if not opps:
        await message.answer(
            f"No active signals for a budget of {budget:.0f} right now. "
            "The scanner is running — new ones arrive automatically."
        )
        return
    for o in opps:
        await message.answer(
            render_card(o.payload),
            reply_markup=card_keyboard(o.id, o.revision, o.payload),
            disable_web_page_preview=True,
        )


@router.message(Command("signals"))
async def cmd_signals(message: Message, ctx: BotContext) -> None:
    await _send_signals(message, ctx)


# ---------------------------------------------------------------------------- card actions
async def _load_card(s: AsyncSession, query: CallbackQuery, data: OppCb) -> Opportunity | None:
    msg = query.message
    if not isinstance(msg, Message):
        return None
    sub = await s.get(Subscription, msg.chat.id)
    if not _owner_ok(sub, query.from_user.id) and query.from_user.id != msg.chat.id:
        await query.answer("This card belongs to another user", show_alert=True)
        return None
    opp = await s.get(Opportunity, data.opp_id)
    if opp is None or opp.revision != data.rev:
        await query.answer("This card is outdated", show_alert=True)
        return None
    return opp


@router.callback_query(OppCb.filter(F.action == "rl"))
async def cb_rules(query: CallbackQuery, callback_data: OppCb, ctx: BotContext) -> None:
    async with ctx.sessions() as s:
        opp = await _load_card(s, query, callback_data)
    if opp is None:
        return
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.answer(render_rules(opp.payload), disable_web_page_preview=True)


@router.callback_query(OppCb.filter(F.action == "hd"))
async def cb_hide(query: CallbackQuery, callback_data: OppCb, ctx: BotContext) -> None:
    async with ctx.sessions() as s, s.begin():
        opp = await _load_card(s, query, callback_data)
        if opp is None:
            return
        assert isinstance(query.message, Message)
        await repo.hide(s, query.message.chat.id, opp.fingerprint)
    await query.answer("Hidden: no more updates for this combination")
    if isinstance(query.message, Message):
        await query.message.delete()


@router.callback_query(OppCb.filter(F.action == "rc"))
async def cb_recheck(query: CallbackQuery, callback_data: OppCb, ctx: BotContext) -> None:
    async with ctx.sessions() as s:
        opp = await _load_card(s, query, callback_data)
        if opp is None:
            return
        latest = await repo.latest_revision(s, opp.fingerprint)
        if latest is not None and latest.revision != opp.revision:
            await query.answer("A newer revision exists — showing it")
            if isinstance(query.message, Message):
                await query.message.answer(
                    render_card(latest.payload), reply_markup=card_keyboard(latest.id, latest.revision, latest.payload)
                )
            return
        subs = await repo.active_subscriptions(s)
    await query.answer("Rechecking…")
    now = datetime.now(UTC)
    payload: dict[str, Any] = opp.payload
    try:
        quotes = await fetch_fresh(payload, ctx.adapters)
    except Exception:
        log.exception("recheck fetch failed")
        quotes = []
    cfg = scan_config_from(ctx.settings, Decimal(payload["budget"]))
    result = recheck_with(payload, quotes, cfg, fx_table_from(ctx.settings, now), now)
    msg = query.message
    if not isinstance(msg, Message):
        return
    if result.draft is None:
        async with ctx.sessions() as s, s.begin():
            row = await s.get(Opportunity, opp.id, with_for_update=True)
            if row and row.status == "active":
                row.status, row.closed_reason, row.closed_at = "closed", f"recheck:{result.reasons[0]}", now
        metrics.RECHECKS.labels("closed").inc()
        await msg.edit_text(render_closed(payload, list(result.reasons)))
        return
    async with ctx.sessions() as s, s.begin():
        # the user who asked gets the card directly; others are notified only on material change
        pub = await repo.publish_draft(s, result.draft, [x for x in subs if x.chat_id != msg.chat.id], now)
        fresh = await s.get(Opportunity, pub.opportunity_id)
    assert fresh is not None
    metrics.RECHECKS.labels("updated" if pub.material else "unchanged").inc()
    header = None if not pub.material else f"🔄 <b>Rechecked</b> (rev. {fresh.revision})"
    await msg.edit_text(
        render_card(fresh.payload, header=header) if header else render_card(fresh.payload),
        reply_markup=card_keyboard(fresh.id, fresh.revision, fresh.payload),
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------- admin
def _mapping_text(m: MarketMapping, market_title: str, provider: str) -> str:
    doc = m.proposal
    outs = "\n".join(
        f"   • {escape(o['label'])} → <code>{escape(o['selection']['key'])}</code>" for o in doc.get("outcomes", [])
    )
    rules = doc.get("market", {}).get("rules", {})
    reasons = (
        ", ".join(
            reason_text(r) if not r.startswith(("rules_", "event_", "start_", "fuzzy", "role")) else r
            for r in (m.reasons or [])
        )
        or "—"
    )
    return (
        f"🧩 <b>Mapping #{m.id}</b> · {m.status}\n"
        f"Event: <code>{escape(m.canonical_event_id)}</code>\n"
        f"Key: <code>{escape(m.canonical_market_key)}</code>\n"
        f"Venue: <b>{escape(provider)}</b> — {escape(market_title)}\n"
        f"Outcomes:\n{outs}\n"
        f"Rules: cancel={rules.get('on_cancel')}, postpone={rules.get('on_postpone')}, "
        f"tie={rules.get('on_draw')}, OT={rules.get('ot')}{' (assumed defaults)' if rules.get('assumed') else ''}\n"
        f"Notes: {escape(reasons)}\n"
        f"Rules version: <code>{escape(m.rules_version)}</code>"
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message, ctx: BotContext) -> None:
    if not ctx.is_admin(message.from_user.id if message.from_user else None):
        return
    async with ctx.sessions() as s:
        rows = await repo.pending_mappings(s, limit=8)
    if not rows:
        await message.answer("The review queue is empty ✅")
        return
    for m, mrow in rows:
        await message.answer(
            _mapping_text(m, mrow.title or mrow.external_id, mrow.provider),
            reply_markup=mapping_keyboard(m.id, m.rules_version),
        )


@router.callback_query(MapCb.filter())
async def cb_mapping(query: CallbackQuery, callback_data: MapCb, ctx: BotContext) -> None:
    if not ctx.is_admin(query.from_user.id):
        await query.answer("Admins only", show_alert=True)
        return
    now = datetime.now(UTC)
    async with ctx.sessions() as s, s.begin():
        current = await s.get(MarketMapping, callback_data.mapping_id)
        if current is None or not current.rules_version.startswith(callback_data.rv):
            await query.answer("The rules have changed — open /pending again", show_alert=True)
            return
        row = await repo.decide_mapping(
            s, callback_data.mapping_id, callback_data.action == "a", query.from_user.id, "telegram", now
        )
        status = row.status if row else "?"
        if row is not None and status == MappingStatus.REJECTED.value:
            await repo.invalidate_by_markets(s, {row.canonical_market_key}, now)
    await query.answer(f"Status: {status}")
    if isinstance(query.message, Message):
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.answer(f"Mapping #{callback_data.mapping_id}: <b>{status}</b> (admin {query.from_user.id})")


@router.message(Command("pause"))
async def cmd_pause(message: Message, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    async with ctx.sessions() as s, s.begin():
        await repo.set_flag(s, repo.PUBLISHING_PAUSED, "1", message.from_user.id)
    await message.answer("⏸ Signal publishing is paused. The scanner keeps calculating. /resume turns it back on.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    async with ctx.sessions() as s, s.begin():
        await repo.set_flag(s, repo.PUBLISHING_PAUSED, "0", message.from_user.id)
    await message.answer("▶️ Publishing is on.")


@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    async with ctx.sessions() as s:
        st = await repo.stats(s, datetime.now(UTC) - timedelta(hours=24))
    lines = [
        "📊 <b>Statistics</b>",
        f"Users: {st['users_total']} (active subscriptions: {st['users_active']})",
        f"Alerts sent: {st['alerts_sent_total']} total, {st['alerts_sent_recent']} in the last 24 hours",
        "<b>Last 24 hours</b>",
        f"Shared events (2+ venues): {st['shared_events']}",
        f"Mappings: {st['mappings']}",
        f"Signals/candidates: {st['opportunities']}",
        f"Notifications: {st['outbox']}",
        "Rejections (top):",
    ]
    lines += [f"• {reason_text(k)}: {v}" for k, v in st["rejections"].items()]
    await message.answer(escape("\n".join(lines)).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"))


@router.message(Command("alias"))
async def cmd_alias(message: Message, command: CommandObject, ctx: BotContext) -> None:
    if not message.from_user or not ctx.is_admin(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) < 3:
        await message.answer('Format: /alias nba "LA Lakers" nba:lal  (the alias may contain several words)')
        return
    league, team_id, alias = parts[0], parts[-1], " ".join(parts[1:-1]).strip("\"'")
    async with ctx.sessions() as s, s.begin():
        await repo.add_team_alias(s, league, alias, team_id, message.from_user.id)
    await message.answer(f"Alias added: {escape(alias)} → {escape(team_id)}. It applies on the next discovery.")


# ---------------------------------------------------------------------------- wiring
COMMANDS = [
    BotCommand(command="signals", description="Active signals"),
    BotCommand(command="budget", description="Budget per combination"),
    BotCommand(command="filters", description="Filters"),
    BotCommand(command="minprofit", description="Minimum profit"),
    BotCommand(command="menu", description="Menu"),
    BotCommand(command="help", description="Help"),
]


def build_bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher(ctx: BotContext) -> Dispatcher:
    dp = Dispatcher()
    dp["ctx"] = ctx
    dp.include_router(router)
    return dp
