"""Crypto prices on exchanges (backlog "price differences between cryptocurrencies": sprint 9, US26–US28,
issues #40–#42, owner: Artem Vozniak) — SKELETON, not wired into the app yet.

The project card plans ccxt (centralised exchanges) and Jupiter / 0x (DEX) plus CoinGecko as a reference price.
"""

from __future__ import annotations

from decimal import Decimal

from polybot.logic.crypto_arbitrage import Ticker


async def fetch_tickers(exchanges: list[str], symbols: list[str]) -> list[Ticker]:
    """Best bid/ask per exchange and symbol (ccxt ``fetch_order_book`` for CEX, quote APIs for DEX)."""
    raise NotImplementedError("crypto arbitrage, sprint 9")


async def withdrawal_fee(exchange: str, asset: str, network: str) -> Decimal | None:
    """Cost of moving ``asset`` out of ``exchange`` on ``network``; None when unknown."""
    raise NotImplementedError("crypto arbitrage, sprint 9")
