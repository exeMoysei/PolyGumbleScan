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


def test_repository_contains_no_cyrillic() -> None:
    """Project language rule: English code and bot texts, Polish docs, no Russian or Ukrainian."""
    import re
    import subprocess

    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    cyrillic = re.compile(f"[{chr(0x400)}-{chr(0x4FF)}]")  # built from code points: no Cyrillic in this file
    offenders = []
    for name in files:
        try:
            text = (ROOT / name).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if cyrillic.search(text):
            offenders.append(name)
    assert offenders == []
