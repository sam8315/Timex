"""
Phase 3 controlled cutover for contract AL entitlement calculation.

Wires Resolver → AnnualLeaveContext → Pure Engine into leave_service
``calculate_prorated_leave_by_year`` without changing mutation semantics.

Paths (env ``TIMEX_AL_ENTITLEMENT_PATH``):
  legacy — Current Behavior (default)
  shadow — dual-run; always return legacy; log mismatches (no fail)
  engine — Resolver+Engine; fail-closed parity vs legacy before return

Annual source for engine path: snapshot (``annual_override`` /
``contract.annual_leave_days``). Does not activate Target Rules.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import replace
from datetime import date
from typing import Any, Dict, Optional

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from web.services.leave_entitlement_engine import compute_annual_entitlement
from web.services.leave_entitlement_resolver import (
    resolve_annual_leave_context_for_contract,
)
from web.services.leave_entitlement_service import calculate_entitlement_by_year

logger = logging.getLogger(__name__)

PATH_LEGACY = 'legacy'
PATH_SHADOW = 'shadow'
PATH_ENGINE = 'engine'
_VALID_PATHS = frozenset({PATH_LEGACY, PATH_SHADOW, PATH_ENGINE})

# Compatibility: production split_contract_coverage_by_year uses today().year.
# Phase 3 adapter deliberately mirrors that coupling for Current Behavior parity.
_FLOAT_ABS_TOL = 1e-9


class EntitlementParityError(RuntimeError):
    """Raised in engine mode when legacy and Resolver/Engine results diverge."""


def get_entitlement_path() -> str:
    raw = (os.getenv('TIMEX_AL_ENTITLEMENT_PATH') or PATH_LEGACY).strip().lower()
    if raw not in _VALID_PATHS:
        logger.warning(
            'invalid TIMEX_AL_ENTITLEMENT_PATH=%r; using %s',
            raw,
            PATH_LEGACY,
        )
        return PATH_LEGACY
    return raw


def _legacy_entitlement(
    db: Session,
    contract: Contract,
    employee: Optional[Employee],
    annual_override: Optional[int],
) -> Dict[int, Dict[str, float]]:
    return calculate_entitlement_by_year(
        db, contract, employee=employee, annual_override=annual_override
    )


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

    ``year_j`` defaults to current Jalali year (Current Behavior coupling).
    """
    year = year_j if year_j is not None else jdatetime.date.today().year
    as_of = contract.start_date or date.today()

    ctx = resolve_annual_leave_context_for_contract(
        db,
        contract,
        year,
        as_of_date=as_of,
        annual_source='snapshot',
    )
    if ctx is None:
        return {}

    if annual_override is not None:
        ctx = replace(ctx, annual_days=float(annual_override))

    result = compute_annual_entitlement(ctx)
    return {year: {'AL': float(result.raw_amount), 'SL': 0.0}}


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


def _log_compare(
    *,
    path: str,
    contract: Contract,
    legacy: Dict[int, Dict[str, Any]],
    new: Dict[int, Dict[str, Any]],
    parity_ok: bool,
    mutation: str,
) -> None:
    years = sorted(set(legacy.keys()) | set(new.keys()))
    for year in years:
        legacy_al = float(legacy.get(year, {}).get('AL', 0.0) or 0.0)
        new_al = float(new.get(year, {}).get('AL', 0.0) or 0.0)
        logger.info(
            'al_entitlement_cutover path=%s parity=%s mutation=%s '
            'user_id=%s contract_id=%s year_j=%s annual_source=snapshot '
            'legacy_raw=%s new_raw=%s legacy_rounded=%s new_rounded=%s diff=%s',
            path,
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
    path = get_entitlement_path()

    if path == PATH_LEGACY:
        return _legacy_entitlement(db, contract, employee, annual_override)

    legacy = _legacy_entitlement(db, contract, employee, annual_override)

    try:
        new = entitlement_via_resolver_engine(
            db, contract, annual_override=annual_override
        )
    except Exception:
        if path == PATH_SHADOW:
            logger.exception(
                'al_entitlement_cutover path=shadow engine_error; '
                'using legacy user_id=%s contract_id=%s',
                contract.user_id,
                getattr(contract, 'id', None),
            )
            return legacy
        logger.exception(
            'al_entitlement_cutover path=engine engine_error; aborting '
            'user_id=%s contract_id=%s',
            contract.user_id,
            getattr(contract, 'id', None),
        )
        raise

    parity_ok = entitlements_match(legacy, new)

    if path == PATH_SHADOW:
        _log_compare(
            path=path,
            contract=contract,
            legacy=legacy,
            new=new,
            parity_ok=parity_ok,
            mutation='legacy',
        )
        return legacy

    # engine
    _log_compare(
        path=path,
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
