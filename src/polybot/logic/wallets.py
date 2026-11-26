"""Wallet rules: large bets, "new wallet" detection (US6), followed wallets (US7) and the ranking (US9).

Pure functions over trades already fetched from the Polymarket Data API (``polybot.data.polymarket_users``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalize_wallet(raw: str) -> str | None:
    """``0x…`` address in lower case, or None when it is not a 40-hex-digit address."""
    value = raw.strip()
    return value.lower() if WALLET_RE.match(value) else None


def short_wallet(wallet: str) -> str:
    return f"{wallet[:6]}…{wallet[-4:]}"


@dataclass(frozen=True, slots=True)
class WalletTrade:
    wallet: str
    side: str  # BUY | SELL
    size: Decimal  # shares
    price: Decimal  # USDC per share
    at: datetime  # UTC
    title: str
    outcome: str
    market_slug: str
    event_slug: str
    tx_hash: str
    token_id: str
    name: str = ""  # profile name or pseudonym

    @property
    def usdc(self) -> Decimal:
        return self.size * self.price

    @property
    def key(self) -> str:
        """Unique per fill: one transaction can contain fills on several outcomes."""
        return f"{self.tx_hash}:{self.token_id}:{self.side}"

    @property
    def url(self) -> str:
        slug = self.event_slug or self.market_slug
        return f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"


@dataclass(frozen=True, slots=True)
class WalletHistory:
    """What we know about a wallet's past activity (newest first, at most ``limit`` items fetched)."""

    wallet: str
    trades_seen: int
    first_seen: datetime | None
    complete: bool  # True when the API returned fewer items than asked, i.e. this is the whole history


@dataclass(frozen=True, slots=True)
class NewWalletRule:
    min_usdc: Decimal = Decimal("5000")
    max_prior_trades: int = 10
    max_age: timedelta = timedelta(days=7)


def is_new_wallet(history: WalletHistory, now: datetime, rule: NewWalletRule) -> bool:
    """A wallet is "new" when its whole history is short and recent. Unknown (incomplete) history is not new."""
    if not history.complete or history.trades_seen > rule.max_prior_trades:
        return False
    return history.first_seen is None or now - history.first_seen <= rule.max_age


def big_trades(trades: list[WalletTrade], min_usdc: Decimal) -> list[WalletTrade]:
    return [t for t in trades if t.side == "BUY" and t.usdc >= min_usdc]


@dataclass(frozen=True, slots=True)
class LeaderRow:
    rank: int
    wallet: str
    name: str
    pnl: Decimal
    volume: Decimal

    @property
    def roi(self) -> Decimal | None:
        """Profit relative to traded volume (the leaderboard API does not publish a hit rate)."""
        return self.pnl / self.volume if self.volume > 0 else None


LEADERBOARD_PERIODS = ("day", "week", "month", "all")
