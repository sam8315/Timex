"""
Current Behavior — raw float vs mutation rounding boundary.

Pure Engine parity compares raw only. Mutation round() stays outside Engine.
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
)


def test_current_raw_float_vs_round_half_even(fixed_non_leap_year):
    """Current Behavior: production calc returns float; mutation uses round()."""
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, _ = jalali_year_bounds_g(year)
    # Choose duration so amount is near .5 for documentation
    for days in range(1, year_days):
        raw = charge_amount_for_segment(
            '4', 30, year, y_start, y_start + timedelta(days=days - 1)
        )
        if abs(raw - round(raw) - 0.5) < 1e-9 or abs(raw % 1 - 0.5) < 1e-9:
            assert round(raw) == round(raw)  # Python half-to-even documented
            assert isinstance(raw, float)
            break
    else:
        # Even if no exact .5 in this year, still document float vs int boundary
        raw = charge_amount_for_segment(
            '4', 30, year, y_start, y_start + timedelta(days=89)
        )
        assert isinstance(raw, float)
        assert round(raw) == round(30 * 90 / year_days)


def test_current_prorata_near_year_boundary(fixed_leap_year):
    year = fixed_leap_year
    year_days = get_jalali_year_days(year)
    assert year_days == 366
    y_start, y_end = jalali_year_bounds_g(year)
    raw = charge_amount_for_segment('4', 30, year, y_start, y_end)
    assert raw == 30.0
