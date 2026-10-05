"""Phase 2 Resolver — coverage / membership Current Behavior."""
from __future__ import annotations

from datetime import timedelta

from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from web.services.leave_entitlement_engine import compute_annual_entitlement
from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    get_jalali_year_days,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_resolver import (
    coverage_for_contract_year,
    resolve_annual_leave_context_for_contract,
    resolve_annual_leave_contexts,
)
from tests.resolver.conftest import (
    FIXED_AS_OF,
    clear_user_contracts,
    make_contract,
    prepare_live_membership,
    seed_leave_policy,
)


def test_resolver_permanent_full_year(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '1', 30, y_start)
    seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.membership_code == '1'
    assert ctx.coverage.start == y_start
    assert ctx.coverage.end == y_end
    assert ctx.annual_days == 30.0
    result = compute_annual_entitlement(ctx)
    assert result.raw_amount == charge_amount_for_segment(
        '1', 30, year, y_start, y_end
    )


def test_resolver_permanent_midyear_start(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=year_days // 2)
    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '1', 35, mid)
    seed_leave_policy(db, {'1': 35}, region_applies={'1': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', mid, end=None, annual=35)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.coverage.start == mid
    assert ctx.coverage.end == y_end
    expected = charge_amount_for_segment('1', 35, year, mid, y_end)
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_resolver_permanent_midyear_end_ignored(db, make_user, fixed_non_leap_year):
    """Current Behavior: permanent early end_date still covers to year end."""
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], '1', y_start, end=y_start + timedelta(days=30), annual=30
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    cov = coverage_for_contract_year(c, year, db=db)
    assert cov == (y_start, y_end)


def test_resolver_open_ended_to_year_end(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '4', 30, y_start)
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=None, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert ctx is not None
    assert ctx.coverage.end == y_end
    assert compute_annual_entitlement(ctx).raw_amount == 30.0


def test_resolver_contractual_partial_year(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=89)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '4', 30, y_start)
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=end, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.membership_code == '4'
    assert ctx.coverage.end == end
    expected = charge_amount_for_segment('4', 30, year, y_start, end)
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_resolver_purchase_service_partial_year(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=100)
    user = make_user(department='3', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '3', 30, mid)
    seed_leave_policy(db, {'3': 30}, region_applies={'3': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '3', mid, end=y_end, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.membership_code == '3'
    expected = charge_amount_for_segment('3', 30, year, mid, y_end)
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_resolver_conscript_service_deduction(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    year_days = get_jalali_year_days(year)
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=200)
    deduction = 20
    user = make_user(department='2', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '2', 35, y_start)
    seed_leave_policy(db, {'2': 35}, region_applies={'2': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], '2', y_start, end=end, annual=35, deduction=deduction
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert ctx is not None
    assert ctx.coverage.end == c.actual_end_date
    duration = (c.actual_end_date - y_start).days + 1
    expected = 35.0 * duration / year_days
    assert compute_annual_entitlement(ctx).raw_amount == expected


def test_resolver_zero_annual_base(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '4', 0, y_start)
    seed_leave_policy(db, {'4': 99}, region_applies={'4': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=y_end, annual=0)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.annual_days == 0.0
    assert compute_annual_entitlement(ctx).raw_amount == 0.0


def test_resolver_empty_coverage_future_contract(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    future_start = y_end + timedelta(days=1)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], '4', future_start, end=future_start + timedelta(days=30)
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    assert (
        resolve_annual_leave_context_for_contract(
            db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
        )
        is None
    )


def test_resolver_multi_contract_sequential(db, make_user, fixed_non_leap_year):
    """Current Behavior: sequential contracts → list of Contexts; no union."""
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '4', 30, y_start)
    prepare_live_membership(db, '3', 30, y_start)
    seed_leave_policy(
        db, {'4': 30, '3': 30}, region_applies={'4': False, '3': False}
    )
    clear_user_contracts(db, user['user_id'])

    c1 = make_contract(
        user['user_id'], '4', y_start, end=y_start + timedelta(days=89), annual=30
    )
    c2 = make_contract(
        user['user_id'],
        '3',
        y_start + timedelta(days=90),
        end=y_start + timedelta(days=179),
        annual=30,
    )
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    contexts = resolve_annual_leave_contexts(
        db, user['user_id'], year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert len(contexts) == 2
    assert contexts[0].membership_code == '4'
    assert contexts[1].membership_code == '3'

    total = sum(compute_annual_entitlement(ctx).raw_amount for ctx in contexts)
    expected = (
        charge_amount_for_segment(
            '4', 30, year, contexts[0].coverage.start, contexts[0].coverage.end
        )
        + charge_amount_for_segment(
            '3', 30, year, contexts[1].coverage.start, contexts[1].coverage.end
        )
    )
    assert total == expected


def test_resolver_no_side_effects(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '1', 30, y_start)
    seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=25)
    db.add(c)
    db.commit()
    db.refresh(c)

    from models.employee import Employee

    emp = db.query(Employee).filter(Employee.user_id == user['user_id']).first()
    emp_region_before = emp.region_code
    annual_before = c.annual_leave_days
    bal_before = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user['user_id'])
        .count()
    )
    tx_before = (
        db.query(LeaveTransaction)
        .filter(LeaveTransaction.user_id == user['user_id'])
        .count()
    )

    resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    db.refresh(c)
    emp = db.query(Employee).filter(Employee.user_id == user['user_id']).first()

    assert c.annual_leave_days == annual_before
    assert emp.region_code == emp_region_before
    assert (
        db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user['user_id'])
        .count()
        == bal_before
    )
    assert (
        db.query(LeaveTransaction)
        .filter(LeaveTransaction.user_id == user['user_id'])
        .count()
        == tx_before
    )
