from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from polybot.adapters.fixture import fixture_adapters
from polybot.logging import mask
from polybot.matching.teams import TeamRegistry
from polybot.services.payload import draft_payload
from polybot.services.pipeline import collect, run_offline
from polybot.services.scanner import ScanConfig
from polybot.telegram.cards import render_card, render_closed, render_rules
from polybot.telegram.keyboards import toggle_filter
from tests.unit.test_pipeline import fx

FIX = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)


async def _payloads() -> list[dict]:  # type: ignore[type-arg]
    world = await collect(fixture_adapters(FIX, ["nba", "epl"], now=NOW))
    _, scan = run_offline(world, TeamRegistry.default(), ScanConfig(budget=Decimal(200)), fx(), NOW, lambda p: True)
    return [draft_payload(d) for d in scan.drafts]


async def test_card_contains_required_sections() -> None:
    payloads = await _payloads()
    signal = next(p for p in payloads if p["verdict"] == "signal")
    text = render_card(signal)
    for needle in (
        "СИГНАЛ",
        "Los Angeles Lakers @ Boston Celtics",
        "Polymarket",
        "Kalshi",
        "Победа",
        "Исключения",
        "Мин. P&amp;L",
        "Снимок",
        "доступно",
        'href="https://polymarket.com/',
    ):
        assert needle in text, needle
    cand = next(p for p in payloads if p["verdict"] == "candidate")
    ct = render_card(cand)
    assert "КАНДИДАТ" in ct and "лимит: unknown" in ct and "агрегатором" in ct
    rules = render_rules(signal)
    assert "отмена" in rules and "50/50" in rules
    assert "Сигнал закрыт" in render_closed(signal, ["no_longer_profitable"])


def test_filter_toggles() -> None:
    f = toggle_filter({}, "verdict", "candidate")
    assert set(f["verdicts"]) == {"signal", "candidate"}
    f = toggle_filter(f, "route", "prediction_sportsbook")
    assert f["routes"] == ["prediction_prediction"]
    f = toggle_filter(f, "route", "prediction_sportsbook")
    assert f["routes"] == []
    assert toggle_filter({"min_roi": "0.01"}, "min_roi", "0.01")["min_roi"] is None


def test_log_masking() -> None:
    s = mask(
        "token 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ and apiKey=abc&x=1 "
        "postgresql+asyncpg://polybot:hunter2@db/polybot"
    )
    assert "AAHdq" not in s and "abc" not in s and "hunter2" not in s
