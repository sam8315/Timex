"""
Current Behavior — physician (membership 5).

Current Behavior math matches contractual prorata (mismatch #11 vs any future
physician-specific Target Rule is Spec-only).
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
)


def test_current_physician_full_year(fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    assert charge_amount_for_segment('5', 30, year, y_start, y_end) == 30.0


def test_current_physician_partial_year_prorata(fixed_non_leap_year):
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=99)
    amount = charge_amount_for_segment('5', 30, year, y_start, end)
    contractual = charge_amount_for_segment('4', 30, year, y_start, end)
    duration = (end - y_start).days + 1
    assert amount == 30.0 * (duration / year_days)
    assert amount == contractual
