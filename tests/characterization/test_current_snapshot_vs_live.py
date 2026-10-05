"""
Current Behavior — charge snapshot vs permanent-history live policy (mismatch #16).

Documents Path B vs Path E divergence; does not fix it.
"""
from web.services.leave_entitlement_service import (
    jalali_year_bounds_g,
    resolve_annual_leave_days,
)
from web.services.leave_service import charge_leave_for_new_contract
from web.services.permanent_leave_history_service import build_year_plan
from tests.characterization.conftest import (
    make_contract,
    clear_user_contracts,
    seed_leave_policy,
)


def test_current_charge_uses_contract_snapshot_not_live_policy(
    db, make_user, current_jalali_year
):
    """Current Behavior Path B: annual_override=contract.annual_leave_days."""
    from models.leave_balance import LeaveBalance

    user = make_user(department='1', balance_al=None, contract_type_code='1')
    seed_leave_policy(db, {'1': 40}, region_applies={'1': False})
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    db.query(LeaveBalance).filter(LeaveBalance.user_id == user['user_id']).delete()
    db.commit()

    # Snapshot on contract differs from live policy (40)
    c = make_contract(user['user_id'], '1', y_start, end=None, annual=25)
    db.add(c)
    db.commit()
    db.refresh(c)

    charged = charge_leave_for_new_contract(db, c)
    assert charged[year]['AL'] == 25
    assert resolve_annual_leave_days(db, '1', region_code='NORMAL') == 40


def test_current_permanent_history_uses_live_policy(db, make_user, current_jalali_year):
    """Current Behavior Path E: build_year_plan resolves live policy annual."""
    user = make_user(department='1', balance_al=None, contract_type_code='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': False})
    year = current_jalali_year
    assert year > 1400
    past_start, _ = jalali_year_bounds_g(year - 2)
    clear_user_contracts(db, user['user_id'])
    # Contract snapshot intentionally different from live policy (30)
    c = make_contract(user['user_id'], '1', past_start, end=None, annual=99)
    db.add(c)
    db.commit()
    db.refresh(c)

    plan = build_year_plan(
        db,
        user_id=user['user_id'],
        start_date=c.start_date,
        region_code='NORMAL',
    )
    assert plan  # hire before current year
    for row in plan:
        assert row['entitlement'] == 30  # live policy, not contract snapshot 99
        assert row['entitlement'] != 99
