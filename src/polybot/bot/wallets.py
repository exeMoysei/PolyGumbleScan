"""Wallet commands (US7, US9): /follow, /unfollow, /following and /top."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from polybot.bot.alerts import render_leaderboard
from polybot.data import repo, wallets_repo
from polybot.logic.wallets import LEADERBOARD_PERIODS, normalize_wallet, short_wallet

if TYPE_CHECKING:  # the context comes from the dispatcher
    from polybot.bot.handlers import BotContext

router = Router(name="polybot-wallets")

FOLLOW_HELP = (
    "Format: /follow 0xWALLET [min_usdc] [label]\n"
    "Example: /follow 0x0d6a1ada6d7ff785ab4b7263d9ce8e2baa85aa98 500 big fish\n"
    "Copy the address from a Polymarket profile link (polymarket.com/profile/0x…) or from /top."
)


def parse_follow(args: str | None, default_min: Decimal) -> tuple[str, Decimal, str | None] | None:
    parts = (args or "").split()
    if not parts:
        return None
    wallet = normalize_wallet(parts[0])
    if wallet is None:
        return None
    min_usdc, rest = default_min, parts[1:]
    if rest:
        try:
            min_usdc = Decimal(rest[0].replace(",", "."))
            rest = rest[1:]
        except InvalidOperation:
            pass
    if not min_usdc.is_finite() or min_usdc < 0:
        return None
    label = " ".join(rest)[:64] or None
    return wallet, min_usdc, label


@router.message(Command("follow"))
async def cmd_follow(message: Message, command: CommandObject, ctx: BotContext) -> None:
    assert message.from_user is not None
    parsed = parse_follow(command.args, ctx.settings.follow_default_min_usdc)
    if parsed is None:
        await message.answer(FOLLOW_HELP, disable_web_page_preview=True)
        return
    wallet, min_usdc, label = parsed
    async with ctx.sessions() as s, s.begin():
        await repo.ensure_subscription(s, message.chat.id, message.from_user.id, ctx.settings.default_budget)
        result = await wallets_repo.follow(
            s, message.chat.id, wallet, min_usdc, label, ctx.settings.max_followed_per_chat
        )
    if result == "limit":
        await message.answer(f"You already follow {ctx.settings.max_followed_per_chat} wallets. /unfollow one first.")
        return
    verb = "Now following" if result == "added" else "Updated"
    await message.answer(
        f"{verb} <code>{short_wallet(wallet)}</code>{' (' + escape(label) + ')' if label else ''}: "
        f"alerts for trades from {min_usdc} USDC. /following lists your wallets."
    )


@router.message(Command("unfollow"))
async def cmd_unfollow(message: Message, command: CommandObject, ctx: BotContext) -> None:
    wallet = normalize_wallet((command.args or "").split()[0] if command.args else "")
    if wallet is None:
        await message.answer("Format: /unfollow 0xWALLET")
        return
    async with ctx.sessions() as s, s.begin():
        removed = await wallets_repo.unfollow(s, message.chat.id, wallet)
    await message.answer("Removed." if removed else "You do not follow this wallet.")


@router.message(Command("following"))
async def cmd_following(message: Message, ctx: BotContext) -> None:
    async with ctx.sessions() as s:
        rows = await wallets_repo.followed_by_chat(s, message.chat.id)
    if not rows:
        await message.answer("You do not follow any wallet yet.\n" + FOLLOW_HELP, disable_web_page_preview=True)
        return
    lines = ["👀 <b>Followed wallets</b>"]
    for r in rows:
        name = f" — {escape(r.label)}" if r.label else ""
        lines.append(
            f'• <a href="https://polymarket.com/profile/{r.wallet}">{short_wallet(r.wallet)}</a>{name}, '
            f"from {Decimal(r.min_usdc):.0f} USDC"
        )
    await message.answer("\n".join(lines), disable_web_page_preview=True)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, ctx: BotContext) -> None:
    args = (command.args or "").lower().split()
    period = next((a for a in args if a in LEADERBOARD_PERIODS), "week")
    sort_by = "VOLUME" if "volume" in args else "PNL"
    from polybot.data.polymarket_users import PolymarketUsersClient

    client = PolymarketUsersClient()
    try:
        rows = await client.leaderboard(period, sort_by, "overall", 10)
    except Exception:
        await message.answer("Polymarket did not answer. Try again in a minute.")
        return
    finally:
        await client.aclose()
    await message.answer(render_leaderboard(rows, period, sort_by), disable_web_page_preview=True)
