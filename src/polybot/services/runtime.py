"""Construction of adapters and shared resources from settings."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from polybot.adapters.base import Adapter
from polybot.adapters.kalshi.adapter import KalshiAdapter
from polybot.adapters.odds_api.adapter import OddsApiAdapter
from polybot.adapters.polymarket.adapter import PolymarketAdapter
from polybot.domain.enums import VenueKind
from polybot.matching.teams import TeamRegistry
from polybot.settings import Settings

SOURCE_KIND = {"polymarket": VenueKind.PREDICTION, "kalshi": VenueKind.PREDICTION, "oddsapi": VenueKind.SPORTSBOOK}


def build_adapters(settings: Settings) -> list[Adapter]:
    horizon = timedelta(hours=settings.horizon_hours)
    adapters: list[Any] = []
    if settings.polymarket_enabled:
        adapters.append(
            PolymarketAdapter(
                {lg: settings.polymarket_tags[lg] for lg in settings.leagues if lg in settings.polymarket_tags},
                fee_rate=settings.polymarket_fee_rate,
                fee_exponent=settings.polymarket_fee_exponent,
                horizon=horizon,
            )
        )
    if settings.kalshi_enabled:
        adapters.append(
            KalshiAdapter(
                {lg: settings.kalshi_series[lg] for lg in settings.leagues if lg in settings.kalshi_series},
                fee_rate=settings.kalshi_fee_rate,
                horizon=horizon,
            )
        )
    if settings.odds_api_enabled and settings.odds_api_key is not None:
        adapters.append(
            OddsApiAdapter(
                settings.odds_api_key.get_secret_value(),
                settings.leagues,
                regions=settings.odds_api_regions,
                markets=tuple(settings.odds_api_markets),
                bookmakers=set(settings.odds_api_bookmakers) or None,
                horizon=horizon,
            )
        )
    return adapters


def registry_with_aliases(aliases: list[tuple[str, str, str]]) -> TeamRegistry:
    reg = TeamRegistry.default()
    for league, alias, team_id in aliases:
        if team_id in reg.teams:
            reg.add_alias(league, alias, team_id)
    return reg
