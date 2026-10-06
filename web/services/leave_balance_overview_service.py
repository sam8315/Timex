"""
Admin leave-balances list: entitlement / used / remaining overview.

Conscript rows are aggregated across the full service period (all years).
Non-conscript rows stay year-scoped.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from models.contract import Contract
from models.leave_balance import LeaveBalance
from web.services import membership_semantics as msem
from web.services.leave_service import get_user_al_year_snapshot


def get_user_al_period_snapshot(
    db: Session,
    user_id: str,
    years: Sequence[int],
) -> dict:
    """
    Sum year snapshots over ``years``.

    ``remaining`` is always ``entitlement - used`` (may be negative) so the
    three overview columns stay consistent.
    """
    years_sorted = sorted({int(y) for y in years if y is not None})
    entitlement = 0
    used = 0
    al_days = 0.0
    cw_days = 0.0
    for year in years_sorted:
        snap = get_user_al_year_snapshot(db, user_id, year)
        entitlement += int(snap.get('entitlement') or 0)
        used += int(snap.get('used') or 0)
        al_days += float(snap.get('al_days') or 0)
        cw_days += float(snap.get('cw_days') or 0)
    remaining = entitlement - used
    return {
        'entitlement': entitlement,
        'used': used,
        'remaining': remaining,
        'al_days': al_days,
        'cw_days': cw_days,
        'years': years_sorted,
    }


def _sum_type(rows: Iterable[dict], leave_type: str) -> Optional[float]:
    total = 0.0
    seen = False
    for row in rows:
        val = row.get(leave_type)
        if val is None:
            continue
        seen = True
        total += float(val)
    return total if seen else None


def _years_for_user(
    db: Session,
    user_id: str,
    seed_years: Sequence[int],
    membership_code: Optional[str],
) -> List[int]:
    years = {int(y) for y in seed_years if y is not None}
    bal_years = (
        db.query(LeaveBalance.year)
        .filter(LeaveBalance.user_id == user_id)
        .distinct()
        .all()
    )
    years.update(int(y[0]) for y in bal_years)

    if membership_code and msem.is_conscript(db, membership_code):
        contract = (
            db.query(Contract)
            .filter(Contract.user_id == user_id)
            .order_by(Contract.start_date.desc())
            .first()
        )
        if contract is not None:
            try:
                from web.services.leave_entitlement_service import (
                    split_contract_coverage_by_year,
                )

                for year_j, _s, _e in split_contract_coverage_by_year(
                    contract, db=db
                ):
                    years.add(int(year_j))
            except Exception:
                pass
    return sorted(years)


def _balances_by_year(db: Session, user_id: str, years: Sequence[int]) -> Dict[int, dict]:
    if not years:
        return {}
    rows = (
        db.query(LeaveBalance)
        .filter(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year.in_(list(years)),
        )
        .all()
    )
    out: Dict[int, dict] = {}
    for b in rows:
        slot = out.setdefault(
            int(b.year),
            {'AL': None, 'SL': None, 'RL': None, 'CW': None},
        )
        if b.leave_type in slot:
            slot[b.leave_type] = b.balance
    return out


def build_leave_balance_list_rows(
    db: Session,
    grouped_balances: Dict[Tuple[str, int], dict],
    contract_types_map: Dict[str, dict],
    *,
    name_resolver: Optional[Callable[[str], str]] = None,
) -> List[Dict[str, Any]]:
    """
    Build display rows for /admin/leave-balances.

    - Non-conscript: one row per (user, year) with AL entitlement/used/remaining.
    - Conscript: one period row per user aggregating all service years.
    """
    if not grouped_balances:
        return []

    by_user: Dict[str, List[dict]] = {}
    for (_uid, _year), row in grouped_balances.items():
        uid = row['user_id']
        by_user.setdefault(uid, []).append(row)

    result: List[Dict[str, Any]] = []
    for user_id, user_rows in by_user.items():
        ctype = contract_types_map.get(user_id) or {'code': None, 'name': '-'}
        code = ctype.get('code')
        is_conscript = bool(code and msem.is_conscript(db, code))
        full_name = (
            name_resolver(user_id) if name_resolver else f"کاربر {user_id}"
        )

        if is_conscript:
            seed = [int(r['year']) for r in user_rows]
            years = _years_for_user(db, user_id, seed, code)
            by_year = _balances_by_year(db, user_id, years)
            year_dicts = [
                by_year.get(y, {'AL': None, 'SL': None, 'RL': None, 'CW': None})
                for y in years
            ]
            snap = get_user_al_period_snapshot(db, user_id, years)
            al_remaining = int(snap['entitlement']) - int(snap['used'])
            period_label = 'دوره خدمت'
            if years:
                period_label = f"دوره خدمت {years[0]}–{years[-1]}"
            result.append(
                {
                    'user_id': user_id,
                    'full_name': full_name,
                    'contract_type': ctype,
                    'scope': 'period',
                    'year': None,
                    'years': years,
                    'period_label': period_label,
                    'al_entitlement': snap['entitlement'],
                    'al_used': snap['used'],
                    'al_remaining': al_remaining,
                    'AL': al_remaining,
                    'SL': _sum_type(year_dicts, 'SL'),
                    'RL': _sum_type(year_dicts, 'RL'),
                    'CW': _sum_type(year_dicts, 'CW'),
                    'is_conscript': True,
                }
            )
            continue

        for row in sorted(user_rows, key=lambda r: (-int(r['year']), r['user_id'])):
            year = int(row['year'])
            snap = get_user_al_year_snapshot(db, user_id, year)
            al_remaining = int(snap['entitlement'] or 0) - int(snap['used'] or 0)
            result.append(
                {
                    'user_id': user_id,
                    'full_name': full_name,
                    'contract_type': ctype,
                    'scope': 'year',
                    'year': year,
                    'years': [year],
                    'period_label': None,
                    'al_entitlement': snap['entitlement'],
                    'al_used': snap['used'],
                    'al_remaining': al_remaining,
                    'AL': al_remaining,
                    'SL': row.get('SL'),
                    'RL': row.get('RL'),
                    'CW': row.get('CW'),
                    'is_conscript': False,
                }
            )

    result.sort(
        key=lambda r: (
            0 if r.get('scope') == 'period' else 1,
            -(max(r['years']) if r.get('years') else 0),
            r['user_id'],
        )
    )
    return result
