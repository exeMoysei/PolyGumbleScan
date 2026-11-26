"""Wallet alerts, ranking, YES-sum arbitrage and alert types on TEST DATA fixtures (no network)."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polybot.bot.alerts import render_followed, render_leaderboard, render_whale, render_yes_sum
from polybot.bot.wallets import parse_follow
from polybot.data.polymarket import fee_params, parse_neg_risk_event
from polybot.data.polymarket_users import parse_history, parse_leader, parse_trade
from polybot.logic.alerts import AlertType, enabled, toggle
from polybot.logic.fees import NoFee, PolymarketTakerFee
from polybot.logic.models import PriceLevel
from polybot.logic.wallets import NewWalletRule, big_trades, is_new_wallet, normalize_wallet
from polybot.logic.yes_sum import OutcomeBook, best_plan

FIX = Path(__file__).parent.parent / "fixtures"
D = Decimal
NOW = datetime.fromtimestamp(1795690100, tz=UTC)


def load(name: str):  # type: ignore[no-untyped-def]
    return json.loads((FIX / name).read_text())


def test_parse_trades_and_big_bets() -> None:
    trades = [parse_trade(r) for r in load("polymarket_data_trades.json")["data"]]
    assert trades[0].wallet == "0x" + "1" * 40 and trades[0].usdc == D("9000.00")
    assert trades[0].url == "https://polymarket.com/event/nba-lal-bos-2026-11-27"
    big = big_trades(trades, D(5000))
    assert [t.tx_hash for t in big] == ["0xtx1", "0xtx2"]  # the SELL is not a bet
    assert len({t.key for t in trades}) == 3


def test_new_wallet_detection() -> None:
    acts = load("polymarket_data_activity.json")
    new = parse_history("0x" + "1" * 40, acts["new_wallet"]["data"], limit=15)
    old = parse_history("0x" + "2" * 40, acts["old_wallet"]["data"], limit=15)
    rule = NewWalletRule(D(5000), max_prior_trades=10, max_age=timedelta(days=7))
    assert new.complete and new.trades_seen == 2 and is_new_wallet(new, NOW, rule)
    assert not old.complete and not is_new_wallet(old, NOW, rule)  # history longer than we fetched
    assert not is_new_wallet(new, NOW + timedelta(days=30), rule)  # first trade too long ago


def test_leaderboard_parsing_and_text() -> None:
    rows = [parse_leader(r) for r in load("polymarket_data_leaderboard.json")["data"]]
    assert rows[0].rank == 1 and rows[0].pnl == D("1506122.89") and rows[1].roi is None
    text = render_leaderboard(rows, "week", "PNL")
    assert "synthetic-top" in text and "0x1111…1111" in text and "+1 506 122.89" in text


def test_wallet_normalization_and_follow_args() -> None:
    w = "0x" + "AbCd" * 10
    assert normalize_wallet(w) == w.lower()
    assert normalize_wallet("0x123") is None and normalize_wallet("hello") is None
    assert parse_follow(f"{w} 500 big fish", D(100)) == (w.lower(), D(500), "big fish")
    assert parse_follow(w, D(100)) == (w.lower(), D(100), None)
    assert parse_follow("nope", D(100)) is None and parse_follow(f"{w} -5", D(100)) is None


def test_alert_types_default_on_and_toggle() -> None:
    assert all(enabled({}, a) for a in AlertType)
    f = toggle({}, AlertType.WHALES)
    assert not enabled(f, AlertType.WHALES) and enabled(f, AlertType.ARBITRAGE)
    assert enabled(toggle(f, AlertType.WHALES), AlertType.WHALES)


def test_fee_schedule_is_read_from_gamma() -> None:
    m = {"feesEnabled": True, "feeSchedule": {"exponent": 1, "rate": 0.05, "takerOnly": True}}
    assert fee_params(m, D(0), D(1)) == (D("0.05"), D(1))
    assert fee_params({**m, "feesEnabled": False}, D(0), D(1))[0] == 0
    assert fee_params({"fd": {"r": "0.02", "e": "2"}}, D(0), D(1)) == (D("0.02"), D(2))
    assert fee_params({}, D("0.03"), D(1)) == (D("0.03"), D(1))


def test_neg_risk_event_rules() -> None:
    evs = load("polymarket_negrisk_events.json")["events"]
    parsed = [parse_neg_risk_event(e, D(0), D(1)) for e in evs]
    fed = parsed[0]
    assert fed is not None and [o.label for o in fed.outcomes] == ["Cut 50+", "Cut 25", "No change"]
    assert fed.outcomes[0].fee_rate == D("0.01") and fed.url == "https://polymarket.com/event/fed-decision-in-december"
    assert parsed[1] is None  # outcome list can still grow
    assert parsed[2] is None  # one outcome already resolved YES
    assert parsed[3] is None  # not a negative-risk event


def _book(label: str, levels: list[tuple[str, str]], fee=None) -> OutcomeBook:  # type: ignore[no-untyped-def]
    return OutcomeBook(label, label, tuple(PriceLevel(D(p), D(s)) for p, s in levels), fee or NoFee(), D(1))


def test_yes_sum_plan_profit_depth_and_fees() -> None:
    books = [
        _book("A", [("0.30", "100"), ("0.40", "1000")]),
        _book("B", [("0.30", "1000")]),
        _book("C", [("0.35", "1000")]),
    ]
    plan = best_plan("Event", "https://polymarket.com/event/x", books, D(1000))
    assert plan is not None
    assert plan.top_sum == D("0.95") and plan.shares == D(100)  # deeper A asks kill the edge
    assert plan.cost == D("95.00") and plan.profit == D("5.00")
    with_fees = [
        _book(b.label, [(str(lv.price), str(lv.size)) for lv in b.asks], PolymarketTakerFee(D("0.05"))) for b in books
    ]
    plan_fees = best_plan("Event", "u", with_fees, D(1000))
    assert plan_fees is not None and plan_fees.fees > 0 and plan_fees.profit < plan.profit
    assert best_plan("E", "u", [_book("A", [("0.50", "10")]), _book("B", [("0.50", "10")])], D(100)) is None  # sum = 1
    small = best_plan("E", "u", books, D(10))  # the budget caps the size
    assert small is not None and small.shares == D(10) and small.profit == D("0.50")
    assert best_plan("E", "u", books, D("0.5")) is None  # not even one share of every outcome fits
    text = render_yes_sum(plan, 3)
    assert "YES SUM" in text and "+5.00" in text and "100" in text


def test_alert_texts() -> None:
    trades = [parse_trade(r) for r in load("polymarket_data_trades.json")["data"]]
    hist = parse_history(trades[0].wallet, load("polymarket_data_activity.json")["new_wallet"]["data"], 15)
    whale = render_whale(trades[0], hist)
    assert "NEW WALLET" in whale and "9 000.00 USDC" in whale and "2 trades so far" in whale
    followed = render_followed(trades[1], "my fish")
    assert "FOLLOWED WALLET" in followed and "my fish" in followed
