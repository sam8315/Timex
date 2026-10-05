"""Resolver effective-dated MembershipTypeRule slices + multi-slice engine."""
from __future__ import annotations

from datetime import timedelta

import jdatetime
import pytest

from web.services.leave_entitlement_engine import (
    build_context_for_segment,
    compute_annual_entitlement,
    compute_annual_entitlement_for_slices,
)
from web.services.leave_entitlement_resolver import (
    membership_rule_timeline_for_year,
    resolve_sliced_contexts_for_contract,
)
from web.services.leave_entitlement_service import jalali_year_bounds_g
from web.services.leave_settlement import (
    MembershipChangeMode,
    resolve_membership_change_mode,
)
from tests.cutover.conftest import clear_user_contracts, make_contract, seed_leave_policy


def test_multi_slice_engine_sums_raw():
    year = 1404
    y_start, y_end = jalali_year_bounds_g(year)
    mid = y_start + timedelta(days=100)
    a = build_context_for_segment(
        membership_code='4',
        annual_days=30,
        year_j=year,
        seg_start=y_start,
        seg_end=mid,
        charge_mode='prorate',
    )
    b = build_context_for_segment(
        membership_code='4',
        annual_days=30,
        year_j=year,
        seg_start=mid + timedelta(days=1),
        seg_end=y_end,
        charge_mode='prorate',
    )
    combined = compute_annual_entitlement_for_slices([a, b])
    solo_a = compute_annual_entitlement(a).raw_amount
    solo_b = compute_annual_entitlement(b).raw_amount
    assert combined.raw_amount == pytest.approx(solo_a + solo_b)
    assert combined.year_j == year


def test_membership_change_mode_defaults_keep_separate(db):
    assert resolve_membership_change_mode(db) == MembershipChangeMode.KEEP_SEPARATE


def test_sliced_contexts_for_contract_parity_single_rule(db, make_user):
    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    c = make_contract(user['user_id'], '4', y_start, end=y_end, annual=30)
    db.add(c)
    db.commit()
    db.refresh(c)

    slices = resolve_sliced_contexts_for_contract(
        db, c, year, as_of_date=y_start
    )
    assert len(slices) >= 1
    timeline = membership_rule_timeline_for_year(db, '4', year)
    assert isinstance(timeline, list)
