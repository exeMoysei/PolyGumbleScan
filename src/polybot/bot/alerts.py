"""Texts of the Polymarket-only alerts: new-wallet whales, followed wallets, YES-sum arbitrage, ranking."""

from __future__ import annotations

from decimal import Decimal
from html import escape

from polybot.logic.money import fmt_money
from polybot.logic.wallets import LeaderRow, WalletHistory, WalletTrade, short_wallet
from polybot.logic.yes_sum import YesSumPlan


def _profile(wallet: str) -> str:
    return f"https://polymarket.com/profile/{wallet}"


def _trade_lines(t: WalletTrade) -> list[str]:
    return [
        f"<b>{escape(t.title)}</b>",
        f"{t.side} <b>{escape(t.outcome)}</b>: {fmt_money(t.usdc, 'USDC')} ({t.size:,.0f} shares @ {t.price})",
        f'🔗 <a href="{escape(t.url)}">Market</a> · <a href="{_profile(t.wallet)}">Wallet</a> · {t.at:%d.%m %H:%M} UTC',
    ]


def render_whale(t: WalletTrade, history: WalletHistory) -> str:
    who = escape(t.name) if t.name and not t.name.lower().startswith("0x") else short_wallet(t.wallet)
    first = f"first trade {history.first_seen:%d.%m %H:%M} UTC" if history.first_seen else "no earlier trades"
    return "\n".join(
        [
            "🐋 <b>NEW WALLET, BIG BET</b>",
            f"Wallet <code>{short_wallet(t.wallet)}</code> ({who}): {history.trades_seen} trades so far, {first}",
            *_trade_lines(t),
            "<i>Information only — new wallets with big bets are sometimes informed, often not.</i>",
        ]
    )


def render_followed(t: WalletTrade, label: str | None) -> str:
    who = escape(label) if label else short_wallet(t.wallet)
    return "\n".join([f"👀 <b>FOLLOWED WALLET</b> · {who}", *_trade_lines(t)])


def render_yes_sum(plan: YesSumPlan, outcomes: int) -> str:
    return "\n".join(
        [
            "🧮 <b>POLYMARKET YES SUM &lt; 1</b>",
            f"<b>{escape(plan.event_title)}</b> — {outcomes} outcomes, exactly one pays 1 USDC per share",
            f"Best asks add up to {plan.top_sum:.3f}",
            f"Buy <b>{plan.shares:f}</b> YES shares of every outcome: cost {fmt_money(plan.cost, 'USDC')} "
            f"(fees {fmt_money(plan.fees)})",
            f"Payout {fmt_money(plan.payout, 'USDC')} · profit <b>+{fmt_money(plan.profit)}</b> "
            f"({plan.roi * 100:.2f}%)",
            f'🔗 <a href="{escape(plan.event_url)}">Event</a>',
            "<i>Check every outcome's price before buying: the edge disappears if one leg moves.</i>",
        ]
    )


def render_leaderboard(rows: list[LeaderRow], period: str, sort_by: str) -> str:
    if not rows:
        return "The leaderboard is empty right now."
    lines = [f"🏆 <b>Polymarket top traders</b> · {period} · by {'profit' if sort_by == 'PNL' else 'volume'}"]
    for r in rows:
        name = escape(r.name) if r.name and not r.name.lower().startswith("0x") else short_wallet(r.wallet)
        roi = f" · {r.roi * 100:.1f}% of volume" if r.roi is not None else ""
        lines.append(
            f'{r.rank}. <a href="{_profile(r.wallet)}">{name}</a> — PnL {_signed(r.pnl)} USDC, '
            f"volume {fmt_money(r.volume)}{roi}"
        )
    lines.append("Follow one: /follow 0x… (copy the address from the profile link)")
    return "\n".join(lines)


def _signed(v: Decimal) -> str:
    s = fmt_money(v)
    return s if v < 0 else f"+{s}"
