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
        "SIGNAL",
        "Los Angeles Lakers @ Boston Celtics",
        "Polymarket",
        "Kalshi",
        "Win:",
        "Exceptions",
        "Min. P&amp;L",
        "Snapshot",
        "available",
        'href="https://polymarket.com/',
    ):
        assert needle in text, needle
    cand = next(p for p in payloads if p["verdict"] == "candidate")
    ct = render_card(cand)
    assert "CANDIDATE" in ct and "limit: unknown" in ct and "aggregator" in ct
    rules = render_rules(signal)
    assert "cancellation" in rules and "50/50" in rules
    assert "Signal closed" in render_closed(signal, ["no_longer_profitable"])


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


async def test_all_fixture_cards_and_keyboards_are_english() -> None:
    import re

    from polybot.telegram.bot import ADMIN_HELP, COMMANDS, HELP
    from polybot.telegram.keyboards import card_keyboard, filters_keyboard, main_menu_keyboard, mapping_keyboard

    texts = [HELP, ADMIN_HELP, *(c.description for c in COMMANDS)]
    keyboards = [main_menu_keyboard(), filters_keyboard({}), mapping_keyboard(1, "abc123")]
    for payload in await _payloads():
        texts.extend((render_card(payload), render_rules(payload), render_closed(payload, ["quote_stale"])))
        keyboards.append(card_keyboard(1, 1, payload))
    texts.extend(button.text for keyboard in keyboards for row in keyboard.inline_keyboard for button in row)
    assert all(not re.search(r"[\u0400-\u04ff]", text) for text in texts)


async def test_legacy_card_labels_render_in_english_without_changing_payload() -> None:
    from copy import deepcopy

    payload = next(p for p in await _payloads() if p["verdict"] == "signal")
    payload["legs"][0]["selection"]["label"] = "НЕ Boston Celtics"
    legacy_labels = {
        "cancelled": "Матч отменён",
        "postponed": "Перенос за пределы отсечки",
        "win:nba:lal": "Победа Los Angeles Lakers",
        "win:nba:bos": "Победа Boston Celtics",
    }
    for scenario in payload["pnl"]:
        scenario["label"] = legacy_labels[scenario["id"]]
    before = deepcopy(payload)
    text = render_card(payload)
    assert "NOT Boston Celtics" in text and "Win: Los Angeles Lakers" in text
    assert "Event cancelled" in text and "Postponed beyond the cutoff" in text
    assert "NOT Boston Celtics" in render_rules(payload)
    assert payload == before


def test_legacy_total_and_draw_labels_are_english() -> None:
    from polybot.telegram.cards import english_label

    for legacy, english in (
        ("Ничья", "Draw"),
        ("Не ничья", "Not a draw"),
        ("Больше 2.5", "Over 2.5"),
        ("Меньше 2.5", "Under 2.5"),
        ("Тотал = 3 (возврат)", "Total = 3 (refund)"),
    ):
        assert english_label(legacy) == english
