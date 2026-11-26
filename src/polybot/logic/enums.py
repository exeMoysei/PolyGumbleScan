from __future__ import annotations

from enum import StrEnum


class VenueKind(StrEnum):
    PREDICTION = "prediction"
    SPORTSBOOK = "sportsbook"
    EXCHANGE = "exchange"


class QuoteKind(StrEnum):
    ASK_LEVELS = "ask_levels"  # prediction market: price per contract paying 1, with sizes
    DECIMAL_ODDS = "decimal_odds"  # sportsbook: decimal odds incl. stake


class QuoteStatus(StrEnum):
    OPEN = "open"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class FreshnessSource(StrEnum):
    VENUE = "venue"  # timestamp comes from the venue itself (order book / direct feed)
    AGGREGATOR = "aggregator"  # timestamp only confirmed by an aggregator (The Odds API)


class MarketType(StrEnum):
    MONEYLINE = "moneyline"  # winner of the game, no draw outcome offered by the market
    MATCH_RESULT = "match_result"  # 1X2 three-way
    TOTAL = "total"
    SPREAD = "spread"


class Period(StrEnum):
    FULL_GAME = "full_game"  # including overtime / extra innings / shoot-out
    REGULATION = "regulation"  # regular time only (e.g. 90 minutes, 60 minutes)
    UNKNOWN = "unknown"


class ScenarioKind(StrEnum):
    REGULAR = "regular"
    EXCEPTIONAL = "exceptional"


class SettlementPolicy(StrEnum):
    """How a leg settles in a given scenario."""

    WIN = "win"
    LOSE = "lose"
    REFUND = "refund"  # stake / entry notional returned, fees are NOT returned
    HALF = "half"  # prediction contract resolves at 0.5 ("50-50")
    NO_WINS = "no_wins"  # binary contract resolves "No": Yes side loses, No side wins
    CARRY = "carry"  # position stays open until the rescheduled game is played
    UNKNOWN = "unknown"


class MappingStatus(StrEnum):
    PENDING = "pending"  # proposed automatically, waiting for admin
    NEEDS_REVIEW = "needs_review"  # automatic checks found something the admin must decide
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"  # rules or key parameters changed after approval


class Verdict(StrEnum):
    SIGNAL = "signal"
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class SolveStatus(StrEnum):
    OK = "ok"
    NO_PLAN = "no_plan"
    SOLVER_LIMIT = "solver_limit"
    UNSUPPORTED = "unsupported"


class Route(StrEnum):
    PREDICTION_PREDICTION = "prediction_prediction"
    PREDICTION_SPORTSBOOK = "prediction_sportsbook"
    SPORTSBOOK_SPORTSBOOK = "sportsbook_sportsbook"


class OpportunityStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"
