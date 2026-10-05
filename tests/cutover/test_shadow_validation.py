"""
Phase 4: Shadow Validation / Parity Evidence.

Shadow always returns legacy; observation (classify/metrics/log) never mutates.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from models.leave_balance import LeaveBalance
from models.leave_glossary import TX_CHARGE
from models.leave_transaction import LeaveTransaction
from web.services.leave_entitlement_cutover import (
    SHADOW_A_RAW,
    SHADOW_B_ROUNDED,
    SHADOW_C_COVERAGE,
    SHADOW_D_ANNUAL,
    SHADOW_G_RESOLVER,
    SHADOW_H_ENGINE,
    SHADOW_OK,
    ShadowOutcome,
    _EngineStageError,
    _ResolverStageError,
    classify_shadow_outcome,
    get_shadow_metrics,
    reset_shadow_metrics,
    resolve_prorated_entitlement,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    jalali_year_bounds_g,
)
from web.services.leave_service import charge_leave_for_new_contract
from tests.cutover.conftest import (
    clear_user_contracts,
    make_contract,
    seed_leave_policy,
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_shadow_metrics()
    yield
    reset_shadow_metrics()


@pytest.fixture
def path_shadow(monkeypatch):
    monkeypatch.setenv('TIMEX_AL_ENTITLEMENT_PATH', 'shadow')


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


# ---------------------------------------------------------------------------
# Unit: classify_shadow_outcome taxonomy
# ---------------------------------------------------------------------------


def test_classify_ok():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    new = {1404: {'AL': 10.0, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        new,
        meta={
            'year_j': 1404,
            'status': 'ok',
            'membership_code': 'CONTRACTUAL',
            'expected_membership': 'CONTRACTUAL',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
            'covered_days': 100,
        },
    )
    assert out.mismatch_type == SHADOW_OK
    assert out.diff == 0.0


def test_classify_a_raw_mismatch():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    new = {1404: {'AL': 10.5, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        new,
        meta={
            'year_j': 1404,
            'status': 'ok',
            'membership_code': 'CONTRACTUAL',
            'expected_membership': 'CONTRACTUAL',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
        },
    )
    assert out.mismatch_type == SHADOW_A_RAW
    assert out.diff == pytest.approx(0.5)


def test_classify_b_rounded_mismatch():
    # raw within abs_tol 1e-9 but round() differs (engineered boundary)
    legacy = {1404: {'AL': 10.5, 'SL': 0.0}}
    # Force B by making raw close enough for isclose with abs_tol... but
    # 10.5 vs 10.4999999999 may still fail isclose. Use identical raw via
    # meta path: inject same float string that rounds differently is hard.
    # Spec: raw close (isclose) but rounded differs.
    # 0.5 rounds half-to-even in Python 3: round(0.5)==0, round(1.5)==2.
    # Use values that are equal under isclose with a tiny epsilon that still
    # changes round — not possible if abs_tol is 1e-9 and round looks at
    # full float. Instead call classifier with raws that areclose:
    # math.isclose(10.4999999995, 10.5, abs_tol=1e-9) is True;
    # round(10.4999999995) == 10, round(10.5) == 10 in Python banker's?
    # round(10.5) == 10 (banker's even). So need different rounded.
    # round(1.5)=2, round(1.499999999) = 1 if far enough.
    # math.isclose(1.5, 1.5 - 1e-10, abs_tol=1e-9) → True
    # round(1.5)=2, round(1.5 - 1e-10)=1
    legacy = {1404: {'AL': 1.5, 'SL': 0.0}}
    new = {1404: {'AL': 1.5 - 1e-10, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        new,
        meta={
            'year_j': 1404,
            'status': 'ok',
            'membership_code': 'CONTRACTUAL',
            'expected_membership': 'CONTRACTUAL',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
        },
    )
    assert out.mismatch_type == SHADOW_B_ROUNDED
    assert out.legacy_rounded != out.engine_rounded


def test_classify_c_coverage_mismatch():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    new = {}  # empty vs nonempty
    out = classify_shadow_outcome(
        legacy,
        new,
        meta={
            'year_j': 1404,
            'status': 'empty',
            'membership_code': 'CONTRACTUAL',
            'expected_membership': 'CONTRACTUAL',
            'expected_annual': 30.0,
            'engine_annual': None,
        },
    )
    assert out.mismatch_type == SHADOW_C_COVERAGE


def test_classify_d_annual_source_mismatch():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    new = {1404: {'AL': 10.0, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        new,
        meta={
            'year_j': 1404,
            'status': 'ok',
            'membership_code': 'CONTRACTUAL',
            'expected_membership': 'CONTRACTUAL',
            'expected_annual': 25.0,
            'engine_annual': 40.0,
            'covered_days': 100,
        },
    )
    assert out.mismatch_type == SHADOW_D_ANNUAL


def test_classify_g_resolver_failure():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        None,
        meta={'year_j': 1404, 'membership_code': 'CONTRACTUAL'},
        failure=SHADOW_G_RESOLVER,
    )
    assert out.mismatch_type == SHADOW_G_RESOLVER
    assert out.resolver_engine_status == 'error'


def test_classify_h_engine_failure():
    legacy = {1404: {'AL': 10.0, 'SL': 0.0}}
    out = classify_shadow_outcome(
        legacy,
        None,
        meta={'year_j': 1404, 'membership_code': 'CONTRACTUAL'},
        failure=SHADOW_H_ENGINE,
    )
    assert out.mismatch_type == SHADOW_H_ENGINE
    assert out.resolver_engine_status == 'error'


def test_classify_precedence_g_over_raw():
    """Failure G wins even if legacy/new would also mismatch."""
    out = classify_shadow_outcome(
        {1404: {'AL': 1.0}},
        {1404: {'AL': 9.0}},
        meta={'year_j': 1404},
        failure=SHADOW_G_RESOLVER,
    )
    assert out.mismatch_type == SHADOW_G_RESOLVER


def test_classify_precedence_c_over_a():
    out = classify_shadow_outcome(
        {1404: {'AL': 1.0}},
        {1405: {'AL': 9.0}},
        meta={
            'year_j': 1404,
            'status': 'ok',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
            'membership_code': 'X',
            'expected_membership': 'X',
        },
    )
    assert out.mismatch_type == SHADOW_C_COVERAGE


# ---------------------------------------------------------------------------
# Unit: metrics
# ---------------------------------------------------------------------------


def test_metrics_ok_increments_match_not_mismatch():
    reset_shadow_metrics()
    outcome = classify_shadow_outcome(
        {1404: {'AL': 5.0}},
        {1404: {'AL': 5.0}},
        meta={
            'year_j': 1404,
            'status': 'ok',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
            'membership_code': 'C',
            'expected_membership': 'C',
        },
    )
    from web.services.leave_entitlement_cutover import _record_shadow_metrics

    _record_shadow_metrics(outcome)
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['shadow_match'] == 1
    assert m['shadow_mismatch'] == 0
    assert m['resolver_failure'] == 0
    assert m['engine_failure'] == 0


def test_metrics_a_increments_mismatch_and_raw():
    from web.services.leave_entitlement_cutover import _record_shadow_metrics

    reset_shadow_metrics()
    outcome = classify_shadow_outcome(
        {1404: {'AL': 5.0}},
        {1404: {'AL': 6.0}},
        meta={
            'year_j': 1404,
            'status': 'ok',
            'expected_annual': 30.0,
            'engine_annual': 30.0,
            'membership_code': 'C',
            'expected_membership': 'C',
        },
    )
    assert outcome.mismatch_type == SHADOW_A_RAW
    _record_shadow_metrics(outcome)
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['shadow_match'] == 0
    assert m['shadow_mismatch'] == 1
    assert m['raw_mismatch'] == 1
    assert m['resolver_failure'] == 0


def test_metrics_g_h_do_not_increment_shadow_mismatch():
    from web.services.leave_entitlement_cutover import _record_shadow_metrics

    reset_shadow_metrics()
    g = classify_shadow_outcome(
        {1404: {'AL': 1.0}}, None, meta={'year_j': 1404}, failure=SHADOW_G_RESOLVER
    )
    h = classify_shadow_outcome(
        {1404: {'AL': 1.0}}, None, meta={'year_j': 1404}, failure=SHADOW_H_ENGINE
    )
    _record_shadow_metrics(g)
    _record_shadow_metrics(h)
    m = get_shadow_metrics()
    assert m['shadow_total'] == 2
    assert m['shadow_match'] == 0
    assert m['shadow_mismatch'] == 0
    assert m['resolver_failure'] == 1
    assert m['engine_failure'] == 1


def test_reset_and_get_shadow_metrics():
    from web.services.leave_entitlement_cutover import _record_shadow_metrics

    _record_shadow_metrics(
        ShadowOutcome(
            mismatch_type=SHADOW_OK,
            membership_code='C',
            year_j=1404,
            legacy_raw=1.0,
            engine_raw=1.0,
            legacy_rounded=1,
            engine_rounded=1,
            diff=0.0,
            resolver_engine_status='ok',
        )
    )
    assert get_shadow_metrics()['shadow_total'] >= 1
    reset_shadow_metrics()
    m = get_shadow_metrics()
    assert m['shadow_total'] == 0
    assert m['shadow_match'] == 0
    assert m['shadow_mismatch'] == 0
    assert m['resolver_failure'] == 0
    assert m['engine_failure'] == 0
    assert m['raw_mismatch'] == 0
    assert m['rounded_mismatch'] == 0
    assert m['coverage_mismatch'] == 0


# ---------------------------------------------------------------------------
# Integration: shadow path
# ---------------------------------------------------------------------------


def test_shadow_success_returns_legacy_and_metrics_ok(
    db, make_user, path_shadow
):
    _, c, year, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    assert year in out
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['shadow_match'] == 1
    assert m['shadow_mismatch'] == 0


def test_shadow_mismatch_returns_legacy(
    db, make_user, path_shadow, monkeypatch
):
    _, c, year, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)

    def _wrong(db, contract, *, annual_override=None, year_j=None):
        return (
            {year: {'AL': 999.0, 'SL': 0.0}},
            {
                'year_j': year,
                'membership_code': 'CONTRACTUAL',
                'expected_membership': 'CONTRACTUAL',
                'expected_annual': 30.0,
                'engine_annual': 30.0,
                'covered_days': 1,
                'status': 'ok',
                'ctx': None,
            },
        )

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._compute_engine_entitlement',
        _wrong,
    )
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['shadow_match'] == 0
    assert m['shadow_mismatch'] == 1
    assert m['raw_mismatch'] == 1


def test_shadow_resolver_exception_returns_legacy(
    db, make_user, path_shadow, monkeypatch
):
    _, c, _, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)

    def _boom(*args, **kwargs):
        raise _ResolverStageError('resolver down')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._compute_engine_entitlement',
        _boom,
    )
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['resolver_failure'] == 1
    assert m['shadow_mismatch'] == 0


def test_shadow_engine_exception_returns_legacy(
    db, make_user, path_shadow, monkeypatch
):
    _, c, _, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)

    def _boom(*args, **kwargs):
        raise _EngineStageError('engine boom')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._compute_engine_entitlement',
        _boom,
    )
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1
    assert m['engine_failure'] == 1
    assert m['shadow_mismatch'] == 0


def test_shadow_logging_exception_does_not_affect_legacy(
    db, make_user, path_shadow, monkeypatch
):
    _, c, _, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)

    def _log_boom(*args, **kwargs):
        raise RuntimeError('logger broken')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._log_shadow_outcome',
        _log_boom,
    )
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy


def test_shadow_classifier_exception_returns_legacy(
    db, make_user, path_shadow, monkeypatch
):
    _, c, _, _, _ = _seed_contract(db, make_user)
    legacy = calculate_entitlement_by_year(db, c, annual_override=30)

    def _cls_boom(*args, **kwargs):
        raise RuntimeError('classifier broken')

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover.classify_shadow_outcome',
        _cls_boom,
    )
    out = resolve_prorated_entitlement(db, c, annual_override=30)
    assert out == legacy
    m = get_shadow_metrics()
    assert m['shadow_total'] == 1


def test_shadow_charge_mutation_isolation_with_forced_mismatch(
    db, make_user, path_shadow, monkeypatch
):
    """
    Forced engine mismatch under shadow: charge still uses legacy calc;
    engine creates no extra LeaveBalance / LeaveTransaction writes.
    """
    user, c, year, _, _ = _seed_contract(db, make_user, annual=30, end_offset=60)
    legacy_calc = calculate_entitlement_by_year(db, c, annual_override=30)
    expected_rounded = round(legacy_calc[year]['AL'])

    def _wrong(db, contract, *, annual_override=None, year_j=None):
        return (
            {year: {'AL': 999.0, 'SL': 0.0}},
            {
                'year_j': year,
                'membership_code': 'CONTRACTUAL',
                'expected_membership': 'CONTRACTUAL',
                'expected_annual': 30.0,
                'engine_annual': 30.0,
                'covered_days': 1,
                'status': 'ok',
                'ctx': None,
            },
        )

    monkeypatch.setattr(
        'web.services.leave_entitlement_cutover._compute_engine_entitlement',
        _wrong,
    )

    db.query(LeaveBalance).filter(LeaveBalance.user_id == user['user_id']).delete()
    db.query(LeaveTransaction).filter(
        LeaveTransaction.user_id == user['user_id']
    ).delete()
    db.commit()

    charged = charge_leave_for_new_contract(db, c)
    assert charged[year]['AL'] == expected_rounded
    assert charged[year]['AL'] != 999

    bals = (
        db.query(LeaveBalance)
        .filter_by(user_id=user['user_id'], year=year, leave_type='AL')
        .all()
    )
    assert len(bals) == 1
    assert bals[0].balance == expected_rounded

    txs = (
        db.query(LeaveTransaction)
        .filter_by(
            user_id=user['user_id'],
            year=year,
            leave_type='AL',
            transaction_type=TX_CHARGE,
            reference_id=c.id,
        )
        .all()
    )
    assert len(txs) == 1
    assert txs[0].amount == expected_rounded

    # No phantom 999 charge from engine path
    weird = (
        db.query(LeaveTransaction)
        .filter(
            LeaveTransaction.user_id == user['user_id'],
            LeaveTransaction.amount == 999,
        )
        .count()
    )
    assert weird == 0

    m = get_shadow_metrics()
    assert m['shadow_total'] >= 1
    assert m['shadow_mismatch'] >= 1
    assert m['raw_mismatch'] >= 1
