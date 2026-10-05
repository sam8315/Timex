"""
Integration: DB facts → Resolver → AnnualLeaveContext → Pure Engine → EntitlementResult.

Deterministic: uses fixed Jalali years and explicit as_of_date (no real today).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from web.services.leave_entitlement_engine import (
    AnnualLeaveContext,
    EntitlementResult,
    compute_annual_entitlement,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    charge_amount_for_segment,
    jalali_year_bounds_g,
    split_contract_coverage_by_year,
)
from web.services.leave_entitlement_resolver import (
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


@pytest.mark.parametrize(
    'membership_code,annual,region_applies',
    [
        ('1', 30, False),
        ('2', 35, False),
        ('3', 30, False),
        ('4', 30, False),
    ],
)
def test_integration_db_resolver_engine_parity_full_year(
    db, make_user, fixed_non_leap_year, membership_code, annual, region_applies
):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(
        department=membership_code, region_code='NORMAL', balance_al=None
    )
    prepare_live_membership(db, membership_code, annual, y_start)
    seed_leave_policy(
        db,
        {membership_code: annual},
        region_applies={membership_code: region_applies},
    )
    clear_user_contracts(db, user['user_id'])
    end = None if membership_code == '1' else y_end
    c = make_contract(
        user['user_id'], membership_code, y_start, end=end, annual=annual
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert isinstance(ctx, AnnualLeaveContext)
    result = compute_annual_entitlement(ctx)
    assert isinstance(result, EntitlementResult)
    expected = charge_amount_for_segment(
        membership_code, annual, year, y_start, y_end
    )
    assert result.raw_amount == expected
    assert result.membership_code == membership_code
    assert result.year_j == year


def test_integration_snapshot_matches_charge_path_math(
    db, make_user, fixed_non_leap_year
):
    """
    Snapshot mode Context → Engine == charge_amount_for_segment with snapshot annual.

    Note: calculate_entitlement_by_year / split_contract_coverage_by_year still
    couple to today().year; when fixed year != current Jalali year we compare
    Engine to charge_amount_for_segment only (not production split).
    """
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=120)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=end, annual=26)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert ctx is not None
    assert ctx.annual_days == 26.0
    result = compute_annual_entitlement(ctx)
    expected = charge_amount_for_segment(
        '4', 26, year, ctx.coverage.start, ctx.coverage.end
    )
    assert result.raw_amount == expected


def test_integration_when_year_j_is_current_matches_calculate_entitlement(
    db, make_user, current_jalali_year
):
    """
    When year_j equals production current Jalali year, Resolver snapshot path
    matches calculate_entitlement_by_year(..., annual_override=snapshot).
    """
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    end = y_start + timedelta(days=60)
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=end, annual=28)
    db.add(c)
    db.commit()
    db.refresh(c)

    segs = split_contract_coverage_by_year(c, db=db)
    assert segs and segs[0][0] == year

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert ctx is not None
    calc = calculate_entitlement_by_year(db, c, annual_override=28)
    assert year in calc
    assert compute_annual_entitlement(ctx).raw_amount == calc[year]['AL']


def test_integration_multi_contract_pipeline(db, make_user, fixed_non_leap_year):
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

    contexts = resolve_annual_leave_contexts(
        db, user['user_id'], year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    results = [compute_annual_entitlement(ctx) for ctx in contexts]
    assert len(results) == 2
    assert all(isinstance(r, EntitlementResult) for r in results)
    assert all(r.year_j == year for r in results)
    assert sum(r.raw_amount for r in results) == sum(
        charge_amount_for_segment(
            ctx.membership_code,
            ctx.annual_days,
            year,
            ctx.coverage.start,
            ctx.coverage.end,
        )
        for ctx in contexts
    )
