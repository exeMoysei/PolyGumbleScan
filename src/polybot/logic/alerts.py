"""Alert types a user can switch on and off (US8)."""

from __future__ import annotations

from enum import StrEnum


class AlertType(StrEnum):
    ARBITRAGE = "arbitrage"  # cross-venue arbitrage cards (Polymarket ↔ Kalshi ↔ sportsbooks)
    YES_SUM = "yes_sum"  # Polymarket multi-outcome event whose YES prices add up to less than 1 (US3)
    WHALES = "whales"  # a new wallet places a large bet (US6)
    WALLETS = "wallets"  # a wallet the user follows trades (US7)
    CASINO = "casino"  # a watched casino player bets or wins big (US10, data source not chosen yet)


ALERT_LABELS: dict[AlertType, str] = {
    AlertType.ARBITRAGE: "Arbitrage",
    AlertType.YES_SUM: "YES sum < 1",
    AlertType.WHALES: "New-wallet whales",
    AlertType.WALLETS: "Followed wallets",
    AlertType.CASINO: "Casino players",
}

# outbox ``kind`` -> alert type
OUTBOX_KINDS: dict[str, AlertType] = {
    "signal": AlertType.ARBITRAGE,
    "update": AlertType.ARBITRAGE,
    "yes_sum": AlertType.YES_SUM,
    "whale": AlertType.WHALES,
    "wallet": AlertType.WALLETS,
    "casino": AlertType.CASINO,
}


def enabled(filters: dict[str, object] | None, alert: AlertType) -> bool:
    """All types are on unless the user switched them off (``filters["alerts_off"]``)."""
    off = (filters or {}).get("alerts_off") or []
    return isinstance(off, list) and alert.value not in off


def toggle(filters: dict[str, object] | None, alert: AlertType) -> dict[str, object]:
    f = dict(filters or {})
    off = set(f.get("alerts_off") or [])  # type: ignore[call-overload]
    off ^= {alert.value}
    f["alerts_off"] = sorted(off)
    return f
