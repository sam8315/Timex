"""
Tests for membership-aware leave entitlement charging.
"""
from datetime import timedelta
from typing import Dict, Optional

import jdatetime

from models.contract import Contract
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_buyback_quota import LeaveBuybackQuota
from models.policy import Policy, PolicyValue
from models.region import Region
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    charge_amount_for_segment,
    get_jalali_year_days,
    get_membership_timeline,
    jalali_year_bounds_g,
    resolve_annual_leave_days,
    resolve_max_buyback,
    split_contract_coverage_by_year,
)
from web.services.leave_service import (
    calculate_prorated_leave_by_year,
    charge_leave_for_new_contract,
    consume_leave,
    get_available_leave,
)
from web.services.hr_leave_import_service import import_hr_opening_line


def _seed_leave_policy(db, dept_annual: Dict[str, int], region_applies: Optional[Dict[str, bool]] = None):
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(category='leave', name='سیاست مرخصی تست', is_active=True)
        db.add(policy)
        db.flush()
    for code, annual in dept_annual.items():
        existing = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == f'annual_leave_dept_{code}',
            PolicyValue.region_code.is_(None),
        ).first()
        if existing:
            existing.parameter_value = str(annual)
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                parameter_key=f'annual_leave_dept_{code}',
                parameter_value=str(annual),
            ))
        applies = True if region_applies is None else region_applies.get(code, True)
        flag = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == f'region_applies_dept_{code}',
            PolicyValue.region_code.is_(None),
        ).first()
        if flag:
            flag.parameter_value = 'true' if applies else 'false'
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                parameter_key=f'region_applies_dept_{code}',
                parameter_value='true' if applies else 'false',
            ))
    db.commit()
    return policy


def _make_contract(user_id, type_code, start, end=None, annual=30, sick=0, deduction=0):
    return Contract(
        user_id=user_id,
        contract_type_code=type_code,
        start_date=start,
        end_date=end,
        annual_leave_days=annual,
        sick_leave_days=sick,
        service_deduction_days=deduction,
    )


class TestPolicyResolve:
    def test_resolve_from_policy_without_region(self, db, make_user):
        make_user(department="1")
        _seed_leave_policy(db, {'1': 33, '4': 28}, region_applies={'1': False, '4': False})
        assert resolve_annual_leave_days(db, '1', region_code='NORMAL') == 33
        assert resolve_annual_leave_days(db, '4', region_code='NORMAL') == 28

    def test_resolve_uses_region_when_flag_on(self, db, make_user):
        make_user(department="1", region_code="GRADE_2")
        db.query(Region).filter(Region.code == 'GRADE_2').update(
            {'default_annual_leave_days': 40}
        )
        db.commit()
        policy = _seed_leave_policy(db, {'1': 35}, region_applies={'1': True})
        # هم‌خوان با پنل مناطق: مقدار scoped هم به‌روز شود
        scoped = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == 'annual_leave_days',
            PolicyValue.region_code == 'GRADE_2',
        ).first()
        if scoped:
            scoped.parameter_value = '40'
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                parameter_key='annual_leave_days',
                parameter_value='40',
                region_code='GRADE_2',
            ))
        db.commit()
        assert resolve_annual_leave_days(db, '1', region_code='GRADE_2') == 40

    def test_resolve_uses_region_when_flag_missing(self, db, make_user):
        """UI پیش‌فرض اعمال منطقه است؛ flag غایب نباید منطقه را حذف کند."""
        make_user(department="2", region_code="GRADE_2")
        db.query(Region).filter(Region.code == 'GRADE_2').update(
            {'default_annual_leave_days': 40}
        )
        db.commit()
        policy = _seed_leave_policy(db, {'2': 30}, region_applies={'2': True})
        # حذف flag تا پیش‌فرض (اعمال) فعال شود
        db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == 'region_applies_dept_2',
        ).delete(synchronize_session=False)
        scoped = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == 'annual_leave_days',
            PolicyValue.region_code == 'GRADE_2',
        ).first()
        if scoped:
            scoped.parameter_value = '40'
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                parameter_key='annual_leave_days',
                parameter_value='40',
                region_code='GRADE_2',
            ))
        db.commit()
        assert resolve_annual_leave_days(db, '2', region_code='GRADE_2') == 40

    def test_resolve_skips_region_when_flag_explicitly_false(self, db, make_user):
        make_user(department="2", region_code="GRADE_2")
        _seed_leave_policy(db, {'2': 30}, region_applies={'2': False})
        assert resolve_annual_leave_days(db, '2', region_code='GRADE_2') == 30


