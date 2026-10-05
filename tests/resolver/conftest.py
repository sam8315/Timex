"""Fixtures for Phase 2 Resolver tests. Reuse characterization helpers."""
from __future__ import annotations

from datetime import date

import pytest

# Re-export characterization fixtures/helpers used by resolver tests.
from tests.characterization.conftest import (  # noqa: F401
    FIXED_LEAP_YEAR_J,
    FIXED_NON_LEAP_YEAR_J,
    clear_user_contracts,
    current_jalali_year,
    fixed_leap_year,
    fixed_non_leap_year,
    get_jalali_year_days,
    jalali_year_bounds_g,
    make_contract,
    seed_leave_policy,
    set_active_membership_annual_base,
    timedelta,
)

# Deterministic as_of for live MembershipTypeRule resolve.
# Far enough in the future that seeded/active rules (effective_from <= today)
# are visible, without coupling coverage year_j to date.today().
FIXED_AS_OF = date(2099, 1, 1)


@pytest.fixture(autouse=True)
def _restore_seed_membership_annual_bases(db):
    """
    Resolver tests may change MembershipTypeRule.annual_leave_base.
    Restore seed defaults after each test so shared test DB stays stable
    for characterization / other suites in the same pytest session.
    """
    yield
    from models.membership_type_rule import MembershipTypeRule
    from web.services.membership_service import SEED_MEMBERSHIPS

    for code, _name, annual, *_rest in SEED_MEMBERSHIPS:
        db.query(MembershipTypeRule).filter(
            MembershipTypeRule.membership_type_code == code,
            MembershipTypeRule.status == 'active',
        ).update({'annual_leave_base': annual})
    db.commit()


def prepare_live_membership(
    db,
    membership_code: str,
    annual_leave_base: int,
    as_of_date: date | None = None,
) -> None:
    """Set membership annual base (as_of_date unused; kept for call-site clarity)."""
    del as_of_date  # coverage year is independent of live-rule as_of
    set_active_membership_annual_base(db, membership_code, annual_leave_base)
