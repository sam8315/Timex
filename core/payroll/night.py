"""فوق‌العاده شب‌کاری. درصد و نوع‌های حذف‌شده داخل موتور ثابت نیستند."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.payroll.money import D, money_round
from core.payroll.shift import (
    PATTERN_EVENING_NIGHT,
    PATTERN_MORNING_EVENING,
    PATTERN_MORNING_EVENING_NIGHT,
    PATTERN_MORNING_NIGHT,
    PATTERN_NIGHT_PAIR,
)

EXCLUDABLE_PATTERNS = (
    PATTERN_MORNING_EVENING,
    PATTERN_MORNING_EVENING_NIGHT,
    PATTERN_NIGHT_PAIR,
    PATTERN_MORNING_NIGHT,
    PATTERN_EVENING_NIGHT,
)

DEFAULT_EXCLUDED = (
    PATTERN_MORNING_EVENING,
    PATTERN_MORNING_EVENING_NIGHT,
    PATTERN_NIGHT_PAIR,
)


@dataclass(frozen=True)
class NightRule:
    premium_percent: Decimal = D("35")
    excluded_patterns: tuple[str, ...] = DEFAULT_EXCLUDED


def parse_excluded_patterns(raw: str | None) -> tuple[str, ...]:
    allowed = set(EXCLUDABLE_PATTERNS)
    seen: list[str] = []
    for part in str(raw or "").split(","):
        code = part.strip()
        if code in allowed and code not in seen:
            seen.append(code)
    return tuple(seen)


def night_premium(hourly: Decimal, hours: Decimal, percent: Decimal) -> Decimal:
    """۳۵ درصد مزد ساعتی برای هر ساعت شب. مزد عادی همان ساعت داخل حقوق روزانه است."""
    if D(hourly) <= 0 or D(hours) <= 0 or D(percent) <= 0:
        return D(0)
    return money_round(D(hourly) * D(percent) / D(100) * D(hours))
