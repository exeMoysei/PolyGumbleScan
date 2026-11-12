"""A leg = one bet at one venue on one canonical selection, with everything needed to price it exactly."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from polybot.domain.enums import QuoteKind, ScenarioKind, SettlementPolicy, VenueKind
from polybot.domain.fees import FeeModel, NoFee
from polybot.domain.models import FxRate, Quote, RuleSet, Scenario, Selection, Venue
from polybot.domain.money import BPS, CENT, ONE, ZERO, floor_step


@dataclass(frozen=True, slots=True)
class Fill:
    size: Decimal  # contracts (prediction) or stake (sportsbook), native units
    notional: Decimal  # money paid for the contracts / the stake, native currency, before fees
    fee: Decimal  # entry fee, native currency
    fills: tuple[tuple[Decimal, Decimal], ...]  # (price, qty) per consumed level

    @property
    def total_native(self) -> Decimal:
        return self.notional + self.fee

    @property
    def avg_price(self) -> Decimal:
        return self.notional / self.size if self.size else ZERO


@dataclass(frozen=True, slots=True)
class Leg:
    venue: Venue
    selection: Selection
    rules: RuleSet
    quote: Quote
    fee: FeeModel = field(default_factory=NoFee)
    fx: FxRate | None = None  # native currency -> budget currency
    min_size: Decimal = ONE
    step: Decimal = ONE
    max_size: Decimal | None = None  # sportsbook max stake / venue cap, native units
    payout_step: Decimal = CENT  # sportsbook payout rounding (always down)
    market_url: str | None = None
    label: str = ""

    # ------------------------------------------------------------ properties
    @property
    def is_prediction(self) -> bool:
        return self.quote.kind == QuoteKind.ASK_LEVELS

    @property
    def currency(self) -> str:
        return self.quote.currency

    @property
    def limits_known(self) -> bool:
        if self.is_prediction:
            return self.quote.total_size is not None
        return self.max_size is not None

    @property
    def depth_cap(self) -> Decimal | None:
        if self.is_prediction:
            return self.quote.total_size
        return None

    def upper_size(self) -> Decimal | None:
        caps = [c for c in (self.max_size, self.depth_cap) if c is not None]
        return min(caps) if caps else None

    # ------------------------------------------------------------ fx (conservative both ways)
    def to_budget_cost(self, native: Decimal) -> Decimal:
        if self.fx is None:
            return native
        return native * self.fx.rate * (ONE + self.fx.reserve_bps * BPS)

    def to_budget_income(self, native: Decimal) -> Decimal:
        if self.fx is None:
            return native
        return native * self.fx.rate * (ONE - self.fx.reserve_bps * BPS)

    def from_budget_income(self, budget_amount: Decimal) -> Decimal:
        if self.fx is None:
            return budget_amount
        return budget_amount / (self.fx.rate * (ONE - self.fx.reserve_bps * BPS))

    # ------------------------------------------------------------ pricing
    def fill(self, size: Decimal) -> Fill | None:
        """Exact cost of ``size`` units walking the book; None if depth or limits are insufficient."""
        if size < self.min_size:
            return None
        if self.max_size is not None and size > self.max_size:
            return None
        if self.is_prediction:
            remaining = size
            notional = ZERO
            fills: list[tuple[Decimal, Decimal]] = []
            for level in self.quote.levels:
                if remaining <= 0:
                    break
                avail = level.size if level.size is not None else remaining
                take = min(avail, remaining)
                if take <= 0:
                    continue
                fills.append((level.price, take))
                notional += take * level.price
                remaining -= take
            if remaining > 0:
                return None
            fee = self.fee.entry_fee(fills, notional)
            return Fill(size, notional, fee, tuple(fills))
        price = self.quote.best_price
        if price is None:
            return None
        fee = self.fee.entry_fee([(price, size)], size)
        return Fill(size, size, fee, ((price, size),))

    def gross_win_native(self, size: Decimal) -> Decimal:
        if self.is_prediction:
            return size  # every contract pays 1 unit of the quote currency
        price = self.quote.best_price
        assert price is not None
        return floor_step(size * price, self.payout_step)

    def policy(self, scenario: Scenario) -> SettlementPolicy:
        if scenario.kind == ScenarioKind.REGULAR:
            if scenario.id in self.selection.undefined:
                pol = self.rules.on_draw
            else:
                return self.selection.regular_policy(scenario.id)
        else:
            pol = self.rules.exceptional_policy(scenario.id)
        if pol == SettlementPolicy.NO_WINS:
            if not self.is_prediction:
                return SettlementPolicy.UNKNOWN
            return SettlementPolicy.WIN if self.selection.negated else SettlementPolicy.LOSE
        return pol

    def cashflow(self, fill: Fill, scenario: Scenario) -> Decimal | None:
        """Money received at settlement in budget currency, ``None`` when the rules don't say."""
        policy = self.policy(scenario)
        native: Decimal
        if policy == SettlementPolicy.WIN:
            gross = self.gross_win_native(fill.size)
            native = gross - self.fee.settlement_deduction(gross, gross - fill.notional)
        elif policy == SettlementPolicy.LOSE:
            native = ZERO
        elif policy == SettlementPolicy.REFUND:
            native = fill.notional  # entry fees are not refunded
        elif policy == SettlementPolicy.CARRY:
            return None  # handled at plan level (see solver.evaluate)
        elif policy == SettlementPolicy.HALF:
            if not self.is_prediction:
                return None
            native = fill.size / 2
        else:
            return None
        return self.to_budget_income(native)

    def size_for_payout(self, target_budget: Decimal) -> Decimal:
        """Continuous size whose winning payout equals ``target_budget`` (budget currency)."""
        native = self.from_budget_income(target_budget)
        if self.is_prediction:
            return native
        price = self.quote.best_price
        assert price is not None and price > 0
        return native / price

    def effective_unit_cost(self) -> Decimal | None:
        """Top-of-book cost per unit of winning payout (budget currency), fees included."""
        price = self.quote.best_price
        if price is None or price <= 0:
            return None
        if self.is_prediction:
            # large notional quantity so per-fill rounding does not inflate the lower bound
            unit = Decimal(1_000_000)
            f = self.fee.entry_fee([(price, unit)], price * unit)
            per_unit = price + f / unit
            return self.to_budget_cost(per_unit) / self.to_budget_income(ONE)
        stake_fee = self.fee.entry_fee([(price, ONE)], ONE)
        return self.to_budget_cost(ONE + stake_fee) / self.to_budget_income(price)

    @property
    def venue_kind(self) -> VenueKind:
        return self.venue.kind
