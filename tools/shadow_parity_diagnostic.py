#!/usr/bin/env python
"""
Read-only Phase 4 Shadow parity diagnostic.

Path (same as production shadow compare, without mutation / metrics / log side effects):

  Contract + Employee (SELECT)
      → calculate_entitlement_by_year  (legacy)
      → _compute_engine_entitlement    (Resolver → Pure Engine)
      → classify_shadow_outcome
      → stdout report

Guarantees:
  - no db.commit()
  - no INSERT/UPDATE/DELETE
  - session always rolled back / closed
  - per-contract exception isolation
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow `python tools/shadow_parity_diagnostic.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import jdatetime  # noqa: E402

from database.engine import SessionLocal  # noqa: E402
from models.contract import Contract  # noqa: E402
from models.employee import Employee  # noqa: E402
from web.services.leave_entitlement_cutover import (  # noqa: E402
    SHADOW_A_RAW,
    SHADOW_B_ROUNDED,
    SHADOW_C_COVERAGE,
    SHADOW_D_ANNUAL,
    SHADOW_E_REGION,
    SHADOW_F_MEMBERSHIP,
    SHADOW_G_RESOLVER,
    SHADOW_H_ENGINE,
    SHADOW_OK,
    _EngineStageError,
    _ResolverStageError,
    _compute_engine_entitlement,
    classify_shadow_outcome,
)
from web.services.leave_entitlement_service import (  # noqa: E402
    calculate_entitlement_by_year,
    resolve_annual_leave_days,
)

_MISMATCH_CODES = (
    SHADOW_A_RAW,
    SHADOW_B_ROUNDED,
    SHADOW_C_COVERAGE,
    SHADOW_D_ANNUAL,
    SHADOW_E_REGION,
    SHADOW_F_MEMBERSHIP,
    SHADOW_G_RESOLVER,
    SHADOW_H_ENGINE,
)


def _al_for_year(ent: Dict[int, Dict[str, Any]], year_j: int) -> float:
    return float(ent.get(year_j, {}).get('AL', 0.0) or 0.0)


def _empty_membership_stats() -> Dict[str, Any]:
    return {
        'total': 0,
        'OK': 0,
        'mismatch': 0,  # A–F only
        'resolver_failure': 0,
        'engine_failure': 0,
        'by_type': Counter({c: 0 for c in (SHADOW_OK,) + _MISMATCH_CODES}),
        'errors': 0,  # unexpected wrapper failures outside G/H
    }


def _classify_one(db, contract: Contract, year_j: int) -> Dict[str, Any]:
    """
    One contract: legacy + engine + Phase 4 classifier.
    Never mutates DB; never bumps shadow metrics / production shadow logs.
    """
    employee = (
        db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    )
    region = employee.region_code if employee else None
    snapshot = int(contract.annual_leave_days)
    live = int(
        resolve_annual_leave_days(
            db, contract.contract_type_code, region_code=region
        )
    )

    legacy = calculate_entitlement_by_year(
        db, contract, employee=employee, annual_override=snapshot
    )

    new: Optional[Dict[int, Dict[str, float]]] = None
    meta: Dict[str, Any] = {
        'year_j': year_j,
        'membership_code': str(contract.contract_type_code),
        'expected_annual': float(snapshot),
    }
    failure: Optional[str] = None
    resolver_status = 'n/a'
    engine_status = 'n/a'

    try:
        new, meta = _compute_engine_entitlement(
            db,
            contract,
            annual_override=snapshot,
            year_j=year_j,
        )
        resolver_status = str(meta.get('status') or 'ok')
        engine_status = 'ok' if meta.get('status') == 'ok' else str(
            meta.get('status') or 'empty'
        )
    except _ResolverStageError as exc:
        failure = SHADOW_G_RESOLVER
        resolver_status = f'error:{exc}'
        engine_status = 'skipped'
    except _EngineStageError as exc:
        failure = SHADOW_H_ENGINE
        resolver_status = str(meta.get('status') or 'ok')
        engine_status = f'error:{exc}'
    except Exception as exc:
        failure = SHADOW_G_RESOLVER
        resolver_status = f'error:{type(exc).__name__}:{exc}'
        engine_status = 'skipped'

    outcome = classify_shadow_outcome(
        legacy, new, meta=meta, failure=failure
    )

    engine_raw = float(outcome.engine_raw)
    engine_rounded = int(outcome.engine_rounded)
    if new is not None and year_j in new:
        engine_raw = _al_for_year(new, year_j)
        engine_rounded = round(engine_raw)

    return {
        'contract_id': contract.id,
        'user_id': contract.user_id,
        'membership_code': str(contract.contract_type_code),
        'annual_snapshot': snapshot,
        'live_annual': live,
        'legacy_raw': float(outcome.legacy_raw),
        'engine_raw': engine_raw,
        'engine_rounded': engine_rounded,
        'mismatch_type': outcome.mismatch_type,
        'resolver_status': resolver_status,
        'engine_status': engine_status,
        'resolver_engine_status': outcome.resolver_engine_status,
        'snapshot_eq_live': snapshot == live,
        'year_j': year_j,
    }


def run(codes: List[str], limit_per_code: Optional[int] = None) -> int:
    year_j = jdatetime.date.today().year
    by_membership: Dict[str, Dict[str, Any]] = {
        c: _empty_membership_stats() for c in codes
    }
    grand = _empty_membership_stats()

    db = SessionLocal()
    exit_code = 0
    try:
        print(f'# shadow_parity_diagnostic year_j={year_j} codes={codes}')
        print('# READ-ONLY: no commit; session will be rolled back')
        print()

        for code in codes:
            q = (
                db.query(Contract)
                .filter(Contract.contract_type_code == code)
                .order_by(Contract.id.asc())
            )
            if limit_per_code is not None:
                q = q.limit(limit_per_code)
            contracts = q.all()

            print(f'=== MEMBERSHIP {code} ({len(contracts)} contracts) ===')
            stats = by_membership[code]

            for contract in contracts:
                stats['total'] += 1
                grand['total'] += 1
                try:
                    row = _classify_one(db, contract, year_j)
                    mt = row['mismatch_type']
                    stats['by_type'][mt] += 1
                    grand['by_type'][mt] += 1

                    if mt == SHADOW_OK:
                        stats['OK'] += 1
                        grand['OK'] += 1
                    elif mt == SHADOW_G_RESOLVER:
                        stats['resolver_failure'] += 1
                        grand['resolver_failure'] += 1
                    elif mt == SHADOW_H_ENGINE:
                        stats['engine_failure'] += 1
                        grand['engine_failure'] += 1
                    elif mt in (
                        SHADOW_A_RAW,
                        SHADOW_B_ROUNDED,
                        SHADOW_C_COVERAGE,
                        SHADOW_D_ANNUAL,
                        SHADOW_E_REGION,
                        SHADOW_F_MEMBERSHIP,
                    ):
                        stats['mismatch'] += 1
                        grand['mismatch'] += 1

                    print(
                        f"contract_id={row['contract_id']} "
                        f"user_id={row['user_id']} "
                        f"membership_code={row['membership_code']} "
                        f"annual_snapshot={row['annual_snapshot']} "
                        f"live_annual={row['live_annual']} "
                        f"snapshot_eq_live={row['snapshot_eq_live']} "
                        f"engine_raw={row['engine_raw']} "
                        f"engine_rounded={row['engine_rounded']} "
                        f"legacy_raw={row['legacy_raw']} "
                        f"mismatch_type={row['mismatch_type']} "
                        f"resolver_status={row['resolver_status']} "
                        f"engine_status={row['engine_status']} "
                        f"resolver_engine_status={row['resolver_engine_status']}"
                    )
                except Exception as exc:
                    exit_code = 1
                    stats['errors'] += 1
                    grand['errors'] += 1
                    print(
                        f'contract_id={getattr(contract, "id", None)} '
                        f'user_id={getattr(contract, "user_id", None)} '
                        f'membership_code={code} '
                        f'ERROR={type(exc).__name__}:{exc}'
                    )
                    try:
                        db.rollback()
                    except Exception:
                        pass
                # Discard any accidental ORM dirtiness between rows.
                try:
                    db.rollback()
                except Exception:
                    pass

            print()

        print('========== SUMMARY ==========')
        for code in codes:
            s = by_membership[code]
            print(f'MEMBERSHIP {code}')
            print(f'total={s["total"]}')
            print(f'OK={s["OK"]}')
            print(f'mismatch={s["mismatch"]}')
            print(f'resolver_failure={s["resolver_failure"]}')
            print(f'engine_failure={s["engine_failure"]}')
            for mt in _MISMATCH_CODES:
                print(f'{mt}={s["by_type"][mt]}')
            if s['errors']:
                print(f'unexpected_errors={s["errors"]}')
            print()

        print('TOTAL')
        print(f'contracts_checked={grand["total"]}')
        print(f'OK={grand["OK"]}')
        print(f'mismatch={grand["mismatch"]}')
        print(f'resolver_failure={grand["resolver_failure"]}')
        print(f'engine_failure={grand["engine_failure"]}')
        for mt in (SHADOW_OK,) + _MISMATCH_CODES:
            print(f'{mt}={grand["by_type"][mt]}')
        if grand['errors']:
            print(f'unexpected_errors={grand["errors"]}')
            exit_code = 1
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Read-only Phase 4 shadow parity diagnostic (no DB writes).'
    )
    parser.add_argument(
        '--codes',
        default='1,2,3,4',
        help='Comma-separated membership codes (default: 1,2,3,4)',
    )
    parser.add_argument(
        '--limit-per-code',
        type=int,
        default=None,
        help='Optional max contracts per membership code',
    )
    args = parser.parse_args(argv)
    codes = [c.strip() for c in args.codes.split(',') if c.strip()]
    if not codes:
        print('No membership codes specified', file=sys.stderr)
        return 2
    return run(codes, limit_per_code=args.limit_per_code)


if __name__ == '__main__':
    raise SystemExit(main())
