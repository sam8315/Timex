"""
Current Behavior — region / policy annual resolve.

Does NOT assert Target Rule default apply_region=false for contractual (mismatch #2).
"""
from models.policy import PolicyValue
from models.region import Region
from web.services.leave_entitlement_service import resolve_annual_leave_days
from tests.characterization.conftest import seed_leave_policy


def _clear_scoped_region_annual(db, region_code: str):
    db.query(PolicyValue).filter(
        PolicyValue.parameter_key == 'annual_leave_days',
        PolicyValue.region_code == region_code,
    ).delete()
    db.commit()


def test_current_region_enabled_replaces_annual(db, make_user):
    """Current Behavior: when region_applies true, region annual replaces dept base."""
    make_user(department='1', region_code='GRADE_2')
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    seed_leave_policy(db, {'1': 35}, region_applies={'1': True})
    assert resolve_annual_leave_days(db, '1', region_code='GRADE_2') == 40


def test_current_region_disabled_uses_dept_base(db, make_user):
    make_user(department='2')
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    seed_leave_policy(db, {'2': 30}, region_applies={'2': False})
    assert resolve_annual_leave_days(db, '2', region_code='GRADE_2') == 30


def test_current_region_flag_missing_defaults_true(db, make_user):
    """
    Current Behavior: missing region_applies flag ⇒ region still applies (True).

    Target Rule mismatch #2 for contractual default false — Spec only.
    """
    make_user(department='2')
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    policy = seed_leave_policy(db, {'2': 30}, region_applies={'2': True})
    # Delete flag to simulate missing
    db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy.id,
        PolicyValue.parameter_key == 'region_applies_dept_2',
    ).delete()
    db.commit()
    assert resolve_annual_leave_days(db, '2', region_code='GRADE_2') == 40


def test_current_region_scoped_policy_override(db, make_user):
    make_user(department='1', region_code='GRADE_2')
    _clear_scoped_region_annual(db, 'GRADE_2')
    db.query(Region).filter(Region.code == 'GRADE_2').update(
        {'default_annual_leave_days': 40}
    )
    db.commit()
    policy = seed_leave_policy(db, {'1': 35}, region_applies={'1': True})
    db.add(PolicyValue(
        policy_id=policy.id,
        parameter_key='annual_leave_days',
        parameter_value='42',
        region_code='GRADE_2',
    ))
    db.commit()
    assert resolve_annual_leave_days(db, '1', region_code='GRADE_2') == 42


def test_current_missing_region_row_keeps_dept_base(db, make_user):
    """Current Behavior: unknown region_code → keep dept annual (no region row)."""
    make_user(department='1')
    seed_leave_policy(db, {'1': 33}, region_applies={'1': True})
    assert resolve_annual_leave_days(db, '1', region_code='DOES_NOT_EXIST') == 33


def test_current_zero_annual_base_with_region_off(db, make_user):
    make_user(department='4')
    seed_leave_policy(db, {'4': 0}, region_applies={'4': False})
    assert resolve_annual_leave_days(db, '4', region_code='NORMAL') == 0
