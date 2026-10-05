"""
Current Behavior — conscript (membership 2).

Does NOT assert Target ServiceDurationPolicy / StartDatePolicy / bomi rules
(mismatches #8, #9). Those are Spec-only in Phase 1.
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
    split_contract_coverage_by_year,
)
from tests.characterization.conftest import make_contract


def test_current_conscript_full_year_without_deduction(fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    assert charge_amount_for_segment('2', 30, year, y_start, y_end) == 30.0


def test_current_conscript_service_deduction_shortens_actual_end(current_jalali_year):
    """Current Behavior: segment end follows Contract.actual_end_date."""
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=364)
    c = make_contract('x', '2', y_start, end=end, annual=35, deduction=30)
    segs = split_contract_coverage_by_year(c)
    assert segs[0][2] == c.actual_end_date
    assert c.actual_end_date == end - timedelta(days=30)


def test_current_conscript_midyear_with_deduction(fixed_non_leap_year):
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=200)
    deduction = 20
    actual_end = end - timedelta(days=deduction)
    amount = charge_amount_for_segment('2', 35, year, y_start, actual_end)
    duration = (actual_end - y_start).days + 1
    assert amount == 35.0 * duration / year_days


def test_current_conscript_calculated_service_end_drives_segment(current_jalali_year, db, make_user):
    """Current Behavior: calculate_entitlement uses actual_end_date for conscript."""
    from web.services.leave_entitlement_service import calculate_entitlement_by_year
    from tests.characterization.conftest import seed_leave_policy, clear_user_contracts

    user = make_user(department='2', balance_al=None, contract_type_code='2')
    seed_leave_policy(db, {'2': 35}, region_applies={'2': False})
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=364)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '2', y_start, end=end, annual=35, deduction=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    result = calculate_entitlement_by_year(db, c, annual_override=35)
    year_days = get_jalali_year_days(year)
    duration = (c.actual_end_date - y_start).days + 1
    assert round(result[year]['AL']) == round(35 * duration / year_days)
