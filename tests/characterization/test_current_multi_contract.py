"""
Current Behavior — multi-contract sequencing and overlap rejection.

Target Rule union/unique covered days is NOT asserted (mismatch #3).
"""
from datetime import timedelta

from web.services.leave_entitlement_service import (
    find_overlapping_contract,
    jalali_year_bounds_g,
)
from tests.characterization.conftest import make_contract, clear_user_contracts, seed_leave_policy


def test_current_sequential_non_overlapping_same_year_no_overlap_error(
    db, make_user, current_jalali_year
):
    user = make_user(department='4', balance_al=None)
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c1 = make_contract(
        user['user_id'], '4', y_start, end=y_start + timedelta(days=29), annual=30
    )
    db.add(c1)
    db.commit()
    overlapping = find_overlapping_contract(
        db,
        user['user_id'],
        y_start + timedelta(days=30),
        y_start + timedelta(days=59),
    )
    assert overlapping is None


def test_current_overlap_rejected(db, make_user, current_jalali_year):
    """Current Behavior: overlapping ranges return the other contract (admin rejects)."""
    user = make_user(department='4', balance_al=None)
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c1 = make_contract(
        user['user_id'], '4', y_start, end=y_start + timedelta(days=60), annual=30
    )
    db.add(c1)
    db.commit()
    overlapping = find_overlapping_contract(
        db,
        user['user_id'],
        y_start + timedelta(days=30),
        y_start + timedelta(days=90),
    )
    assert overlapping is not None
    assert overlapping.id == c1.id


def test_current_membership_change_midyear_no_settlement(
    db, make_user, current_jalali_year
):
    """
    Current Behavior: sequential memberships each charge independently;
    no Membership Change Settlement (Target mismatch #6 — Spec only).
    """
    from web.services.leave_service import charge_leave_for_new_contract
    from models.leave_balance import LeaveBalance

    user = make_user(department='4', balance_al=None)
    seed_leave_policy(db, {'4': 30, '3': 30}, region_applies={'4': False, '3': False})
    year = current_jalali_year
    y_start, _ = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    db.query(LeaveBalance).filter(LeaveBalance.user_id == user['user_id']).delete()
    db.commit()

    c1 = make_contract(
        user['user_id'], '4', y_start, end=y_start + timedelta(days=89), annual=30
    )
    db.add(c1)
    db.commit()
    db.refresh(c1)
    charged1 = charge_leave_for_new_contract(db, c1)

    c2 = make_contract(
        user['user_id'],
        '3',
        y_start + timedelta(days=90),
        end=y_start + timedelta(days=179),
        annual=30,
    )
    db.add(c2)
    db.commit()
    db.refresh(c2)
    charged2 = charge_leave_for_new_contract(db, c2)

    assert year in charged1 and year in charged2
    bal = db.query(LeaveBalance).filter_by(
        user_id=user['user_id'], year=year, leave_type='AL'
    ).first()
    assert bal is not None
    assert bal.balance == charged1[year]['AL'] + charged2[year]['AL']
