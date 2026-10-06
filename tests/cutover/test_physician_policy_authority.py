"""
Physician (membership code 5) annual-leave policy authority matrix.

SoT: MembershipTypeRule.annual_leave_base (seed 0).
Compatibility: PolicyValue annual_leave_dept_5 mirror.
Charge: Contract.annual_leave_days snapshot (may historically be 30).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from models.policy import Policy, PolicyValue
from web.services.annual_leave_policy_authority import (
    PHYSICIAN_CODE,
    audit_annual_policy_conflicts,
    engine_promotion_blockers,
    is_engine_promotion_allowed,
    physician_live_annual_base,
    sync_compat_policy_mirrors_from_rules,
)
from web.services.leave_entitlement_cutover import (
    PATH_ENGINE,
    PATH_SHADOW,
    classify_shadow_outcome,
    entitlement_via_resolver_engine,
    entitlements_match,
    get_effective_entitlement_path,
    get_entitlement_path,
    resolve_prorated_entitlement,
    _compute_engine_entitlement,
)
from web.services.leave_entitlement_resolver import (
    resolve_annual_leave_context_for_contract,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    charge_amount_for_segment,
    resolve_annual_leave_days,
    resolve_annual_leave_days_legacy,
)
from web.services.leave_service import (
    charge_leave_for_new_contract,
    remove_leave_for_contract,
)
from tests.characterization.conftest import (
    FIXED_NON_LEAP_YEAR_J,
    clear_user_contracts,
    jalali_year_bounds_g,
    make_contract,
    seed_leave_policy,
    set_active_membership_annual_base,
)


def _force_mirror(db, code: str, value: int) -> None:
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    assert policy is not None
    key = f'annual_leave_dept_{code}'
    pv = (
        db.query(PolicyValue)
        .filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == key,
            PolicyValue.region_code.is_(None),
        )
        .first()
    )
    if pv is None:
        db.add(
            PolicyValue(
                policy_id=policy.id,
                parameter_key=key,
                parameter_value=str(value),
                is_editable=True,
            )
        )
    else:
        pv.parameter_value = str(value)
    db.commit()


@pytest.fixture
def path_engine(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'engine')


@pytest.fixture
def path_shadow(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'shadow')


def test_physician_seed_live_base_is_zero(db):
    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    assert physician_live_annual_base(db) == 0
    assert resolve_annual_leave_days(db, PHYSICIAN_CODE, region_code=None) == 0


def test_physician_mirror_drift_detected_and_synced(db):
    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    _force_mirror(db, PHYSICIAN_CODE, 30)  # Production-shaped drift
    conflicts = audit_annual_policy_conflicts(
        db, membership_codes=[PHYSICIAN_CODE]
    )
    assert len(conflicts) == 1
    assert conflicts[0].kind == 'mirror_drift'
    assert conflicts[0].rule_base == 0
    assert conflicts[0].mirror_annual == 30
    assert not is_engine_promotion_allowed(db)
    assert any('code=5' in b for b in engine_promotion_blockers(db))

    changes = sync_compat_policy_mirrors_from_rules(
        db, membership_codes=[PHYSICIAN_CODE]
    )
    db.commit()
    assert changes
    assert changes[0].old_mirror == '30'
    assert changes[0].new_mirror == '0'
    assert audit_annual_policy_conflicts(
        db, membership_codes=[PHYSICIAN_CODE]
    ) == []
    assert is_engine_promotion_allowed(db)


def test_physician_legacy_resolver_engine_live_invariant(db):
    """After mirror sync: legacy live == Rule live == resolve_annual_leave_days."""
    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    seed_leave_policy(db, {PHYSICIAN_CODE: 0}, region_applies={PHYSICIAN_CODE: False})
    sync_compat_policy_mirrors_from_rules(db, membership_codes=[PHYSICIAN_CODE])
    db.commit()

    legacy = resolve_annual_leave_days_legacy(
        db, PHYSICIAN_CODE, region_code=None
    )
    live = resolve_annual_leave_days(db, PHYSICIAN_CODE, region_code=None)
    assert legacy == live == 0 == physician_live_annual_base(db)


def test_physician_full_and_partial_year_math(db):
    year = FIXED_NON_LEAP_YEAR_J
    y_start, y_end = jalali_year_bounds_g(year)
    assert charge_amount_for_segment('5', 0, year, y_start, y_end) == 0.0
    # Snapshot 30 still uses physician/contractual prorata shape
    assert charge_amount_for_segment('5', 30, year, y_start, y_end) == 30.0
    end = y_start + timedelta(days=99)
    partial_30 = charge_amount_for_segment('5', 30, year, y_start, end)
    partial_0 = charge_amount_for_segment('5', 0, year, y_start, end)
    assert partial_0 == 0.0
    assert partial_30 == charge_amount_for_segment('4', 30, year, y_start, end)


def test_physician_snapshot_charge_parity_engine(db, make_user, path_engine):
    import jdatetime

    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    seed_leave_policy(
        db, {PHYSICIAN_CODE: 0}, region_applies={PHYSICIAN_CODE: False}
    )
    user = make_user(
        department=PHYSICIAN_CODE, region_code='NORMAL', balance_al=None
    )
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    # Historical Production-shaped snapshot 30 while live Rule is 0
    c = make_contract(
        user['user_id'], PHYSICIAN_CODE, y_start, end=y_end, annual=30
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    engine = entitlement_via_resolver_engine(db, c, annual_override=30)
    assert entitlements_match(legacy, engine)
    assert legacy[year]['AL'] == 30.0
    resolved = resolve_prorated_entitlement(db, c, annual_override=30)
    assert entitlements_match(legacy, resolved)
    assert get_effective_entitlement_path(db) == PATH_ENGINE


def test_physician_live_context_uses_rule_zero(db, make_user):
    from datetime import date

    import jdatetime

    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    seed_leave_policy(
        db, {PHYSICIAN_CODE: 0}, region_applies={PHYSICIAN_CODE: False}
    )
    user = make_user(
        department=PHYSICIAN_CODE, region_code='NORMAL', balance_al=None
    )
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], PHYSICIAN_CODE, y_start, end=y_end, annual=30
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    live_ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=date(2099, 1, 1), annual_source='live'
    )
    snap_ctx = resolve_annual_leave_context_for_contract(
        db, c, year, as_of_date=date(2099, 1, 1), annual_source='snapshot'
    )
    assert live_ctx is not None and snap_ctx is not None
    assert live_ctx.annual_days == 0.0
    assert snap_ctx.annual_days == 30.0
    assert live_ctx.charge_mode == 'physician'


def test_physician_shadow_ok_with_snapshot(db, make_user, path_shadow):
    import jdatetime

    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    seed_leave_policy(
        db, {PHYSICIAN_CODE: 0}, region_applies={PHYSICIAN_CODE: False}
    )
    user = make_user(
        department=PHYSICIAN_CODE, region_code='NORMAL', balance_al=None
    )
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], PHYSICIAN_CODE, y_start, end=y_end, annual=30
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    new, meta = _compute_engine_entitlement(db, c, annual_override=30, year_j=year)
    outcome = classify_shadow_outcome(legacy, new, meta=meta, failure=None)
    assert outcome.mismatch_type == 'OK'
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy


def test_physician_engine_blocked_while_mirror_drifts(
    db, make_user, path_engine
):
    import jdatetime

    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    _force_mirror(db, PHYSICIAN_CODE, 30)
    assert get_entitlement_path() == PATH_ENGINE
    assert get_effective_entitlement_path(db) == PATH_SHADOW

    user = make_user(
        department=PHYSICIAN_CODE, region_code='NORMAL', balance_al=None
    )
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(
        user['user_id'], PHYSICIAN_CODE, y_start, end=y_end, annual=30
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    # Downgraded to shadow: returns legacy, does not raise
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    assert resolve_prorated_entitlement(db, c, annual_override=30) == legacy


def test_physician_contract_create_edit_remove_charge(db, make_user, path_engine):
    import jdatetime

    from models.leave_balance import LeaveBalance

    set_active_membership_annual_base(db, PHYSICIAN_CODE, 0)
    seed_leave_policy(
        db, {PHYSICIAN_CODE: 0}, region_applies={PHYSICIAN_CODE: False}
    )
    user = make_user(
        department=PHYSICIAN_CODE, region_code='NORMAL', balance_al=None
    )
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    db.query(LeaveBalance).filter(LeaveBalance.user_id == user['user_id']).delete()
    db.commit()

    # Create with live Rule 0 → snapshot 0 → no AL charge rows
    c = make_contract(
        user['user_id'], PHYSICIAN_CODE, y_start, end=y_end, annual=0
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    charged = charge_leave_for_new_contract(db, c)
    assert charged.get(year, {}).get('AL', 0) == 0

    # Edit snapshot to historical 30 and charge / remove
    c.annual_leave_days = 30
    db.commit()
    db.refresh(c)
    charged30 = charge_leave_for_new_contract(db, c)
    assert charged30[year]['AL'] == 30
    bal = (
        db.query(LeaveBalance)
        .filter_by(user_id=user['user_id'], year=year, leave_type='AL')
        .first()
    )
    assert bal is not None and bal.balance == 30
    remove_leave_for_contract(db, c)
    bal2 = (
        db.query(LeaveBalance)
        .filter_by(user_id=user['user_id'], year=year, leave_type='AL')
        .first()
    )
    assert bal2 is None or bal2.balance == 0
