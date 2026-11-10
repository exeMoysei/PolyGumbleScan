from polygumblescan.config import Settings


def test_defaults(monkeypatch):
    for name in ("BOT_TOKEN", "DATABASE_URL", "POLYMARKET_GAMMA_URL", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.bot_token == ""
    assert settings.database_url.startswith("sqlite+aiosqlite")
    assert settings.polymarket_gamma_url == "https://gamma-api.polymarket.com"
    assert settings.log_level == "INFO"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.bot_token == "123:abc"
    assert settings.log_level == "DEBUG"
