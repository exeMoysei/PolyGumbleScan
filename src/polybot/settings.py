"""Runtime configuration (environment variables, prefix ``POLYBOT_``). Secrets never have defaults."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from polybot.domain.enums import Route


class Settings(BaseSettings):
    # empty values ("POLYBOT_TECH_CHAT_ID=" in a freshly copied .env.example) mean "not set"
    model_config = SettingsConfigDict(
        env_prefix="POLYBOT_", env_file=".env", extra="ignore", env_nested_delimiter="__", env_ignore_empty=True
    )

    env: str = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://polybot:polybot@localhost:5432/polybot"
    redis_url: str = "redis://localhost:6379/0"

    # ---------------------------------------------------------------- telegram
    telegram_bot_token: SecretStr | None = None
    admin_ids: list[int] = Field(default_factory=list)
    tech_chat_id: int | None = None

    # ---------------------------------------------------------------- sources
    # staging smoke test: replay the labelled TEST DATA fixtures with a live clock instead of real feeds
    fixtures_dir: str | None = None
    leagues: list[str] = Field(default_factory=lambda: ["nba"])
    polymarket_enabled: bool = True
    polymarket_tags: dict[str, str] = Field(
        default_factory=lambda: {"nba": "nba", "nfl": "nfl", "nhl": "nhl", "mlb": "mlb", "epl": "epl"}
    )
    polymarket_fee_rate: Decimal = Decimal("0")  # overridden per market when the venue reports it
    polymarket_fee_exponent: Decimal = Decimal("1")
    polymarket_size_step: Decimal = Decimal("1")
    polymarket_ws: bool = False  # optional streaming on top of REST polling
    kalshi_enabled: bool = True
    kalshi_series: dict[str, str] = Field(
        default_factory=lambda: {
            "nba": "KXNBAGAME",
            "nfl": "KXNFLGAME",
            "nhl": "KXNHLGAME",
            "mlb": "KXMLBGAME",
            "epl": "KXEPLGAME",
        }
    )
    kalshi_fee_rate: Decimal = Decimal("0.07")
    odds_api_enabled: bool = True
    odds_api_key: SecretStr | None = None
    odds_api_regions: list[str] = Field(default_factory=lambda: ["eu"])
    odds_api_markets: list[str] = Field(default_factory=lambda: ["h2h"])
    odds_api_bookmakers: list[str] = Field(default_factory=list)  # empty = all
    odds_api_currency: str = "USD"  # currency of the user's sportsbook accounts
    sportsbook_min_stake: Decimal = Decimal("1")
    sportsbook_stake_step: Decimal = Decimal("1")
    sportsbook_max_stake: dict[str, Decimal] = Field(default_factory=dict)  # venue_id -> known max stake
    horizon_hours: int = 72

    # ---------------------------------------------------------------- ingest
    discovery_interval_s: int = 600
    quote_interval_s: dict[str, int] = Field(default_factory=lambda: {"polymarket": 15, "kalshi": 15, "oddsapi": 300})
    quote_ttl_s: dict[str, int] = Field(default_factory=lambda: {"polymarket": 90, "kalshi": 90, "oddsapi": 600})
    max_quote_skew_s: int = 300
    prematch_buffer_min: int = 5
    raw_retention_days: int = 14

    # ---------------------------------------------------------------- scan
    budget_currency: str = "USD"
    default_budget: Decimal = Decimal("100")
    max_budget: Decimal = Decimal("5000")
    min_profit: Decimal = Decimal("1.00")
    min_roi: Decimal = Decimal("0.005")
    exceptional_tolerance: Decimal = Decimal("0")
    routes: list[Route] = Field(default_factory=lambda: [Route.PREDICTION_PREDICTION, Route.PREDICTION_SPORTSBOOK])
    max_legs: int = 3
    top_offers_per_selection: int = 3
    solver_max_anchor_points: int = 20_000
    solver_max_evaluations: int = 200_000
    scan_debounce_ms: int = 500
    auto_approve_strong_matches: bool = False  # MVP: every new mapping is approved by an admin
    signal_ttl_s: int = 600
    # FX: "BASE/QUOTE=rate" ; applied with fx_reserve_bps against the user
    fx_static: dict[str, Decimal] = Field(default_factory=lambda: {"USDC/USD": Decimal("1")})
    fx_reserve_bps: Decimal = Decimal("30")
    fx_ttl_s: int = 900

    # ---------------------------------------------------------------- notify
    outbox_lease_s: int = 30
    outbox_max_attempts: int = 8
    metrics_port: int = 9108

    @field_validator("leagues")
    @classmethod
    def _known_leagues(cls, v: list[str]) -> list[str]:
        allowed = {"nba", "nfl", "nhl", "mlb", "epl"}
        bad = [x for x in v if x not in allowed]
        if bad:
            raise ValueError(f"unsupported leagues: {bad}")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
