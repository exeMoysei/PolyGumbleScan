"""Offline engine tests. All prices below are TEST DATA (synthetic)."""

from decimal import Decimal

from polybot.domain.enums import MarketType, Period, SettlementPolicy, SolveStatus, Verdict
from polybot.domain.fees import KalshiTakerFee, PolymarketTakerFee
from polybot.domain.prefilter import ideal_stakes, prefilter
from polybot.domain.scenarios import build_space
from polybot.domain.solver import SolverConfig, evaluate, solve
from polybot.domain.verdict import Thresholds, assess
from tests.factories import (
    KALSHI,
    POLY,
    kalshi_fee,
    nba_space,
    prediction_leg,
    rules,
    soccer_space,
    sportsbook_leg,
)

D = Decimal


def test_ideal_stakes_textbook_example() -> None:
    stakes, payout = ideal_stakes([1 / D("0.45"), D("2.10")], D(100))
    assert round(stakes[0], 2) == D("48.59")
    assert round(stakes[1], 2) == D("51.41")
    assert round(payout, 2) == D("107.97")


def test_both_routes_share_scenarios() -> None:
    space = nba_space()
    lal, bos = space.team_win("nba:lal"), space.team_win("nba:bos")
    pp = [prediction_leg(POLY, lal, [("0.45", "1000")]), prediction_leg(KALSHI, bos, [("0.50", "1000")])]
    ps = [prediction_leg(POLY, lal, [("0.45", "1000")]), sportsbook_leg(bos, "2.10")]
    r1 = solve(pp, space.all, D(100))
    r2 = solve(ps, space.all, D(100))
    assert r1.best and r2.best
    assert (
        [s for s, _ in r1.best.pnl]
        == [s for s, _ in r2.best.pnl]
        == ["win:nba:bos", "win:nba:lal", "cancelled", "postponed"]
    )


def test_positive_plan_prediction_vs_sportsbook() -> None:
    space = nba_space()
    legs = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.45", "1000")]),
        sportsbook_leg(space.team_win("nba:bos"), "2.10"),
    ]
    res = solve(legs, space.all, D(100))
    assert res.status == SolveStatus.OK and res.best
    plan = res.best
    assert plan.total_cost <= D(100)
    assert plan.worst_regular > 0
    # equal-ish payouts: every regular scenario is profitable
    assert plan.pnl_of("win:nba:lal") > 0 and plan.pnl_of("win:nba:bos") > 0
    # integer steps: contracts and whole-unit stakes
    assert all(pl.fill.size == pl.fill.size.to_integral_value() for pl in plan.legs)
    a = assess(res, legs, Thresholds(D("1"), D("0.01")))
    assert a.verdict == Verdict.SIGNAL


def test_zero_and_negative_pnl_rejected() -> None:
    space = nba_space()
    # exactly fair: 0.50 + 0.50 -> best possible P&L is 0
    fair = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.50", "1000")]),
        prediction_leg(KALSHI, space.team_win("nba:bos"), [("0.50", "1000")]),
    ]
    res = solve(fair, space.all, D(100))
    assert res.best and res.best.worst_regular == 0
    assert assess(res, fair, Thresholds()).verdict == Verdict.REJECTED
    neg = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.55", "1000")]),
        prediction_leg(KALSHI, space.team_win("nba:bos"), [("0.50", "1000")]),
    ]
    res2 = solve(neg, space.all, D(100))
    a = assess(res2, neg, Thresholds())
    assert a.verdict == Verdict.REJECTED and "negative_pnl" in a.reasons
    assert not prefilter(neg, space.all).passes


def test_sportsbook_payout_rounds_down_and_stake_step() -> None:
    space = nba_space()
    leg = sportsbook_leg(space.team_win("nba:bos"), "2.333", step="1")
    fill = leg.fill(D(7))
    assert fill is not None
    win = leg.cashflow(fill, space.regular[0])
    assert win == D("16.33")  # 7 * 2.333 = 16.331 -> floored to cents
    assert leg.fill(D("0.5")) is None  # below min stake


def test_kalshi_and_polymarket_fee_formulas() -> None:
    k = KalshiTakerFee(D("0.07"))
    # 0.07 * 100 * 0.45 * 0.55 = 1.7325 -> 1.74
    assert k.entry_fee([(D("0.45"), D(100))], D(45)) == D("1.74")
    p = PolymarketTakerFee(rate=D("0.03"), exponent=D(1))
    # 100 * 0.45 * 0.03 * (0.45*0.55) = 0.334125 -> 0.3342 (ceil to 0.0001)
    assert p.entry_fee([(D("0.45"), D(100))], D(45)) == D("0.3342")


