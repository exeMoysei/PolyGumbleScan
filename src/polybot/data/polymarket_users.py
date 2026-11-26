"""Polymarket Data API v2: trades, wallet activity and the leaderboard (public, no key).

The v1 endpoints and ``lb-api.polymarket.com`` were retired (HTTP 410). Parameters below were checked against the
live v2 API in Nov 2026: ``/v2/trades`` (``limit`` ≤ 1000, ``user``, ``filter_type=CASH`` + ``filter_amount``),
``/v2/activity?user=`` and ``/v2/leaderboard`` (``time_period`` day|week|month|all, ``sort_by`` PNL|VOLUME,
``category``). Responses are ``{"data": [...], "pagination": {...}}``, newest first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from polybot.data.http import HttpClient
from polybot.logic.money import dec
from polybot.logic.wallets import LeaderRow, WalletHistory, WalletTrade

BASE_URL = "https://data-api.polymarket.com/v2"


def parse_trade(row: dict[str, Any]) -> WalletTrade:
    return WalletTrade(
        wallet=str(row.get("proxy_wallet") or "").lower(),
        side=str(row.get("side") or "").upper(),
        size=dec(row.get("size") or 0),
        price=dec(row.get("price") or 0),
        at=datetime.fromtimestamp(int(row.get("timestamp") or 0), tz=UTC),
        title=str(row.get("title") or ""),
        outcome=str(row.get("outcome") or ""),
        market_slug=str(row.get("slug") or ""),
        event_slug=str(row.get("event_slug") or ""),
        tx_hash=str(row.get("transaction_hash") or ""),
        token_id=str(row.get("token_id") or ""),
        name=str(row.get("name") or row.get("pseudonym") or ""),
    )


def parse_history(wallet: str, rows: list[dict[str, Any]], limit: int) -> WalletHistory:
    trades = [r for r in rows if str(r.get("type") or "TRADE").upper() == "TRADE"]
    stamps = [int(r.get("timestamp") or 0) for r in rows if r.get("timestamp")]
    first = datetime.fromtimestamp(min(stamps), tz=UTC) if stamps else None
    return WalletHistory(wallet, len(trades), first, complete=len(rows) < limit)


def parse_leader(row: dict[str, Any]) -> LeaderRow:
    return LeaderRow(
        rank=int(row.get("rank") or 0),
        wallet=str(row.get("user_id") or "").lower(),
        name=str(row.get("user_name") or ""),
        pnl=dec(row.get("pnl") or 0),
        volume=dec(row.get("volume") or 0),
    )


class PolymarketUsersClient:
    def __init__(self, base_url: str = BASE_URL, http: HttpClient | None = None) -> None:
        self.http = http or HttpClient(base_url, concurrency=3)

    async def _data(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        payload = await self.http.get_json(path, params=params)
        rows = payload.get("data") if isinstance(payload, dict) else payload
        return [r for r in rows or [] if isinstance(r, dict)]

    async def big_trades(self, min_usdc: Decimal, limit: int = 200) -> list[WalletTrade]:
        """Latest trades worth at least ``min_usdc``, newest first."""
        rows = await self._data(
            "/trades", {"limit": min(limit, 1000), "filter_type": "CASH", "filter_amount": str(min_usdc)}
        )
        return [parse_trade(r) for r in rows]

    async def wallet_trades(self, wallet: str, limit: int = 50) -> list[WalletTrade]:
        rows = await self._data("/trades", {"user": wallet, "limit": min(limit, 1000)})
        return [parse_trade(r) for r in rows]

    async def history(self, wallet: str, limit: int = 50) -> WalletHistory:
        rows = await self._data("/activity", {"user": wallet, "limit": limit})
        return parse_history(wallet, rows, limit)

    async def leaderboard(
        self, period: str = "week", sort_by: str = "PNL", category: str = "overall", limit: int = 10
    ) -> list[LeaderRow]:
        rows = await self._data(
            "/leaderboard", {"time_period": period, "sort_by": sort_by, "category": category, "limit": limit}
        )
        return [parse_leader(r) for r in rows]

    async def aclose(self) -> None:
        await self.http.aclose()