class TestMembershipChargeRules:
    def test_permanent_open_charges_full_start_year(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_leave_policy(db, {'1': 35}, region_applies={'1': False})
        year = jdatetime.date.today().year
        start_g = jalali_year_bounds_g(year)[0]
        # Replace fixture contract so dates match current year start
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        c = _make_contract(user["user_id"], '1', start_g, end=None, annual=35)
        db.add(c)
        db.commit()
        db.refresh(c)

        result = calculate_entitlement_by_year(db, c, annual_override=35)
        assert year in result
        assert round(result[year]['AL']) == 35

    def test_permanent_midyear_start_is_prorated(self):
        year = 1404
        year_days = get_jalali_year_days(year)
        y_start, y_end = jalali_year_bounds_g(year)
        mid = y_start + timedelta(days=year_days // 2)
        amount = charge_amount_for_segment('1', 35, year, mid, y_end)
        expected_days = (y_end - mid).days + 1
        assert abs(amount - 35 * expected_days / year_days) < 0.01

    def test_permanent_split_ignores_early_end(self):
        year = jdatetime.date.today().year
        y_start, y_end = jalali_year_bounds_g(year)
        segs = split_contract_coverage_by_year(
            _make_contract('x', '1', y_start, end=y_start + timedelta(days=30), annual=35)
        )
        assert len(segs) == 1
        assert segs[0][0] == year
        assert segs[0][2] == y_end

    def test_permanent_past_hire_charges_current_year_only(self, db, make_user):
        """رسمی با استخدام قدیمی: فقط AL سال جاری شارژ می‌شود، بدون SL."""
        from web.routes.admin_contracts import add_years

        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
        year = jdatetime.date.today().year
        past_start, _ = jalali_year_bounds_g(year - 5)
        end = add_years(past_start, 30)

        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        c = _make_contract(user["user_id"], '1', past_start, end=end, annual=30, sick=120)
        db.add(c)
        db.commit()
        db.refresh(c)

        result = calculate_entitlement_by_year(db, c, annual_override=30)
        assert list(result.keys()) == [year]
        assert round(result[year]['AL']) == 30
        assert result[year]['SL'] == 0.0

        charged = charge_leave_for_new_contract(db, c)
        assert list(charged.keys()) == [year]
        assert charged[year].get('AL') == 30
        assert 'SL' not in charged[year]
        sl_bal = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='SL'
        ).first()
        assert sl_bal is None or sl_bal.balance == 0

    def test_no_sl_charged_even_when_sick_days_set(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        c = _make_contract(user["user_id"], '1', y_start, end=None, annual=30, sick=120)
        db.add(c)
        db.commit()
        db.refresh(c)

        charged = charge_leave_for_new_contract(db, c)
        assert charged[year]['AL'] == 30
        assert 'SL' not in charged.get(year, {})
        assert db.query(LeaveTransaction).filter_by(
            user_id=user["user_id"], leave_type='SL', transaction_type='CHARGE'
        ).count() == 0

    def test_contractual_three_months_approx_quarter(self, db, make_user):
        user = make_user(department="4", balance_al=None)
        _seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        end = y_start + timedelta(days=89)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        c = _make_contract(user["user_id"], '4', y_start, end=end, annual=30)
        db.add(c)
        db.commit()
        db.refresh(c)

        result = calculate_prorated_leave_by_year(c, db=db, annual_override=30)
        year_days = get_jalali_year_days(year)
        expected = round(30 * 90 / year_days)
        assert round(result[year]['AL']) == expected

    def test_conscript_uses_service_deduction(self, db, make_user):
        user = make_user(department="2", balance_al=None, contract_type_code="2")
        _seed_leave_policy(db, {'2': 35}, region_applies={'2': False})
        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        end = y_start + timedelta(days=364)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        c = _make_contract(
            user["user_id"], '2', y_start, end=end, annual=35, deduction=30
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        segs = split_contract_coverage_by_year(c)
        assert segs[0][2] == c.actual_end_date
        result = calculate_entitlement_by_year(db, c, annual_override=35)
        year_days = get_jalali_year_days(year)
        duration = (c.actual_end_date - y_start).days + 1
        assert round(result[year]['AL']) == round(35 * duration / year_days)


class TestChargeAndSync:
    def test_charge_updates_balance_and_department(self, db, make_user):
        user = make_user(department="3", balance_al=None, contract_type_code="3")
        _seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
        year = jdatetime.date.today().year
        y_start, _ = jalali_year_bounds_g(year)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        c = _make_contract(user["user_id"], '4', y_start, end=None, annual=30)
        db.add(c)
        db.commit()
        db.refresh(c)

        charged = charge_leave_for_new_contract(db, c)
        assert year in charged
        assert charged[year]['AL'] == 30

        bal = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='AL'
        ).first()
        assert bal is not None and bal.balance == 30

        emp = db.query(Employee).filter_by(user_id=user["user_id"]).first()
        assert emp.department == '4'

    def test_membership_timeline_order(self, db, make_user):
        user = make_user(department="1", balance_al=None)
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        y = jdatetime.date.today().year
        s1, _ = jalali_year_bounds_g(y - 2)
        s2, _ = jalali_year_bounds_g(y - 1)
        s3, _ = jalali_year_bounds_g(y)
        db.add(_make_contract(user["user_id"], '2', s1, end=s2 - timedelta(days=1), annual=35))
        db.add(_make_contract(user["user_id"], '4', s2, end=s3 - timedelta(days=1), annual=30))
        db.add(_make_contract(user["user_id"], '1', s3, end=None, annual=35))
        db.commit()

        timeline = get_membership_timeline(db, user["user_id"])
        assert [t['contract_type_code'] for t in timeline] == ['2', '4', '1']


def _ensure_leave_policy(db) -> Policy:
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(category='leave', name='leave', is_active=True)
        db.add(policy)
        db.flush()
    return policy


def _set_policy_value(db, policy_id: int, key: str, value: str, region_code=None):
    q = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy_id,
        PolicyValue.parameter_key == key,
    )
    if region_code is None:
        q = q.filter(PolicyValue.region_code.is_(None))
    else:
        q = q.filter(PolicyValue.region_code == region_code)
    existing = q.first()
    if existing:
        existing.parameter_value = value
    else:
        db.add(PolicyValue(
            policy_id=policy_id,
            parameter_key=key,
            parameter_value=value,
            region_code=region_code,
        ))


class TestArticle11Buyback:
    def test_permanent_normal_modern_cap_15(self, db, make_user):
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_cap', '15', region_code='NORMAL')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1404) == 15

    def test_permanent_grade1_legacy_maps_to_normal(self, db, make_user):
        """کد قدیمی GRADE_1 برای سقف بازخرید مثل عادی رفتار می‌کند."""
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_cap', '15', region_code='NORMAL')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='GRADE_1', year_j=1404) == 15

    def test_permanent_grade4_modern_cap_22(self, db, make_user):
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_cap', '22', region_code='GRADE_4')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='GRADE_4', year_j=1404) == 22

    def test_permanent_historical_1395_cap_15(self, db, make_user):
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_era_1390_1398_cap', '15')
        _set_policy_value(db, policy.id, 'buyback_era_modern_from_year', '1399')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1395) == 15

    def test_permanent_grade4_exception_cap_25(self, db, make_user):
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_era_1390_1398_cap', '15')
        _set_policy_value(db, policy.id, 'buyback_era_grade4_from', '1391/07/15')
        _set_policy_value(db, policy.id, 'buyback_era_grade4_cap', '25')
        _set_policy_value(db, policy.id, 'buyback_era_modern_from_year', '1399')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='GRADE_4', year_j=1395) == 25

    def test_contractual_buyback_none_returns_none(self, db, make_user):
        make_user(department="4", balance_al=None, contract_type_code="4")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'buyback_dept_4', 'none')
        db.commit()
        assert resolve_max_buyback(db, '4', year_j=1404) is None

    def test_permanent_region_overrides_buyback_dept(self, db, make_user):
        make_user(department="1", balance_al=None, contract_type_code="1")
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_dept_1', '9')
        _set_policy_value(db, policy.id, 'buyback_cap', '18', region_code='GRADE_2')
        db.commit()
        assert resolve_max_buyback(db, '1', region_code='GRADE_2', year_j=1404) == 18


