from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from polybot.domain.enums import MarketType, Period

LEAGUE_SPORT = {
    "nba": "basketball",
    "nfl": "american_football",
    "nhl": "hockey",
    "mlb": "baseball",
    "epl": "soccer",
}


def default_winner_market(league: str) -> tuple[MarketType, Period]:
    if LEAGUE_SPORT.get(league) == "soccer":
        return MarketType.MATCH_RESULT, Period.REGULATION
    return MarketType.MONEYLINE, Period.FULL_GAME


def parse_ts(value: Any) -> datetime | None:
    """Parse ISO strings ("2026-01-16T00:30:00Z", "2026-01-16 00:30:00+00") or epoch (s/ms)."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float) or (isinstance(value, str) and value.isdigit()):
        n = float(value)
        if n > 1e12:
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=UTC)
    s = str(value).strip().replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if len(s) >= 3 and (s[-3] in "+-") and ":" not in s[-3:]:
        s = s + ":00"  # "+00" -> "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def raw_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def maybe_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, list) else []
    return []
