"""
Current Behavior — contractual (membership 4) coverage and charge math.

Does NOT assert Target Rules (e.g. Target base 26, apply_region default false,
union of overlapping contracts — mismatches #1, #2, #3).
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
    split_contract_coverage_by_year,
)
from tests.characterization.conftest import make_contract


def test_current_contractual_full_year(fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    assert charge_amount_for_segment('4', 30, year, y_start, y_end) == 30.0


def test_current_contractual_midyear_start(fixed_non_leap_year):
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=100)
    amount = charge_amount_for_segment('4', 30, year, mid, y_end)
    days = (y_end - mid).days + 1
    assert amount == 30.0 * days / year_days


def test_current_contractual_midyear_end(fixed_non_leap_year):
    """Current Behavior: contractual midyear end is Prorata (honors end_date)."""
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=89)
    amount = charge_amount_for_segment('4', 30, year, y_start, end)
    duration = (end - y_start).days + 1
    # Match production expression associativity: annual * (duration / year_days)
    assert amount == 30.0 * (duration / year_days)


def test_current_contractual_open_clamped_to_year_end(current_jalali_year):
    """Current Behavior: open contractual → segment end = Jalali year end."""
    year = current_jalali_year
    y_start, y_end = jalali_year_bounds_g(year)
    segs = split_contract_coverage_by_year(
        make_contract('x', '4', y_start, end=None, annual=30)
    )
    assert len(segs) == 1
    assert segs[0][2] == y_end


def test_current_contractual_gap_no_charge_in_gap(fixed_non_leap_year):
    """
    Current Behavior: two sequential contracts do not invent coverage in the gap;
    each segment is charged independently (no union engine).
    """
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, y_end = jalali_year_bounds_g(year)
    first_end = y_start + timedelta(days=29)
    second_start = y_start + timedelta(days=60)
    a1 = charge_amount_for_segment('4', 30, year, y_start, first_end)
    a2 = charge_amount_for_segment('4', 30, year, second_start, y_end)
    gap_days = (second_start - first_end).days - 1
    assert gap_days > 0
    d1 = (first_end - y_start).days + 1
    d2 = (y_end - second_start).days + 1
    assert a1 == 30.0 * (d1 / year_days)
    assert a2 == 30.0 * (d2 / year_days)
    assert a1 + a2 == 30.0 * (d1 / year_days) + 30.0 * (d2 / year_days)
