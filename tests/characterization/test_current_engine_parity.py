"""
Current Behavior parity — Pure Engine raw == charge_amount_for_segment raw.

Locked Phase 1 definition:
  compute_annual_entitlement(...).raw_amount
  == charge_amount_for_segment(membership_code, annual_days, year_j, seg_start, seg_end)
"""
from datetime import timedelta

import pytest

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_engine.engine import (
    build_context_for_segment,
    compute_annual_entitlement,
)


@pytest.mark.parametrize('membership_code', ['1', '2', '3', '4', '5', '6', '7'])
@pytest.mark.parametrize('annual_days', [0, 26, 30, 35])
def test_current_engine_parity_full_year(
    membership_code, annual_days, fixed_non_leap_year
):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    expected = charge_amount_for_segment(
        membership_code, annual_days, year, y_start, y_end
    )
    ctx = build_context_for_segment(
        membership_code=membership_code,
        annual_days=annual_days,
        year_j=year,
        seg_start=y_start,
        seg_end=y_end,
    )
    assert compute_annual_entitlement(ctx).raw_amount == expected


@pytest.mark.parametrize('membership_code', ['1', '2', '4', '5'])
def test_current_engine_parity_midyear_start(membership_code, fixed_leap_year):
    year = fixed_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=120)
    expected = charge_amount_for_segment(membership_code, 30, year, mid, y_end)
    ctx = build_context_for_segment(
        membership_code=membership_code,
        annual_days=30,
        year_j=year,
        seg_start=mid,
        seg_end=y_end,
    )
    assert compute_annual_entitlement(ctx).raw_amount == expected


@pytest.mark.parametrize('membership_code', ['2', '3', '4', '5'])
def test_current_engine_parity_midyear_end(membership_code, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=89)
    expected = charge_amount_for_segment(membership_code, 30, year, y_start, end)
    ctx = build_context_for_segment(
        membership_code=membership_code,
        annual_days=30,
        year_j=year,
        seg_start=y_start,
        seg_end=end,
    )
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_current_engine_parity_open_ended_none_seg_end(fixed_non_leap_year):
    """Current Behavior: seg_end=None clamps to year end in both paths."""
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    expected = charge_amount_for_segment('1', 30, year, y_start, None)
    ctx = build_context_for_segment(
        membership_code='1',
        annual_days=30,
        year_j=year,
        seg_start=y_start,
        seg_end=None,
    )
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_current_engine_parity_empty_coverage(fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    # segment entirely after year end → 0
    seg_start = y_end + timedelta(days=1)
    expected = charge_amount_for_segment('4', 30, year, seg_start, seg_start + timedelta(days=5))
    ctx = build_context_for_segment(
        membership_code='4',
        annual_days=30,
        year_j=year,
        seg_start=seg_start,
        seg_end=seg_start + timedelta(days=5),
    )
    assert expected == 0.0
    assert compute_annual_entitlement(ctx).raw_amount == expected
