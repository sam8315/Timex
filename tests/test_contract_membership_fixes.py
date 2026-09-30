"""
Tests for contract/membership bugfixes: overlap, policy charge, permanent +30y, CW stored.
"""
from datetime import timedelta

import jdatetime
import pytest

from models.contract import Contract, CONTRACT_TYPES
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.policy import Policy, PolicyValue
from web.services.leave_entitlement_service import (
    add_years,
    find_overlapping_contract,
    jalali_year_bounds_g,
    resolve_annual_leave_days,
    split_contract_coverage_by_year,
    sync_employee_department_from_active_contract,
    calculate_entitlement_by_year,
)
from web.services.leave_service import (
    charge_leave_for_new_contract,
    get_stored_leave_balance,
    set_stored_leave_for_year,
)


def _seed_policy(db, dept_annual, region_applies=None):
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(category='leave', name='test leave', is_active=True)
        db.add(policy)
        db.flush()
    for code, annual in dept_annual.items():
        key = f'annual_leave_dept_{code}'
        existing = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == key,
            PolicyValue.region_code.is_(None),
        ).first()
        if existing:
            existing.parameter_value = str(annual)
        else:
            db.add(PolicyValue(
                policy_id=policy.id, parameter_key=key, parameter_value=str(annual)
            ))
        applies = (region_applies or {}).get(code)
        if applies is not None:
            fkey = f'region_applies_dept_{code}'
            flag = db.query(PolicyValue).filter(
                PolicyValue.policy_id == policy.id,
                PolicyValue.parameter_key == fkey,
                PolicyValue.region_code.is_(None),
            ).first()
            val = 'true' if applies else 'false'
            if flag:
                flag.parameter_value = val
            else:
                db.add(PolicyValue(
                    policy_id=policy.id, parameter_key=fkey, parameter_value=val
                ))
    db.commit()
    return policy


def _contract(user_id, code, start, end=None, annual=30, deduction=0):
    return Contract(
        user_id=user_id,
        contract_type_code=code,
        start_date=start,
        end_date=end,
        annual_leave_days=annual,
        sick_leave_days=0,
        service_deduction_days=deduction,
    )


class TestOverlap:
    def test_overlapping_ranges_detected(self, db, make_user):
        user = make_user(department="4", balance_al=None)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        y = jdatetime.date.today().year
        s, _ = jalali_year_bounds_g(y)
        e = s + timedelta(days=100)
        db.add(_contract(user["user_id"], '4', s, e))
        db.commit()

        hit = find_overlapping_contract(
            db, user["user_id"], s + timedelta(days=50), e + timedelta(days=50)
        )
        assert hit is not None

    def test_non_overlapping_ok(self, db, make_user):
        user = make_user(department="4", balance_al=None)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        y = jdatetime.date.today().year
        s, _ = jalali_year_bounds_g(y)
        e = s + timedelta(days=30)
        db.add(_contract(user["user_id"], '4', s, e))
        db.commit()

        hit = find_overlapping_contract(
            db, user["user_id"], e + timedelta(days=1), e + timedelta(days=60)
        )
        assert hit is None


class TestPolicyCharge:
    def test_conscript_uses_policy_30_not_contract_types_35(self, db, make_user):
        user = make_user(department="2", balance_al=None, contract_type_code="2")
        _seed_policy(db, {'2': 30}, region_applies={'2': False})
        assert resolve_annual_leave_days(db, '2', region_code='NORMAL') == 30
        assert CONTRACT_TYPES['2']['annual_leave'] == 30

        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        end = y_start + timedelta(days=get_year_days(year) - 1)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        c = _contract(user["user_id"], '2', y_start, end, annual=30)
        db.add(c)
        db.commit()
        db.refresh(c)

        charged = charge_leave_for_new_contract(db, c)
        assert charged[year]['AL'] == 30


def get_year_days(year):
    from web.services.leave_entitlement_service import get_jalali_year_days
    return get_jalali_year_days(year)


class TestPermanent:
    def test_add_years_helper(self):
        from datetime import date as d
        assert add_years(d(2020, 3, 1), 30) == d(2050, 3, 1)
        assert add_years(d(2020, 2, 29), 30).year == 2050

    def test_permanent_long_end_charges_only_start_year(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_policy(db, {'1': 30}, region_applies={'1': False})
        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        end = add_years(y_start, 30)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        c = _contract(user["user_id"], '1', y_start, end, annual=30)
        db.add(c)
        db.commit()
        db.refresh(c)

        segs = split_contract_coverage_by_year(c)
        assert len(segs) == 1
        assert segs[0][0] == year

        result = calculate_entitlement_by_year(db, c, annual_override=30)
        assert list(result.keys()) == [year]
        assert round(result[year]['AL']) == 30


class TestStoredLeave:
    def test_set_stored_on_create_and_edit(self, db, make_user):
        user = make_user(department="1", balance_al=None)
        year = jdatetime.date.today().year
        r1 = set_stored_leave_for_year(
            db, user_id=user["user_id"], year=year, target_days=10, reference_id=1
        )
        assert r1['new'] == 10
        assert get_stored_leave_balance(db, user["user_id"], year) == 10

        r2 = set_stored_leave_for_year(
            db, user_id=user["user_id"], year=year, target_days=15, reference_id=1
        )
        assert r2['diff'] == 5
        assert get_stored_leave_balance(db, user["user_id"], year) == 15


class TestDepartmentSync:
    def test_sync_from_latest_membership(self, db, make_user):
        user = make_user(department="3", balance_al=None)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        y = jdatetime.date.today().year
        s1, _ = jalali_year_bounds_g(y - 1)
        s2, _ = jalali_year_bounds_g(y)
        db.add(_contract(user["user_id"], '2', s1, s2 - timedelta(days=1)))
        db.add(_contract(user["user_id"], '1', s2, add_years(s2, 30)))
        db.commit()

        dept = sync_employee_department_from_active_contract(db, user["user_id"], commit=True)
        assert dept == '1'
        emp = db.query(Employee).filter_by(user_id=user["user_id"]).first()
        assert emp.department == '1'
