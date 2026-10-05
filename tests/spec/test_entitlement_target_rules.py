"""
Target Rule placeholders — Phase 2+.

These tests encode Target Rules from docs/leave_entitlement_target_spec.md
but are skipped so they never fail default CI in Phase 1.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason='Phase 2+ Target Rule; non-blocking in Phase 1'
)


def test_target_contractual_base_default_26():
    """Target Rule: contractual base 26 (mismatch #1)."""
    assert False, 'not enforced in Phase 1'


def test_target_contractual_apply_region_default_false():
    """Target Rule: contractual apply_region default false (mismatch #2)."""
    assert False, 'not enforced in Phase 1'


def test_target_overlapping_contracts_union_coverage():
    """Target Rule: union/unique covered days (mismatch #3)."""
    assert False, 'not enforced in Phase 1'


def test_target_policy_change_midyear_slices():
    """Target Rule: date-effective Policy slices (mismatch #4)."""
    assert False, 'not enforced in Phase 1'


def test_target_region_change_midyear_slices():
    """Target Rule: region change mid-year segments (mismatch #5)."""
    assert False, 'not enforced in Phase 1'


def test_target_membership_change_settlement_policy():
    """Target Rule: Membership Change Settlement (mismatch #6)."""
    assert False, 'not enforced in Phase 1'


def test_target_permanent_midyear_end_prorata():
    """Target Rule: official midyear end Prorata (mismatch #7)."""
    assert False, 'not enforced in Phase 1'


def test_target_service_duration_and_start_date_policies():
    """Target Rule: ServiceDurationPolicy + StartDatePolicy (mismatch #8)."""
    assert False, 'not enforced in Phase 1'
