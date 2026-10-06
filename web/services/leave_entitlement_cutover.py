"""
Phase 3/4 controlled cutover for contract AL entitlement calculation.

Wires Resolver → AnnualLeaveContext → Pure Engine into leave_service
``calculate_prorated_leave_by_year`` without changing mutation semantics.

Paths (env ``TIMEX_AL_ENTITLEMENT_PATH``):
  engine — Resolver+Engine; fail-closed parity vs legacy (Phase 5 default)
  shadow — dual-run; always return legacy; classify/log/metrics (no fail)
  legacy — Current Behavior formula path (rollback / explicit opt-in)

Annual source for engine/shadow compare path: snapshot
(``annual_override`` / ``contract.annual_leave_days``).

Phase 4 shadow metrics are in-process only (not global across workers).
Production evidence aggregation must use structured logs.
Rollback: set TIMEX_AL_ENTITLEMENT_PATH=legacy (or shadow) and restart.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from web.services.leave_entitlement_engine import compute_annual_entitlement
from web.services.leave_entitlement_resolver import (
    resolve_annual_leave_context_for_contract,
)
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    resolve_membership_code_for_policy,
)
from web.services import membership_semantics as msem

logger = logging.getLogger(__name__)

PATH_LEGACY = 'legacy'
PATH_SHADOW = 'shadow'
PATH_ENGINE = 'engine'
_VALID_PATHS = frozenset({PATH_LEGACY, PATH_SHADOW, PATH_ENGINE})

# Compatibility: production split_contract_coverage_by_year uses today().year.
# Phase 3 adapter deliberately mirrors that coupling for Current Behavior parity.
_FLOAT_ABS_TOL = 1e-9

# ShadowOutcome mismatch type codes (deterministic classification)
SHADOW_OK = 'OK'
SHADOW_A_RAW = 'A'
SHADOW_B_ROUNDED = 'B'
SHADOW_C_COVERAGE = 'C'
SHADOW_D_ANNUAL = 'D'
SHADOW_E_REGION = 'E'
SHADOW_F_MEMBERSHIP = 'F'
SHADOW_G_RESOLVER = 'G'
SHADOW_H_ENGINE = 'H'

_SHADOW_MISMATCH_TYPES = frozenset({
    SHADOW_A_RAW,
    SHADOW_B_ROUNDED,
    SHADOW_C_COVERAGE,
    SHADOW_D_ANNUAL,
    SHADOW_E_REGION,
    SHADOW_F_MEMBERSHIP,
})


class EntitlementParityError(RuntimeError):
    """Raised in engine mode when legacy and Resolver/Engine results diverge."""


class _ResolverStageError(Exception):
    """Internal: failure while building Context (ShadowOutcome G)."""


class _EngineStageError(Exception):
    """Internal: failure inside Pure Engine (ShadowOutcome H)."""


@dataclass(frozen=True)
class ShadowOutcome:
    """Structured Phase 4 shadow comparison result (observation only)."""

    mismatch_type: str
    membership_code: str
    year_j: Optional[int]
    legacy_raw: float
    engine_raw: float
    legacy_rounded: int
    engine_rounded: int
    diff: float
    resolver_engine_status: str  # ok | empty | error
    covered_days_engine: Optional[int] = None
    expected_annual: Optional[float] = None
    engine_annual: Optional[float] = None


_metrics_lock = threading.Lock()
_shadow_metrics: Dict[str, int] = {
    'shadow_total': 0,
    'shadow_match': 0,
    'shadow_mismatch': 0,
    'resolver_failure': 0,
    'engine_failure': 0,
    'raw_mismatch': 0,
    'rounded_mismatch': 0,
    'coverage_mismatch': 0,
}


def get_shadow_metrics() -> Dict[str, int]:
    """Return a copy of in-process shadow counters (not cross-worker)."""
    with _metrics_lock:
        return dict(_shadow_metrics)


def reset_shadow_metrics() -> None:
    """Reset in-process shadow counters (tests / local evidence only)."""
    with _metrics_lock:
        for key in _shadow_metrics:
            _shadow_metrics[key] = 0


def _bump_metric(name: str, delta: int = 1) -> None:
    try:
        with _metrics_lock:
            if name in _shadow_metrics:
                _shadow_metrics[name] += delta
    except Exception:
        # Metrics must never affect business flow.
        pass


def get_entitlement_path() -> str:
    """
    Entitlement cutover path (env only — no DB gate).

    Phase 5 default is ``engine`` when env is unset.
    Invalid values fall back to ``legacy`` (safe rollback semantics).

    For DB-aware promotion safety (Rule↔PolicyValue mirror conflicts),
    use ``get_effective_entitlement_path(db)``.
    """
    raw = (os.getenv('TIMEX_AL_ENTITLEMENT_PATH') or PATH_ENGINE).strip().lower()
    if raw not in _VALID_PATHS:
        logger.warning(
            'invalid TIMEX_AL_ENTITLEMENT_PATH=%r; using %s',
            raw,
            PATH_LEGACY,
        )
        return PATH_LEGACY
    return raw


def get_effective_entitlement_path(db: Optional[Session] = None) -> str:
    """
    Env path with promotion safety gate.

    If env requests ``engine`` but annual policy mirror conflicts remain
    (e.g. physician Rule base 0 vs orphaned annual_leave_dept_5=30),
    downgrade to ``shadow`` so Production never mutates via engine while
    live policy sources diverge.
    """
    path = get_entitlement_path()
    if path != PATH_ENGINE or db is None:
        return path
    try:
        from web.services.annual_leave_policy_authority import (
            engine_promotion_blockers,
        )

        blockers = engine_promotion_blockers(db)
    except Exception:
        logger.exception(
            'al_entitlement_cutover promotion_gate_error; downgrading '
            'engine→shadow'
        )
        return PATH_SHADOW
    if blockers:
        try:
            logger.warning(
                'al_entitlement_cutover engine_promotion_blocked '
                'downgrade=shadow blockers=%s',
                '; '.join(blockers[:10]),
            )
        except Exception:
            pass
        return PATH_SHADOW
    return PATH_ENGINE


def _legacy_entitlement(
    db: Session,
    contract: Contract,
    employee: Optional[Employee],
    annual_override: Optional[int],
) -> Dict[int, Dict[str, float]]:
    return calculate_entitlement_by_year(
        db, contract, employee=employee, annual_override=annual_override
    )


def _engine_years_for_contract(
    db: Session,
    contract: Contract,
    year_j: Optional[int],
) -> List[int]:
    """
    Years to resolve via engine.

    Explicit ``year_j`` → single year (tests / diagnostics).
    Otherwise follow ``split_contract_coverage_by_year`` (conscript = full period).
    """
    if year_j is not None:
        return [int(year_j)]
    from web.services.leave_entitlement_service import split_contract_coverage_by_year

    years = [y for y, _s, _e in split_contract_coverage_by_year(contract, db=db)]
    return years or [jdatetime.date.today().year]


def _compute_engine_entitlement(
    db: Session,
    contract: Contract,
    *,
    annual_override: Optional[int] = None,
    year_j: Optional[int] = None,
) -> Tuple[Dict[int, Dict[str, float]], Dict[str, Any]]:
    """
    Snapshot Resolver → Pure Engine.

    Returns (entitlement_dict, meta).
    Raises _ResolverStageError or _EngineStageError for stage isolation.
    """
    years = _engine_years_for_contract(db, contract, year_j)
    as_of = contract.start_date or date.today()
    if msem.is_conscript(db, contract.contract_type_code):
        as_of = msem.resolve_conscript_leave_start(db, contract) or as_of
    expected_membership = resolve_membership_code_for_policy(
        contract.contract_type_code
    )
    expected_annual = (
        float(annual_override)
        if annual_override is not None
        else float(contract.annual_leave_days)
    )

    out: Dict[int, Dict[str, float]] = {}
    last_ctx = None
    total_covered = 0
    for year in years:
        try:
            ctx = resolve_annual_leave_context_for_contract(
                db,
                contract,
                year,
                as_of_date=as_of,
                annual_source='snapshot',
            )
        except Exception as exc:
            raise _ResolverStageError(str(exc)) from exc

        if ctx is None:
            continue

        try:
            if annual_override is not None:
                ctx = replace(ctx, annual_days=float(annual_override))
            result = compute_annual_entitlement(ctx)
        except Exception as exc:
            raise _EngineStageError(str(exc)) from exc

        out[year] = {'AL': float(result.raw_amount), 'SL': 0.0}
        last_ctx = ctx
        total_covered += int(result.covered_days)

    if not out:
        meta = {
            'year_j': years[0] if years else jdatetime.date.today().year,
            'membership_code': expected_membership,
            'expected_annual': expected_annual,
            'engine_annual': None,
            'covered_days': None,
            'status': 'empty',
            'ctx': None,
        }
        return {}, meta

    meta = {
        'year_j': years[0],
        'years': years,
        'membership_code': last_ctx.membership_code if last_ctx else expected_membership,
        'expected_annual': expected_annual,
        'engine_annual': float(last_ctx.annual_days) if last_ctx else expected_annual,
        'covered_days': total_covered,
        'status': 'ok',
        'ctx': last_ctx,
        'expected_membership': expected_membership,
    }
    return out, meta


def entitlement_via_resolver_engine(
    db: Session,
    contract: Contract,
    *,
    annual_override: Optional[int] = None,
    year_j: Optional[int] = None,
) -> Dict[int, Dict[str, float]]:
    """
    Snapshot-based Resolver → Pure Engine → same dict shape as
    ``calculate_entitlement_by_year``.

    When ``year_j`` is omitted, years follow coverage split
    (conscript: full service period; others: current Jalali year).
    """
    result, _meta = _compute_engine_entitlement(
        db, contract, annual_override=annual_override, year_j=year_j
    )
    return result


def entitlements_match(
    legacy: Dict[int, Dict[str, Any]],
    new: Dict[int, Dict[str, Any]],
) -> bool:
    years = set(legacy.keys()) | set(new.keys())
    for year in years:
        legacy_al = float(legacy.get(year, {}).get('AL', 0.0) or 0.0)
        new_al = float(new.get(year, {}).get('AL', 0.0) or 0.0)
        if not math.isclose(legacy_al, new_al, rel_tol=0.0, abs_tol=_FLOAT_ABS_TOL):
            return False
        if round(legacy_al) != round(new_al):
            return False
    return True


def classify_shadow_outcome(
    legacy: Dict[int, Dict[str, Any]],
    new: Optional[Dict[int, Dict[str, Any]]],
    *,
    meta: Optional[Dict[str, Any]] = None,
    failure: Optional[str] = None,
) -> ShadowOutcome:
    """
    Deterministic ShadowOutcome classification.

    Precedence (first match wins):
      G resolver failure
      H engine failure
      C coverage mismatch (year-key / empty-vs-nonempty)
      D annual source mismatch (snapshot/override invariant)
      F membership mismatch
      E region mismatch (unexpected on snapshot path; meta flag only)
      A raw mismatch
      B rounded mismatch
      OK
    """
    meta = meta or {}
    membership = str(
        meta.get('membership_code')
        or meta.get('expected_membership')
        or ''
    )
    year_j = meta.get('year_j')
    if year_j is None and legacy:
        year_j = sorted(legacy.keys())[0]
    if year_j is None and new:
        year_j = sorted(new.keys())[0]

    def _al(d: Optional[Dict[int, Dict[str, Any]]], y: Optional[int]) -> float:
        if not d or y is None:
            # aggregate first year if present
            if d:
                y = sorted(d.keys())[0]
            else:
                return 0.0
        return float(d.get(y, {}).get('AL', 0.0) or 0.0)

    if failure == SHADOW_G_RESOLVER:
        return ShadowOutcome(
            mismatch_type=SHADOW_G_RESOLVER,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=_al(legacy, year_j),
            engine_raw=0.0,
            legacy_rounded=round(_al(legacy, year_j)),
            engine_rounded=0,
            diff=0.0 - _al(legacy, year_j),
            resolver_engine_status='error',
            expected_annual=meta.get('expected_annual'),
            engine_annual=None,
        )

    if failure == SHADOW_H_ENGINE:
        return ShadowOutcome(
            mismatch_type=SHADOW_H_ENGINE,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=_al(legacy, year_j),
            engine_raw=0.0,
            legacy_rounded=round(_al(legacy, year_j)),
            engine_rounded=0,
            diff=0.0 - _al(legacy, year_j),
            resolver_engine_status='error',
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    assert new is not None
    status = str(meta.get('status') or ('empty' if not new else 'ok'))
    legacy_raw = _al(legacy, year_j)
    engine_raw = _al(new, year_j)
    legacy_rounded = round(legacy_raw)
    engine_rounded = round(engine_raw)
    diff = engine_raw - legacy_raw

    # C — coverage: year keys or empty-vs-nonempty
    if set(legacy.keys()) != set(new.keys()) or (bool(legacy) != bool(new)):
        return ShadowOutcome(
            mismatch_type=SHADOW_C_COVERAGE,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    # D — annual source / override invariant
    expected_annual = meta.get('expected_annual')
    engine_annual = meta.get('engine_annual')
    if (
        expected_annual is not None
        and engine_annual is not None
        and not math.isclose(
            float(expected_annual),
            float(engine_annual),
            rel_tol=0.0,
            abs_tol=_FLOAT_ABS_TOL,
        )
    ):
        return ShadowOutcome(
            mismatch_type=SHADOW_D_ANNUAL,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=float(expected_annual),
            engine_annual=float(engine_annual),
        )

    # F — membership identity
    expected_membership = meta.get('expected_membership')
    if (
        expected_membership is not None
        and meta.get('membership_code') is not None
        and str(expected_membership) != str(meta.get('membership_code'))
    ):
        return ShadowOutcome(
            mismatch_type=SHADOW_F_MEMBERSHIP,
            membership_code=str(meta.get('membership_code')),
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    # E — region (unexpected on snapshot path; only if explicitly flagged)
    if meta.get('region_mismatch'):
        return ShadowOutcome(
            mismatch_type=SHADOW_E_REGION,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    # A — raw
    if not math.isclose(legacy_raw, engine_raw, rel_tol=0.0, abs_tol=_FLOAT_ABS_TOL):
        return ShadowOutcome(
            mismatch_type=SHADOW_A_RAW,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    # B — rounded (raw close but rounded differs)
    if legacy_rounded != engine_rounded:
        return ShadowOutcome(
            mismatch_type=SHADOW_B_ROUNDED,
            membership_code=membership,
            year_j=year_j,
            legacy_raw=legacy_raw,
            engine_raw=engine_raw,
            legacy_rounded=legacy_rounded,
            engine_rounded=engine_rounded,
            diff=diff,
            resolver_engine_status=status,
            covered_days_engine=meta.get('covered_days'),
            expected_annual=meta.get('expected_annual'),
            engine_annual=meta.get('engine_annual'),
        )

    return ShadowOutcome(
        mismatch_type=SHADOW_OK,
        membership_code=membership,
        year_j=year_j,
        legacy_raw=legacy_raw,
        engine_raw=engine_raw,
        legacy_rounded=legacy_rounded,
        engine_rounded=engine_rounded,
        diff=diff,
        resolver_engine_status=status,
        covered_days_engine=meta.get('covered_days'),
        expected_annual=meta.get('expected_annual'),
        engine_annual=meta.get('engine_annual'),
    )


def _record_shadow_metrics(outcome: ShadowOutcome) -> None:
    _bump_metric('shadow_total')
    code = outcome.mismatch_type
    if code == SHADOW_OK:
        _bump_metric('shadow_match')
        return
    if code == SHADOW_G_RESOLVER:
        _bump_metric('resolver_failure')
        return
    if code == SHADOW_H_ENGINE:
        _bump_metric('engine_failure')
        return
    if code in _SHADOW_MISMATCH_TYPES:
        _bump_metric('shadow_mismatch')
        if code == SHADOW_A_RAW:
            _bump_metric('raw_mismatch')
        elif code == SHADOW_B_ROUNDED:
            _bump_metric('rounded_mismatch')
        elif code == SHADOW_C_COVERAGE:
            _bump_metric('coverage_mismatch')


def _log_shadow_outcome(
    contract: Contract,
    outcome: ShadowOutcome,
) -> None:
    try:
        logger.info(
            'al_entitlement_shadow user_id=%s contract_id=%s year_j=%s '
            'membership_code=%s legacy_raw=%s engine_raw=%s '
            'legacy_rounded=%s engine_rounded=%s diff=%s mismatch_type=%s '
            'resolver_engine_status=%s mutation=legacy annual_source=snapshot',
            contract.user_id,
            getattr(contract, 'id', None),
            outcome.year_j,
            outcome.membership_code,
            outcome.legacy_raw,
            outcome.engine_raw,
            outcome.legacy_rounded,
            outcome.engine_rounded,
            outcome.diff,
            outcome.mismatch_type,
            outcome.resolver_engine_status,
        )
    except Exception:
        # logging failure != business failure
        pass


def _log_compare_engine(
    *,
    contract: Contract,
    legacy: Dict[int, Dict[str, Any]],
    new: Dict[int, Dict[str, Any]],
    parity_ok: bool,
    mutation: str,
) -> None:
    """Phase 3 engine-path diagnostic log (isolated)."""
    try:
        years = sorted(set(legacy.keys()) | set(new.keys()))
        for year in years:
            legacy_al = float(legacy.get(year, {}).get('AL', 0.0) or 0.0)
            new_al = float(new.get(year, {}).get('AL', 0.0) or 0.0)
            logger.info(
                'al_entitlement_cutover path=engine parity=%s mutation=%s '
                'user_id=%s contract_id=%s year_j=%s annual_source=snapshot '
                'legacy_raw=%s new_raw=%s legacy_rounded=%s new_rounded=%s diff=%s',
                'ok' if parity_ok else 'mismatch',
                mutation,
                contract.user_id,
                getattr(contract, 'id', None),
                year,
                legacy_al,
                new_al,
                round(legacy_al),
                round(new_al),
                new_al - legacy_al,
            )
    except Exception:
        pass


def _shadow_compare_and_return_legacy(
    db: Session,
    contract: Contract,
    legacy: Dict[int, Dict[str, float]],
    *,
    annual_override: Optional[int],
) -> Dict[int, Dict[str, float]]:
    """
    Shadow path: compare Resolver/Engine vs legacy, observe, always return legacy.

    Observation failures never change the returned legacy result.
    """
    new: Optional[Dict[int, Dict[str, float]]] = None
    meta: Dict[str, Any] = {
        'expected_membership': resolve_membership_code_for_policy(
            contract.contract_type_code
        ),
        'expected_annual': (
            float(annual_override)
            if annual_override is not None
            else float(contract.annual_leave_days)
        ),
        'year_j': jdatetime.date.today().year,
    }
    failure: Optional[str] = None

    try:
        new, meta = _compute_engine_entitlement(
            db, contract, annual_override=annual_override
        )
    except _ResolverStageError:
        failure = SHADOW_G_RESOLVER
        try:
            logger.exception(
                'al_entitlement_shadow resolver_failure user_id=%s contract_id=%s '
                'mutation=legacy',
                contract.user_id,
                getattr(contract, 'id', None),
            )
        except Exception:
            pass
    except _EngineStageError:
        failure = SHADOW_H_ENGINE
        try:
            logger.exception(
                'al_entitlement_shadow engine_failure user_id=%s contract_id=%s '
                'mutation=legacy',
                contract.user_id,
                getattr(contract, 'id', None),
            )
        except Exception:
            pass
    except Exception:
        # Treat unexpected wrapper failures as resolver-stage for isolation.
        failure = SHADOW_G_RESOLVER
        try:
            logger.exception(
                'al_entitlement_shadow resolver_failure user_id=%s contract_id=%s '
                'mutation=legacy',
                contract.user_id,
                getattr(contract, 'id', None),
            )
        except Exception:
            pass

    try:
        outcome = classify_shadow_outcome(
            legacy, new, meta=meta, failure=failure
        )
    except Exception:
        # Classifier failure must not break legacy return.
        try:
            logger.exception(
                'al_entitlement_shadow classifier_error user_id=%s contract_id=%s '
                'mutation=legacy',
                contract.user_id,
                getattr(contract, 'id', None),
            )
        except Exception:
            pass
        _bump_metric('shadow_total')
        return legacy

    try:
        _record_shadow_metrics(outcome)
    except Exception:
        pass

    try:
        _log_shadow_outcome(contract, outcome)
    except Exception:
        pass

    return legacy


def resolve_prorated_entitlement(
    db: Session,
    contract: Contract,
    *,
    employee: Optional[Employee] = None,
    annual_override: Optional[int] = None,
) -> Dict[int, Dict[str, float]]:
    """
    Path-switched entitlement for leave_service.calculate_prorated_leave_by_year.

    Never mutates LeaveBalance / LeaveTransaction.
    """
    path = get_effective_entitlement_path(db)

    if path == PATH_LEGACY:
        return _legacy_entitlement(db, contract, employee, annual_override)

    legacy = _legacy_entitlement(db, contract, employee, annual_override)

    if path == PATH_SHADOW:
        return _shadow_compare_and_return_legacy(
            db, contract, legacy, annual_override=annual_override
        )

    # engine (fail-closed parity; blocked while Rule↔mirror conflicts exist)
    try:
        new = entitlement_via_resolver_engine(
            db, contract, annual_override=annual_override
        )
    except Exception:
        logger.exception(
            'al_entitlement_cutover path=engine engine_error; aborting '
            'user_id=%s contract_id=%s',
            contract.user_id,
            getattr(contract, 'id', None),
        )
        raise

    parity_ok = entitlements_match(legacy, new)
    _log_compare_engine(
        contract=contract,
        legacy=legacy,
        new=new,
        parity_ok=parity_ok,
        mutation='engine' if parity_ok else 'skipped',
    )
    if not parity_ok:
        raise EntitlementParityError(
            f'AL entitlement parity mismatch contract_id={getattr(contract, "id", None)} '
            f'user_id={contract.user_id} legacy={legacy!r} new={new!r}'
        )
    return new
