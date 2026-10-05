"""
Characterization fixtures for Current Behavior leave entitlement tests.

These fixtures lock Current Behavior only. They do not encode Target Rules.
See docs/leave_entitlement_target_spec.md for Target Rules / mismatch register.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, Optional

import jdatetime
import pytest

from models.contract import Contract
from models.policy import Policy, PolicyValue
from web.services.leave_entitlement_service import (
    get_jalali_year_days,
    jalali_year_bounds_g,
)

# Fixed Jalali years for non-flaky calendar/parity math (avoid Nowruz boundary).
FIXED_LEAP_YEAR_J = 1403  # Jalali leap
FIXED_NON_LEAP_YEAR_J = 1404  # Jalali non-leap


@pytest.fixture
def fixed_leap_year():
    return FIXED_LEAP_YEAR_J


@pytest.fixture
def fixed_non_leap_year():
    return FIXED_NON_LEAP_YEAR_J


@pytest.fixture
def current_jalali_year():
    """Current Behavior of split_contract_coverage_by_year uses today().year."""
    return jdatetime.date.today().year


def seed_leave_policy(
    db,
    dept_annual: Dict[str, int],
    region_applies: Optional[Dict[str, bool]] = None,
):
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(category='leave', name='سیاست مرخصی characterization', is_active=True)
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
        if region_applies is not None and code in region_applies:
            applies = region_applies[code]
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
        elif region_applies is None:
            # Leave flag absent for "missing flag" Current Behavior cases —
            # caller deletes flags explicitly when needed.
            pass
        else:
            applies = True
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


def make_contract(user_id, type_code, start, end=None, annual=30, sick=0, deduction=0):
    return Contract(
        user_id=user_id,
        contract_type_code=type_code,
        start_date=start,
        end_date=end,
        annual_leave_days=annual,
        sick_leave_days=sick,
        service_deduction_days=deduction,
    )


def clear_user_contracts(db, user_id):
    db.query(Contract).filter(Contract.user_id == user_id).delete()
    db.commit()


def set_active_membership_annual_base(db, membership_code: str, annual_leave_base: int) -> None:
    """
    Characterization-only: set MembershipTypeRule.annual_leave_base for seeded rules.

    Baseline 164d130 Current Behavior: when a membership rule exists,
    resolve_annual_leave_days uses this base (not PolicyValue annual_leave_dept_*).
    """
    from models.membership_type_rule import MembershipTypeRule
    from web.services.membership_service import get_effective_rule

    rule = get_effective_rule(db, membership_code)
    if rule is None:
        raise AssertionError(
            f"No effective MembershipTypeRule for code={membership_code!r}; "
            "test DB should seed membership foundation."
        )
    rule.annual_leave_base = max(0, int(annual_leave_base))
    # Keep other active rows for this code consistent for characterization isolation.
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == membership_code,
        MembershipTypeRule.status == 'active',
    ).update({'annual_leave_base': max(0, int(annual_leave_base))})
    db.commit()


# Re-export calendar helpers used by Current Behavior tests
__all__ = [
    'FIXED_LEAP_YEAR_J',
    'FIXED_NON_LEAP_YEAR_J',
    'seed_leave_policy',
    'set_active_membership_annual_base',
    'make_contract',
    'clear_user_contracts',
    'get_jalali_year_days',
    'jalali_year_bounds_g',
    'timedelta',
]
