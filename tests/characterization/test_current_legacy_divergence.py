"""
Current Behavior — legacy entitlement paths diverge from Path B.

Documents Path G (Contract.prorated_annual_leave) divergence.
Does not delete or refactor legacy code (mismatch #15).
"""
from datetime import timedelta

from models.contract import Contract
from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
)


def test_current_legacy_model_prorata_uses_gregorian_365_int(fixed_non_leap_year):
    """
    Current Behavior Path G: Gregorian elapsed/365 with int().
    Path B: Jalali year_days float raw via charge_amount_for_segment.
    """
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=90)
    c = Contract(
        user_id='legacy',
        contract_type_code='4',
        start_date=mid,
        end_date=y_end,
        annual_leave_days=30,
        sick_leave_days=0,
        service_deduction_days=0,
    )
    segment_raw = charge_amount_for_segment('4', 30, year, mid, y_end)
    legacy = c.prorated_annual_leave
    assert isinstance(legacy, int)
    assert isinstance(segment_raw, float)
    assert get_jalali_year_days(year) == 365
    # Formulas differ (Jalali float vs Gregorian/365 int); values need not match.
    assert segment_raw == 30.0 * ((y_end - mid).days + 1) / 365
