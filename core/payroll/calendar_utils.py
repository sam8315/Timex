"""بازه ماه شمسی برای حقوق."""
from __future__ import annotations

from datetime import date, timedelta

import jdatetime


def month_day_count(year_j: int, month_j: int) -> int:
    """تعداد روزهای ماه شمسی (۲۹–۳۱)."""
    if month_j == 12:
        # اسفند: ۲۹ یا ۳۰ بسته به کبیسه
        try:
            jdatetime.date(year_j, 12, 30)
            return 30
        except ValueError:
            return 29
    if 1 <= month_j <= 6:
        return 31
    return 30


def jalali_month_bounds(year_j: int, month_j: int) -> tuple[date, date]:
    """ابتدا و انتهای ماه شمسی به میلادی (شامل هر دو روز)."""
    start_j = jdatetime.date(year_j, month_j, 1)
    days = month_day_count(year_j, month_j)
    end_j = jdatetime.date(year_j, month_j, days)
    return start_j.togregorian(), end_j.togregorian()


def iter_days(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
