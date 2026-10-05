"""
Jalali calendar helpers for the Pure Entitlement Engine.

Independent copy of Current Behavior from leave_entitlement_service
(get_jalali_year_days / jalali_year_bounds_g). No DB. No date.today().
"""
from __future__ import annotations

from datetime import date
from typing import Tuple

import jdatetime


def get_jalali_year_days(year: int) -> int:
    try:
        jdatetime.date(year, 12, 30)
        return 366
    except ValueError:
        return 365


def jalali_year_bounds_g(year: int) -> Tuple[date, date]:
    start_j = jdatetime.date(year, 1, 1)
    try:
        end_j = jdatetime.date(year, 12, 30)
    except ValueError:
        end_j = jdatetime.date(year, 12, 29)
    return start_j.togregorian(), end_j.togregorian()
