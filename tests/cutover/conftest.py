"""Fixtures for Phase 3 cutover tests."""
from __future__ import annotations

import pytest

from tests.characterization.conftest import (  # noqa: F401
    FIXED_NON_LEAP_YEAR_J,
    clear_user_contracts,
    current_jalali_year,
    fixed_non_leap_year,
    jalali_year_bounds_g,
    make_contract,
    seed_leave_policy,
    timedelta,
)


@pytest.fixture(autouse=True)
def _restore_seed_membership_annual_bases(db):
    yield
    from models.membership_type_rule import MembershipTypeRule
    from web.services.annual_leave_policy_authority import (
        sync_compat_policy_mirrors_from_rules,
    )
    from web.services.membership_service import SEED_MEMBERSHIPS

    for code, _name, annual, *_rest in SEED_MEMBERSHIPS:
        db.query(MembershipTypeRule).filter(
            MembershipTypeRule.membership_type_code == code,
            MembershipTypeRule.status == 'active',
        ).update({'annual_leave_base': annual})
    db.flush()
    sync_compat_policy_mirrors_from_rules(db)
    db.commit()