def test_fees_reduce_profit_and_can_kill_edge() -> None:
    space = nba_space()
    base = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.48", "5000")]),
        prediction_leg(KALSHI, space.team_win("nba:bos"), [("0.50", "5000")]),
    ]
    no_fee = solve(base, space.all, D(1000))
    with_fee = [base[0], prediction_leg(KALSHI, space.team_win("nba:bos"), [("0.50", "5000")], fee=kalshi_fee())]
    fee_res = solve(with_fee, space.all, D(1000))
    assert no_fee.best and no_fee.best.worst_regular > 0
    # 2 % edge minus Kalshi fee (~1.75 % of notional at p=0.5) -> much smaller or gone
    assert fee_res.best_risky is None or fee_res.best_risky.worst_regular < no_fee.best.worst_regular


def test_max_stake_limits_plan_size() -> None:
    space = nba_space()
    legs = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.45", "100000")]),
        sportsbook_leg(space.team_win("nba:bos"), "2.10", max_stake="30"),
    ]
    res = solve(legs, space.all, D(1000))
    assert res.best
    stake = res.best.legs[1].fill.size
    assert stake <= D(30)
    assert res.best.total_cost < D(100)


def test_draw_pair_rejected_and_three_way_covers() -> None:
    space = soccer_space()
    ars, che = space.team_win("epl:ars"), space.team_win("epl:che")
    two = [prediction_leg(POLY, ars, [("0.40", "1000")]), sportsbook_leg(che, "3.20")]
    res = solve(two, space.all, D(100))
    assert res.status == SolveStatus.NO_PLAN and "uncovered_scenario:draw" in res.reasons
    three = [
        prediction_leg(POLY, ars, [("0.40", "1000")]),
        prediction_leg(KALSHI, space.draw(), [("0.25", "1000")]),
        sportsbook_leg(che, "3.40"),
    ]
    res3 = solve(three, space.all, D(100))
    assert res3.status == SolveStatus.OK and res3.best_risky
    assert all(res3.best_risky.pnl_of(s.id) is not None for s in space.regular)


def test_team_vs_team_or_draw_covers_three_results() -> None:
    space = soccer_space()
    legs = [
        prediction_leg(POLY, space.team_win("epl:ars"), [("0.40", "1000")]),
        prediction_leg(KALSHI, space.not_team_win("epl:ars"), [("0.55", "1000")]),
    ]
    res = solve(legs, space.all, D(100))
    assert res.best and res.best.worst_regular > 0
    assert {s for s, _ in res.best.pnl} >= {"win:epl:ars", "draw", "win:epl:che"}


def test_overtime_and_regulation_have_different_spaces() -> None:
    ft = build_space("hockey", MarketType.MONEYLINE, Period.FULL_GAME, ("nhl:bos", "nhl:tor"))
    reg = build_space("hockey", MarketType.MONEYLINE, Period.REGULATION, ("nhl:bos", "nhl:tor"))
    assert not ft.has_draw() and reg.has_draw()


def test_refund_both_vs_one_side_with_nonrefundable_fees() -> None:
    space = nba_space()
    lal, bos = space.team_win("nba:lal"), space.team_win("nba:bos")
    # both sides refund stakes on cancel, Kalshi fee is not refunded
    both = [
        prediction_leg(
            KALSHI, lal, [("0.45", "1000")], fee=kalshi_fee(), rule_set=rules("kalshi", cancel=SettlementPolicy.REFUND)
        ),
        sportsbook_leg(bos, "2.20", rule_set=rules("oddsapi", cancel=SettlementPolicy.REFUND)),
    ]
    plan = evaluate(both, [D(100), D(50)], space.all)
    assert plan is not None
    fee = plan.legs[0].fill.fee
    assert fee > 0
    assert plan.pnl_of("cancelled") == -fee  # zero result except the fee
    # one side resolves 50-50 (Polymarket style), the other refunds
    one = [
        prediction_leg(POLY, lal, [("0.45", "1000")], rule_set=rules("polymarket", cancel=SettlementPolicy.HALF)),
        sportsbook_leg(bos, "2.20", rule_set=rules("oddsapi", cancel=SettlementPolicy.REFUND)),
    ]
    plan2 = evaluate(one, [D(100), D(50)], space.all)
    assert plan2 is not None
    assert plan2.pnl_of("cancelled") == D(50) - D(45)  # 100*0.5 - 45 (stake 50 refunded)


def test_exceptional_loss_makes_candidate_not_signal() -> None:
    space = nba_space()
    lal, bos = space.team_win("nba:lal"), space.team_win("nba:bos")
    legs = [
        prediction_leg(POLY, lal, [("0.45", "1000")], rule_set=rules("polymarket", cancel=SettlementPolicy.LOSE)),
        sportsbook_leg(bos, "2.10"),
    ]
    res = solve(legs, space.all, D(100))
    assert res.best is None and res.best_risky is not None
    a = assess(res, legs, Thresholds())
    assert a.verdict == Verdict.CANDIDATE and "exceptional_loss_possible" in a.reasons


def test_unknown_exceptional_rules_make_candidate() -> None:
    space = nba_space()
    legs = [
        prediction_leg(
            POLY,
            space.team_win("nba:lal"),
            [("0.45", "1000")],
            rule_set=rules("polymarket", cancel=SettlementPolicy.UNKNOWN),
        ),
        sportsbook_leg(space.team_win("nba:bos"), "2.10"),
    ]
    a = assess(solve(legs, space.all, D(100)), legs, Thresholds())
    assert a.verdict == Verdict.CANDIDATE and "exceptional_unknown" in a.reasons


