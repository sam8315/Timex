"""Dated leave settlement caps: storage/year + buyback by membership/region/period."""
from __future__ import annotations

import jdatetime
import pytest

from models.leave_settlement_cap_period import LeaveSettlementCapPeriod
from models.region import Region
from web.services.leave_entitlement_service import jalali_year_bounds_g, resolve_max_buyback
from web.services.leave_settlement import resolve_storage_cap
from web.services.leave_settlement.caps import (
    SettlementCapOverlapError,
    create_period,
    resolve_settlement_caps as resolve_caps,
)
from web.services.permanent_leave_history_service import preview_history_summary
from tests.characterization.conftest import seed_leave_policy


@pytest.fixture(autouse=True)
def _clean_settlement_periods(db):
    db.query(LeaveSettlementCapPeriod).delete()
    db.commit()
    yield
    db.query(LeaveSettlementCapPeriod).delete()
    db.commit()


def _ensure_region(db, code: str, name: str | None = None) -> Region:
    row = db.query(Region).filter(Region.code == code).first()
    if row:
        return row
    row = Region(
        code=code,
        name=name or code,
        default_annual_leave_days=30,
        is_active=True,
        sort_order=0,
    )
    db.add(row)
    db.commit()
    return row


def _g(year_j: int, month: int = 1, day: int = 1):
    return jdatetime.date(year_j, month, day).togregorian()


def test_overlap_rejected(db, make_user):
    make_user(department='4')
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    create_period(
        db,
        membership_code='4',
        region_code=None,
        effective_from=_g(1400),
        effective_to=_g(1402, 12, 29),
        storage_cap=9,
        buyback_cap=5,
    )
    with pytest.raises(SettlementCapOverlapError):
        create_period(
            db,
            membership_code='4',
            region_code=None,
            effective_from=_g(1402, 1, 1),
            effective_to=_g(1403, 12, 29),
            storage_cap=10,
            buyback_cap=6,
        )


def test_region_on_region_row_wins(db, make_user):
    make_user(department='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    _ensure_region(db, 'GRADE_2')
    create_period(
        db,
        membership_code='1',
        region_code='GRADE_2',
        effective_from=_g(1399),
        effective_to=None,
        storage_cap=9,
        buyback_cap=18,
    )
    caps = resolve_caps(
        db, '1', region_code='GRADE_2', year_j=1404
    )
    assert caps['source'] == 'period_region'
    assert caps['storage_cap'] == 9
    assert caps['buyback_cap'] == 18
    assert resolve_storage_cap(db, '1', region_code='GRADE_2', year_j=1404) == 9
    assert resolve_max_buyback(db, '1', region_code='GRADE_2', year_j=1404) == 18


def test_region_on_falls_back_to_membership_then_legacy(db, make_user):
    make_user(department='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    _ensure_region(db, 'NORMAL')
    # membership-level row (created while temporarily forcing via direct insert
    # because create_period requires region when applies=on)
    db.add(
        LeaveSettlementCapPeriod(
            membership_code='1',
            region_code=None,
            effective_from=_g(1400),
            effective_to=None,
            storage_cap=7,
            buyback_cap=11,
        )
    )
    db.commit()
    caps = resolve_caps(db, '1', region_code='NORMAL', year_j=1404)
    assert caps['source'] == 'period_membership'
    assert caps['storage_cap'] == 7
    assert caps['buyback_cap'] == 11

    db.query(LeaveSettlementCapPeriod).delete()
    db.commit()
    caps2 = resolve_caps(db, '1', region_code='NORMAL', year_j=1404)
    assert caps2['source'] == 'legacy'
    assert resolve_max_buyback(db, '1', region_code='NORMAL', year_j=1404) == 15


def test_region_off_ignores_region_rows(db, make_user):
    make_user(department='4')
    seed_leave_policy(db, {'4': 30}, region_applies={'4': False})
    _ensure_region(db, 'GRADE_2')
    # sneak a region row in (UI would not allow); resolve must ignore it
    db.add(
        LeaveSettlementCapPeriod(
            membership_code='4',
            region_code='GRADE_2',
            effective_from=_g(1400),
            effective_to=None,
            storage_cap=3,
            buyback_cap=3,
        )
    )
    db.commit()
    create_period(
        db,
        membership_code='4',
        region_code=None,
        effective_from=_g(1400),
        effective_to=None,
        storage_cap=9,
        buyback_cap=12,
    )
    caps = resolve_caps(db, '4', region_code='GRADE_2', year_j=1404)
    assert caps['source'] == 'period_membership'
    assert caps['storage_cap'] == 9
    assert caps['buyback_cap'] == 12


def test_per_year_history_uses_year_end_caps(db, make_user):
    user = make_user(department='1', contract_type_code='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    _ensure_region(db, 'NORMAL')
    # 1402: storage 5; 1403+: storage 9
    create_period(
        db,
        membership_code='1',
        region_code='NORMAL',
        effective_from=_g(1402),
        effective_to=jalali_year_bounds_g(1402)[1],
        storage_cap=5,
        buyback_cap=15,
    )
    create_period(
        db,
        membership_code='1',
        region_code='NORMAL',
        effective_from=_g(1403),
        effective_to=None,
        storage_cap=9,
        buyback_cap=18,
    )
    start = jdatetime.date(1402, 1, 1).togregorian()
    preview = preview_history_summary(
        db,
        user_id=user['user_id'],
        start_date=start,
        used_by_year={1402: 0, 1403: 0, 1404: 0},
    )
    by_year = {y['year']: y for y in preview['years']}
    assert by_year[1402]['storage_cap'] == 5
    assert by_year[1402]['carry'] == 5
    assert by_year[1403]['storage_cap'] == 9
    assert by_year[1403]['carry'] == 9


def test_create_allows_membership_level_when_region_applies(db, make_user):
    make_user(department='1')
    seed_leave_policy(db, {'1': 30}, region_applies={'1': True})
    row = create_period(
        db,
        membership_code='1',
        region_code=None,
        effective_from=_g(1400),
        effective_to=None,
        storage_cap=9,
        buyback_cap=15,
    )
    assert row.region_code is None
    assert row.storage_cap == 9


def test_seed_default_settlement_caps(db, make_user):
    make_user(department='1')
    seed_leave_policy(db, {'1': 30, '2': 30, '3': 30, '4': 30}, region_applies={
        '1': True, '2': False, '3': False, '4': False,
    })
    for code in ('NORMAL', 'GRADE_2', 'GRADE_3', 'GRADE_4'):
        _ensure_region(db, code)
    from web.services.leave_settlement.caps import seed_default_settlement_cap_periods

    n = seed_default_settlement_cap_periods(db, force=True)
    assert n >= 7
    caps = resolve_caps(db, '1', region_code='NORMAL', year_j=1404)
    assert caps['source'] == 'period_region'
    assert caps['buyback_cap'] == 15
    assert caps['storage_cap'] is None
    caps_old = resolve_caps(db, '1', region_code='NORMAL', year_j=1388)
    assert caps_old['source'] == 'period_membership'
    assert caps_old['buyback_cap'] is None
    caps_mid = resolve_caps(db, '1', region_code='NORMAL', year_j=1395)
    assert caps_mid['buyback_cap'] == 15
    assert resolve_caps(db, '4', year_j=1404)['storage_cap'] == 9
    assert resolve_caps(db, '4', year_j=1404)['buyback_cap'] == 9
    assert resolve_caps(db, '2', year_j=1404)['storage_cap'] is None
    assert resolve_caps(db, '3', year_j=1404)['buyback_cap'] is None
