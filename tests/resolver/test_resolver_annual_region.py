"""Phase 2 Resolver — live annual / region / snapshot Current Behavior."""
from __future__ import annotations

from models.policy import PolicyValue
from models.region import Region
from web.services.leave_entitlement_engine import compute_annual_entitlement
from web.services.leave_entitlement_service import (
    charge_amount_for_segment,
    jalali_year_bounds_g,
    resolve_annual_leave_days,
)
from web.services.leave_entitlement_resolver import (
    resolve_annual_leave_context_for_contract,
)
from tests.resolver.conftest import (
    FIXED_AS_OF,
    clear_user_contracts,
    make_contract,
    prepare_live_membership,
    seed_leave_policy,
)


def _clear_scoped_region_annual(db, region_code: str):
    db.query(PolicyValue).filter(
        PolicyValue.parameter_key == 'annual_leave_days',
        PolicyValue.region_code == region_code,
    ).delete()
    db.commit()


def test_resolver_region_enabled_replaces_annual(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='GRADE_2', balance_al=None)
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    prepare_live_membership(db, '1', 35, y_start)
    seed_leave_policy(db, {'1': 35}, region_applies={'1': True})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=35)
    db.add(c)
    db.commit()
    db.refresh(c)

    assert resolve_annual_leave_days(db, '1', region_code='GRADE_2') == 40
    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.annual_days == 40.0
    assert compute_annual_entitlement(ctx).raw_amount == charge_amount_for_segment(
        '1', 40, year, y_start, y_end
    )


def test_resolver_region_disabled_uses_membership_base(
    db, make_user, fixed_non_leap_year
):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='2', region_code='GRADE_2', balance_al=None)
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    prepare_live_membership(db, '2', 30, y_start)
    seed_leave_policy(db, {'2': 30}, region_applies={'2': False})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '2', y_start, end=y_end, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.annual_days == 30.0


def test_resolver_missing_region_row_keeps_membership_base(
    db, make_user, fixed_non_leap_year
):
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='DOES_NOT_EXIST', balance_al=None)
    prepare_live_membership(db, '1', 33, y_start)
    seed_leave_policy(db, {'1': 99}, region_applies={'1': True})
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=33)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    assert ctx is not None
    assert ctx.annual_days == 33.0


def test_resolver_snapshot_vs_live(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    prepare_live_membership(db, '1', 40, y_start)
    seed_leave_policy(db, {'1': 99}, region_applies={'1': False})
    clear_user_contracts(db, user['user_id'])
    # Snapshot intentionally differs from live membership base
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=25)
    db.add(c)
    db.commit()
    db.refresh(c)

    live = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='live'
    )
    snap = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert live is not None and snap is not None
    assert live.annual_days == 40.0
    assert snap.annual_days == 25.0
    assert compute_annual_entitlement(snap).raw_amount == charge_amount_for_segment(
        '1', 25, year, y_start, y_end
    )
    assert compute_annual_entitlement(live).raw_amount == charge_amount_for_segment(
        '1', 40, year, y_start, y_end
    )


def test_resolver_calendar_passthrough(db, make_user, fixed_leap_year):
    year = fixed_leap_year
    y_start, y_end = jalali_year_bounds_g(year)
    from web.services.leave_entitlement_engine.calendar import (
        get_jalali_year_days as engine_days,
        jalali_year_bounds_g as engine_bounds,
    )

    user = make_user(department='1', region_code='NORMAL', balance_al=None)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=FIXED_AS_OF, annual_source='snapshot'
    )
    assert ctx is not None
    assert ctx.year_days == engine_days(year) == 366
    assert (ctx.year_start_g, ctx.year_end_g) == engine_bounds(year)
    assert ctx.as_of_date == FIXED_AS_OF


def test_resolver_requires_as_of_date(db, make_user, fixed_non_leap_year):
    year = fixed_non_leap_year
    y_start, _ = jalali_year_bounds_g(year)
    user = make_user(department='4', balance_al=None)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=None, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    import pytest

    with pytest.raises(ValueError, match='as_of_date'):
        resolve_annual_leave_context_for_contract(
            db, c, year, as_of_date=None, annual_source='live'  # type: ignore[arg-type]
        )
