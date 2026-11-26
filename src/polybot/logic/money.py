"""Decimal helpers. Money and prices are always Decimal, never float."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation

ZERO = Decimal(0)
ONE = Decimal(1)
CENT = Decimal("0.01")
BPS = Decimal("0.0001")


def dec(value: object) -> Decimal:
    """Convert a value coming from JSON/an API into Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal: {value!r}") from exc
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


def opt_dec(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return dec(value)


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    """Largest multiple of ``step`` that is <= value."""
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    """Smallest multiple of ``step`` that is >= value."""
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def round_display(value: Decimal, step: Decimal = CENT) -> Decimal:
    return value.quantize(step, rounding=ROUND_HALF_EVEN)


def fmt_money(value: Decimal, currency: str = "") -> str:
    q = round_display(value)
    s = f"{q:,.2f}".replace(",", " ")
    return f"{s} {currency}".strip()


def fmt_pct(value: Decimal) -> str:
    return f"{round_display(value * 100, Decimal('0.01'))}%"