class TestConsumeLeavePriority:
    def test_permanent_cw_over_cap_uses_non_buyback_first(self, db, make_user):
        """رسمی: CW بالای سقف منطقه → اول non-buyback، بعد AL، بعد buyback CW."""
        user = make_user(
            department="1",
            balance_al=None,
            contract_type_code="1",
            region_code="NORMAL",
        )
        year = jdatetime.date.today().year
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'region_applies_dept_1', 'true')
        _set_policy_value(db, policy.id, 'buyback_cap', '15', region_code='NORMAL')

        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.add(LeaveBalance(user_id=user["user_id"], year=year, leave_type='CW', balance=40))
        db.add(LeaveBalance(user_id=user["user_id"], year=year, leave_type='AL', balance=10))
        db.commit()

        avail = get_available_leave(db, user["user_id"], year, 'AL')
        assert avail['total'] == 50
        assert avail['breakdown']['CW_NON_BUYBACK'] == 25
        assert avail['breakdown']['CW_BUYBACK'] == 15
        assert avail['breakdown']['AL'] == 10

        # 30 روز: 25 از non-buyback CW + 5 از AL
        res = consume_leave(db, user["user_id"], year, 30, 'AL')
        assert res['success']
        assert res['consumed_from']['CW'] == 25
        assert res['consumed_from']['AL'] == 5

        cw = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='CW'
        ).first()
        al = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='AL'
        ).first()
        assert cw.balance == 15
        assert al.balance == 5

        # ادامه: تمام AL سپس buyback CW
        res2 = consume_leave(db, user["user_id"], year, 10, 'AL')
        assert res2['success']
        assert res2['consumed_from'].get('AL', 0) == 5
        assert res2['consumed_from'].get('CW', 0) == 5
        assert cw.balance == 10
        assert al.balance == 0

    def test_contractual_all_cw_buybackable_uses_al_first(self, db, make_user):
        """قراردادی: همه CW قابل‌بازخرید → اول AL، بعد CW."""
        user = make_user(department="4", balance_al=None, contract_type_code="4")
        year = jdatetime.date.today().year
        policy = _ensure_leave_policy(db)
        _set_policy_value(db, policy.id, 'buyback_dept_4', 'none')

        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.add(LeaveBalance(user_id=user["user_id"], year=year, leave_type='CW', balance=9))
        db.add(LeaveBalance(user_id=user["user_id"], year=year, leave_type='AL', balance=10))
        db.commit()

        avail = get_available_leave(db, user["user_id"], year, 'AL')
        assert avail['breakdown']['CW_NON_BUYBACK'] == 0
        assert avail['breakdown']['CW_BUYBACK'] == 9

        res = consume_leave(db, user["user_id"], year, 7, 'AL')
        assert res['success']
        assert res['consumed_from'].get('AL') == 7
        assert 'CW' not in res['consumed_from']

        cw = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='CW'
        ).first()
        al = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='AL'
        ).first()
        assert cw.balance == 9
        assert al.balance == 3

        res2 = consume_leave(db, user["user_id"], year, 5, 'AL')
        assert res2['success']
        assert res2['consumed_from'].get('AL') == 3
        assert res2['consumed_from'].get('CW') == 2
        assert al.balance == 0
        assert cw.balance == 7


class TestHrImport:
    def test_hr_import_permanent_fields(self, db, make_user):
        user = make_user(department="1", balance_al=None)
        year = 1405
        out = import_hr_opening_line(
            db,
            user_id=user["user_id"],
            year=year,
            stored_days=20,
            buyback_days=5,
            burned_days=0,
            admin_name="tester",
        )
        db.commit()
        assert out['success']

        cw = db.query(LeaveBalance).filter_by(
            user_id=user["user_id"], year=year, leave_type='CW'
        ).first()
        assert cw and cw.balance == 20

        bb = db.query(LeaveBuybackQuota).filter_by(
            user_id=user["user_id"], year=year
        ).first()
        assert bb and bb.days == 5

    def test_hr_import_contractual_with_burn(self, db, make_user):
        user = make_user(department="4", balance_al=None)
        year = 1405
        out = import_hr_opening_line(
            db,
            user_id=user["user_id"],
            year=year,
            stored_days=9,
            buyback_days=3,
            burned_days=6,
            admin_name="tester",
        )
        db.commit()
        assert out['success']

        burns = db.query(LeaveTransaction).filter_by(
            user_id=user["user_id"], year=year, transaction_type='BURN'
        ).all()
        assert len(burns) == 1
        assert burns[0].amount == 6
