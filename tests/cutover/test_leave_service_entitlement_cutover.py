"""
Phase 3: leave_service.calculate_prorated_leave_by_year cutover paths.

Default TIMEX_AL_ENTITLEMENT_PATH=legacy preserves Current Behavior.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import TX_CHARGE
from web.services.leave_entitlement_cutover import (
    EntitlementParityError,
    entitlement_via_resolver_engine,
    entitlements_match,
    resolve_prorated_entitlement,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    jalali_year_bounds_g,
)
from web.services.leave_service import (
    calculate_prorated_leave_by_year,
    charge_leave_for_new_contract,
)
from tests.cutover.conftest import (
    clear_user_contracts,
    make_contract,
    seed_leave_policy,
)


@pytest.fixture
def path_legacy(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'legacy')


@pytest.fixture
def path_shadow(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'shadow')


@pytest.fixture
def path_engine(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'engine')


def _seed_contract(db, make_user, *, type_code='4', annual=30, end_offset=None):
    user = make_user(department=type_code, region_code='NORMAL', balance_al=None)
    seed_leave_policy(db, {type_code: annual}, region_applies={type_code: False})
    year = __import__('jdatetime').date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    end = y_end if end_offset is None else y_start + timedelta(days=end_offset)
    if type_code == '1' and end_offset is None:
        end = None
    c = make_contract(user['user_id'], type_code, y_start, end=end, annual=annual)
    db.add(c)
    db.commit()
    db.refresh(c)
    return user, c, year, y_start, y_end


def test_legacy_matches_calculate_entitlement(db, make_user, path_legacy):
    user, c, year, y_start, y_end = _seed_contract(db, make_user)
    employee = None
    via_service = calculate_prorated_leave_by_year(
        c, db=db, employee=employee, annual_override=c.annual_leave_days
    )
    via_legacy = calculate_entitlement_by_year(
        db, c, annual_override=c.annual_leave_days
    )
    assert via_service == via_legacy
    assert year in via_service


def test_engine_matches_legacy_raw_and_rounded(db, make_user, path_engine):
    _, c, year, _, _ = _seed_contract(db, make_user, annual=30, end_offset=89)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    engine = entitlement_via_resolver_engine(db, c, annual_override=30)
    assert entitlements_match(legacy, engine)
    assert round(legacy[year]['AL']) == round(engine[year]['AL'])
    resolved = resolve_prorated_entitlement(db, c, annual_override=30)
    assert entitlements_match(legacy, resolved)


def test_shadow_returns_legacy_on_match(db, make_user, path_shadow):
    _, c, year, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    assert year in out


def test_shadow_returns_legacy_even_when_engine_forced_mismatch(
    db, make_user, path_shadow, monkeypatch
):
    from web.services.leave_entitlement_cutover import _EngineStageError

    _, c, _, _, _ = _seed_contract(db, make_user)

    def _boom(*args, **kwargs):
        raise _EngineStageError('forced engine failure')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._compute_engine_entitlement',
        _boom,
    )
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy


def test_engine_aborts_on_parity_mismatch(db, make_user, path_engine, monkeypatch):
    _, c, year, _, _ = _seed_contract(db, make_user)

    def _wrong(db, contract, *, annual_override=None, year_j=None):
        return {year: {'AL': 999.0, 'SL': 0.0}}

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover.entitlement_via_resolver_engine',
        _wrong,
    )
    with pytest.raises(EntitlementParityError):
        resolve_prorated_entitlement(db, c, annual_override=30)


def test_engine_exception_aborts_without_fallback(
    db, make_user, path_engine, monkeypatch
):
    _, c, _, _, _ = _seed_contract(db, make_user)

    def _boom(*args, **kwargs):
        raise RuntimeError('resolver failed')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover.entitlement_via_resolver_engine',
        _boom,
    )
    with pytest.raises(RuntimeError, match='resolver failed'):
        resolve_prorated_entitlement(db, c, annual_override=30)


def test_open_ended_permanent_engine_parity(db, make_user, path_engine):
    _, c, year, _, _ = _seed_contract(db, make_user, type_code='1', annual=30)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    engine = entitlement_via_resolver_engine(db, c, annual_override=30)
    assert entitlements_match(legacy, engine)
    assert engine[year]['AL'] == 30.0


def test_conscript_deduction_engine_parity(db, make_user, path_engine):
    user = make_user(department='2', region_code='NORMAL', balance_al=None)
    seed_leave_policy(db, {'2': 35}, region_applies={'2': False})
    year = __import__('jdatetime').date.today().year
    y_start, _ = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    end = y_start + timedelta(days=200)
    c = make_contract(
        user['user_id'], '2', y_start, end=end, annual=35, deduction=20
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    legacy = calculate_entitlement_by_year(db, c, annual_override=35)
    engine = entitlement_via_resolver_engine(db, c, annual_override=35)
    assert entitlements_match(legacy, engine)


def test_zero_entitlement_engine(db, make_user, path_engine):
    _, c, year, _, _ = _seed_contract(db, make_user, annual=0, end_offset=30)
    out = resolve_prorated_entitlement(db, c, annual_override=0)
    assert out[year]['AL'] == 0.0


def test_charge_mutation_parity_engine_vs_legacy(db, make_user, monkeypatch):
    """Same charge ledger under legacy and engine when parity holds."""
    user, c, year, _, _ = _seed_contract(db, make_user, annual=30, end_offset=60)

    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'legacy')
    # Fresh contract clone for second charge would double — compare calc only,
    # then one charge under engine and assert TX matches rounded calc.
    legacy_calc = calculate_prorated_leave_by_year(
        c, db=db, annual_override=30
    )
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'engine')
    engine_calc = calculate_prorated_leave_by_year(
        c, db=db, annual_override=30
    )
    assert entitlements_match(legacy_calc, engine_calc)

    db.query(LeaveBalance).filter(LeaveBalance.user_id == user['user_id']).delete()
    db.query(LeaveTransaction).filter(
        LeaveTransaction.user_id == user['user_id']
    ).delete()
    db.commit()

    charged = charge_leave_for_new_contract(db, c)
    expected_rounded = round(engine_calc[year]['AL'])
    if expected_rounded > 0:
        assert charged[year]['AL'] == expected_rounded
        bal = db.query(LeaveBalance).filter_by(
            user_id=user['user_id'], year=year, leave_type='AL'
        ).first()
        assert bal is not None
        assert bal.balance == expected_rounded
        tx = (
            db.query(LeaveTransaction)
            .filter_by(
                user_id=user['user_id'],
                year=year,
                leave_type='AL',
                transaction_type=TX_CHARGE,
                reference_id=c.id,
            )
            .first()
        )
        assert tx is not None
        assert tx.amount == expected_rounded


def test_engine_mismatch_prevents_charge_mutation(
    db, make_user, path_engine, monkeypatch
):
    user, c, year, _, _ = _seed_contract(db, make_user)

    def _wrong(db, contract, *, annual_override=None, year_j=None):
        return {year: {'AL': 123.0, 'SL': 0.0}}

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover.entitlement_via_resolver_engine',
        _wrong,
    )
    before_bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user['user_id'])
        .count()
    )
    before_tx = (
        db.query(LeaveTransaction)
        .filter(LeaveTransaction.user_id == user['user_id'])
        .count()
    )
    with pytest.raises(EntitlementParityError):
        charge_leave_for_new_contract(db, c)
    db.rollback()
    assert (
        db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user['user_id'])
        .count()
        == before_bal
    )
    assert (
        db.query(LeaveTransaction)
        .filter(LeaveTransaction.user_id == user['user_id'])
        .count()
        == before_tx
    )


def test_invalid_path_falls_back_to_legacy(db, make_user, monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'not-a-path')
    _, c, _, _, _ = _seed_contract(db, make_user)
    out = calculate_prorated_leave_by_year(c, db=db, annual_override=30)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    assert out == legacy


def test_snapshot_override_used_not_live_base(db, make_user, path_engine):
    """annual_override/snapshot wins over any live membership base."""
    from tests.characterization.conftest import set_active_membership_annual_base

    user = make_user(department='4', region_code='NORMAL', balance_al=None)
    set_active_membership_annual_base(db, '4', 40)
    seed_leave_policy(db, {'4': 40}, region_applies={'4': False})
    year = __import__('jdatetime').date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    clear_user_contracts(db, user['user_id'])
    # Snapshot intentionally 25 while live base is 40
    c = make_contract(user['user_id'], '4', y_start, end=y_end, annual=25)
    db.add(c)
    db.commit()
    db.refresh(c)

    engine = entitlement_via_resolver_engine(db, c, annual_override=25)
    legacy = calculate_entitlement_by_year(db, c, annual_override=25)
    assert entitlements_match(legacy, engine)
    # Full-year coverage with annual 25 → 25, not live 40
    assert engine[year]['AL'] == 25.0
