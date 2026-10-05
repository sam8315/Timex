"""
Current Behavior — permanent (membership 1) coverage and charge math.

Does NOT assert Target Rules (e.g. Target says midyear end Prorata;
Current Behavior ignores permanent end within year — mismatch #7).
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
    split_contract_coverage_by_year,
)
from tests.characterization.conftest import make_contract


def test_current_permanent_full_year_from_farvardin(fixed_non_leap_year):
    """Current Behavior: full-year permanent coverage → full annual."""
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    amount = charge_amount_for_segment('1', 30, year, y_start, y_end)
    assert amount == 30.0


def test_current_permanent_midyear_start_prorata(fixed_non_leap_year):
    """Current Behavior: midyear permanent start → prorata to year end."""
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=year_days // 2)
    amount = charge_amount_for_segment('1', 35, year, mid, y_end)
    expected_days = (y_end - mid).days + 1
    assert abs(amount - 35 * expected_days / year_days) < 1e-12


def test_current_permanent_midyear_end_ignored(current_jalali_year):
    """
    Current Behavior: permanent split ignores early end_date → segment to year end.

    Target Rule mismatch #7 (Target: midyear end Prorata) — not asserted here.
    """
    year = current_jalali_year
    y_start, y_end = jalali_year_bounds_g(year)
    segs = split_contract_coverage_by_year(
        make_contract('x', '1', y_start, end=y_start + timedelta(days=30), annual=30)
    )
    assert len(segs) == 1
    assert segs[0][0] == year
    assert segs[0][2] == y_end


def test_current_permanent_open_ended_full_year(fixed_non_leap_year):
    """Current Behavior: open permanent covering full year → full annual."""
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    amount = charge_amount_for_segment('1', 30, year, y_start, None)
    assert amount == 30.0


def test_current_permanent_zero_annual_base(fixed_non_leap_year):
    """Current Behavior: zero annual base → zero charge."""
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    assert charge_amount_for_segment('1', 0, year, y_start, y_end) == 0.0


def test_current_permanent_past_hire_current_year_only(db, make_user, current_jalali_year):
    """Current Behavior: old permanent hire → split/charge only current Jalali year."""
    from web.routes.admin_contracts import add_years
    from web.services.leave_entitlement_service import calculate_entitlement_by_year
    from tests.characterization.conftest import seed_leave_policy, clear_user_contracts

    user = make_user(department='1', balance_al=None, contract_type_code='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
    year = current_jalali_year
    past_start, _ = jalali_year_bounds_g(year - 5)
    end = add_years(past_start, 30)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', past_start, end=end, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    result = calculate_entitlement_by_year(db, c, annual_override=30)
    assert list(result.keys()) == [year]
    assert round(result[year]['AL']) == 30
