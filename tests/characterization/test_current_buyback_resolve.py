"""
Current Behavior — buyback resolve APIs only (outside Entitlement Engine).

Does NOT merge Buyback into Engine. Dual-path mismatch #13 is Spec-only.
"""
from web.services.leave_entitlement_service import resolve_max_buyback
from models.policy import Policy, PolicyValue
from tests.characterization.conftest import seed_leave_policy


def _set_policy_value(db, policy_id, key, value, region_code=None):
    q = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy_id,
        PolicyValue.parameter_key == key,
    )
    if region_code is None:
        q = q.filter(PolicyValue.region_code.is_(None))
    else:
        q = q.filter(PolicyValue.region_code == region_code)
    row = q.first()
    if row:
        row.parameter_value = str(value)
    else:
        db.add(PolicyValue(
            policy_id=policy_id,
            parameter_key=key,
            parameter_value=str(value),
            region_code=region_code,
        ))
    db.commit()


def test_current_buyback_era_1390_1398_cap(db, make_user):
    make_user(department='1')
    policy = seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    _set_policy_value(db, policy.id, 'buyback_era_1390_1398_cap', '15')
    _set_policy_value(db, policy.id, 'buyback_era_modern_from_year', '1399')
    assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1395) == 15


def test_current_buyback_pre_1390_unlimited_default(db, make_user):
    """Current Behavior default pre-1390 cap parses as unlimited (none)."""
    make_user(department='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1388) is None


def test_current_buyback_modern_region_normal(db, make_user):
    make_user(department='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1404) == 15


def test_current_buyback_contractual_default_unlimited(db, make_user):
    make_user(department='4')
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    assert resolve_max_buyback(db, '4', year_j=1404) is None
