"""کمک‌کارهای مبلغ و Decimal برای حقوق."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Number = Union[Decimal, int, float, str]


def D(value: Number | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Decimal, places: str = "0.0001") -> Decimal:
    return value.quantize(Decimal(places))


def money_round(value: Decimal, places: str = "1") -> Decimal:
    """گرد کردن نهایی مبلغ (پیش‌فرض ریال صحیح)."""
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