def test_depth_average_price_and_vanishing_spread() -> None:
    space = nba_space()
    # top of book 0.45 for only 10 contracts, then 0.55
    thin = prediction_leg(POLY, space.team_win("nba:lal"), [("0.45", "10"), ("0.55", "1000")])
    fill = thin.fill(D(20))
    assert fill is not None and fill.avg_price == D("0.50")
    assert thin.fill(D(2000)) is None  # not enough depth
    legs = [thin, sportsbook_leg(space.team_win("nba:bos"), "2.05")]
    assert prefilter(legs, space.all).passes  # 0.45 + 1/2.05 < 1 at the top level
    res = solve(legs, space.all, D(500))
    assert res.best is not None
    # the best plan stays small: buying deeper kills the edge
    assert res.best.legs[0].fill.size <= D(10)
    big = evaluate(legs, [D(200), D(100)], space.all)
    assert big is not None and big.worst_regular < 0


def test_solver_limit() -> None:
    space = nba_space()
    legs = [
        prediction_leg(POLY, space.team_win("nba:lal"), [("0.45", "1000000")], step="0.01"),
        sportsbook_leg(space.team_win("nba:bos"), "2.10", step="0.01", max_stake=None),
    ]
    res = solve(legs, space.all, D(100000), SolverConfig(max_anchor_points=1000))
    assert res.status == SolveStatus.SOLVER_LIMIT
    assert assess(res, legs, Thresholds()).verdict == Verdict.REJECTED


def test_nfl_tie_uses_venue_rules() -> None:
    space = build_space("american_football", MarketType.MONEYLINE, Period.FULL_GAME, ("nfl:kc", "nfl:buf"))
    assert space.has_draw()
    kc, buf = space.team_win("nfl:kc"), space.team_win("nfl:buf")
    legs = [
        prediction_leg(POLY, kc, [("0.45", "1000")], rule_set=rules("polymarket", draw=SettlementPolicy.HALF)),
        sportsbook_leg(buf, "2.10", rule_set=rules("oddsapi", draw=SettlementPolicy.REFUND)),
    ]
    plan = evaluate(legs, [D(100), D(50)], space.all)
    assert plan is not None and plan.pnl_of("draw") == D(50) - D(45)
    unknown = [prediction_leg(POLY, kc, [("0.45", "1000")]), sportsbook_leg(buf, "2.10")]
    assert evaluate(unknown, [D(100), D(50)], space.all) is None  # tie settlement unknown -> invalid


def test_fx_reserve_is_conservative() -> None:
    from polybot.domain.models import FxRate
    from tests.factories import NOW

    space = nba_space()
    fx = FxRate("USDC", "USD", D("1"), NOW, __import__("datetime").timedelta(minutes=10), reserve_bps=D(20))
    leg = prediction_leg(POLY, space.team_win("nba:lal"), [("0.50", "1000")], currency="USDC", fx=fx)
    fill = leg.fill(D(100))
    assert fill is not None
    assert leg.to_budget_cost(fill.total_native) == D("50.1")  # +0.2 %
    assert leg.cashflow(fill, space.regular[1]) == D("99.8")  # -0.2 %


def test_postponement_carry_vs_void() -> None:
    space = nba_space()
    lal, bos = space.team_win("nba:lal"), space.team_win("nba:bos")
    carry = SettlementPolicy.CARRY
    # both venues keep positions open -> postponed result equals the worst regular result
    both = [
        prediction_leg(POLY, lal, [("0.45", "1000")], rule_set=rules("polymarket", postpone=carry)),
        prediction_leg(KALSHI, bos, [("0.50", "1000")], rule_set=rules("kalshi", postpone=carry)),
    ]
    p = evaluate(both, [D(100), D(100)], space.all)
    assert p is not None and p.pnl_of("postponed") == p.worst_regular == D(5)
    # one side voids, the other carries: worst case the surviving leg loses
    mixed = [both[0], sportsbook_leg(bos, "2.10", rule_set=rules("oddsapi", postpone=SettlementPolicy.REFUND))]
    p2 = evaluate(mixed, [D(100), D(50)], space.all)
    assert p2 is not None and p2.pnl_of("postponed") == D(50) - D(95)


def test_resolves_no_on_cancel_is_asymmetric() -> None:
    space = nba_space()
    r = rules("kalshi", cancel=SettlementPolicy.NO_WINS)
    yes = prediction_leg(KALSHI, space.team_win("nba:lal"), [("0.45", "1000")], rule_set=r)
    no = prediction_leg(KALSHI, space.not_team_win("nba:lal"), [("0.55", "1000")], rule_set=r)
    cancelled = space.exceptional[0]
    assert yes.policy(cancelled) == SettlementPolicy.LOSE
    assert no.policy(cancelled) == SettlementPolicy.WIN
