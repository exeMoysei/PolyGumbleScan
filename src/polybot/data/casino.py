"""Casino data source (US10, owner: Mikhailo Ivanyshyn) — SKELETON, not wired into the app yet.

Goal: notice when a watched crypto-casino player places or wins a large amount.

Open decision (team, before implementing): where the data comes from. No large crypto casino (Stake, Rollbit,
BC.Game) publishes an official API of other players' bets. Options noted in ``docs/podzial-pracy.md``:
1. On-chain casinos: bets and wins are public blockchain transactions (read through a Polygon RPC node).
2. Scraping a casino site: against its terms of use and usually blocked by Cloudflare — not recommended.

Fill in the functions below, then add the watcher to ``polybot.services.wallets`` (or a new service) and the
``AlertType.CASINO`` switch is already in ``/filters``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from polybot.logic.casino_alerts import CasinoBet


class CasinoSource(Protocol):
    """What the alert logic needs from any casino data source."""

    async def recent_bets(self, since: datetime) -> list[CasinoBet]: ...

    async def player_bets(self, player: str, since: datetime) -> list[CasinoBet]: ...

    async def aclose(self) -> None: ...


class OnChainCasinoSource:
    """Reads bets of on-chain casino contracts from a Polygon JSON-RPC node (``eth_getLogs``)."""

    def __init__(self, rpc_url: str, casino_contracts: dict[str, str]) -> None:
        self.rpc_url = rpc_url
        self.casino_contracts = casino_contracts  # contract address -> casino name

    async def recent_bets(self, since: datetime) -> list[CasinoBet]:
        """All bets on the configured contracts after ``since`` (decode the contracts' bet/settle events)."""
        raise NotImplementedError("US10: choose the casino contracts and decode their events")

    async def player_bets(self, player: str, since: datetime) -> list[CasinoBet]:
        """Bets of one player (wallet) after ``since``."""
        raise NotImplementedError("US10")

    async def aclose(self) -> None:
        return None
