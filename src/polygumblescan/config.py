"""Konfiguracja aplikacji wczytywana ze zmiennych środowiskowych / pliku .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./polygumblescan.db"
    polymarket_gamma_url: str = "https://gamma-api.polymarket.com"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
