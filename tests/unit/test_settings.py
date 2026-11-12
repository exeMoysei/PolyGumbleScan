from pathlib import Path

import pytest

from polybot.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_env_example_copied_as_is_is_a_valid_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cp .env.example .env` must start: empty values count as "not set" (docker passes them as "")."""
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            monkeypatch.setenv(key, value)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.tech_chat_id is None
    assert s.odds_api_key is None  # an empty key must not enable the Odds API adapter
    assert s.telegram_bot_token is None
    assert s.admin_ids == [] and s.leagues == ["nba"]
