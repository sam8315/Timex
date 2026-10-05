"""
Current Behavior — Jalali calendar helpers used by entitlement charging.

Does NOT assert Target Rules. See docs/leave_entitlement_target_spec.md.
"""
from web.services.leave_entitlement_service import (
    get_jalali_year_days,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_engine.calendar import (
    get_jalali_year_days as engine_get_jalali_year_days,
    jalali_year_bounds_g as engine_jalali_year_bounds_g,
)


def test_current_jalali_year_days_leap(fixed_leap_year):
    """Current Behavior: leap Jalali year has 366 days."""
    assert get_jalali_year_days(fixed_leap_year) == 366


def test_current_jalali_year_days_non_leap(fixed_non_leap_year):
    """Current Behavior: non-leap Jalali year has 365 days."""
    assert get_jalali_year_days(fixed_non_leap_year) == 365


def test_current_jalali_year_bounds_inclusive(fixed_non_leap_year):
    """Current Behavior: year bounds are Gregorian conversions of 1/1 .. 12/29|30."""
    y_start, y_end = jalali_year_bounds_g(fixed_non_leap_year)
    days = (y_end - y_start).days + 1
    assert days == get_jalali_year_days(fixed_non_leap_year)


def test_current_engine_calendar_matches_production(fixed_leap_year, fixed_non_leap_year):
    """Independent engine calendar must match production Current Behavior helpers."""
    for year in (fixed_leap_year, fixed_non_leap_year):
        assert engine_get_jalali_year_days(year) == get_jalali_year_days(year)
        assert engine_jalali_year_bounds_g(year) == jalali_year_bounds_g(year)
