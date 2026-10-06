"""
Read-only Annual Leave dashboard aggregates for Admin/User UI.

Uses central ledger snapshot + settlement facades + optional engine estimate.
Never mutates DB.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.membership_type import MembershipType
from models.membership_type_rule import MembershipTypeRule
from web.services import membership_semantics as msem
from web.services.conscript_service_context import build_conscript_service_context
from web.services.leave_entitlement_cutover import (
    entitlement_via_resolver_engine,
    get_entitlement_path,
)
from web.services.leave_entitlement_service import resolve_annual_leave_days
from web.services.leave_service import (
    get_buyback_quota,
    get_stored_leave_balance,
    get_user_al_year_snapshot,
)
from web.services.leave_settlement import (
    resolve_buyback_cap,
    resolve_membership_change_mode,
    resolve_storage_cap,
)


def build_user_annual_leave_dashboard(
    db: Session,
    user_id: str,
    *,
    year_j: Optional[int] = None,
) -> Dict[str, Any]:
    year = year_j if year_j is not None else jdatetime.date.today().year
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    snapshot = get_user_al_year_snapshot(db, user_id, year)
    stored = get_stored_leave_balance(db, user_id, year)
    buyback_quota = get_buyback_quota(db, user_id, year)

    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.desc())
        .all()
    )
    active = None
    for c in contracts:
        if c.is_active:
            active = c
            break
    membership_code = (
        active.contract_type_code if active else (employee.department if employee else None)
    )
    region = employee.region_code if employee else None
    live_annual = None
    storage_cap = None
    buyback_cap = None
    engine_estimate = None
    conscript = None
    if membership_code:
        live_annual = resolve_annual_leave_days(
            db, membership_code, region_code=region
        )
        storage_cap = resolve_storage_cap(
            db, membership_code, region_code=region, year_j=year
        )
        buyback_cap = resolve_buyback_cap(
            db, membership_code, region_code=region, year_j=year
        )
        if active is not None:
            try:
                eng = entitlement_via_resolver_engine(
                    db, active, annual_override=active.annual_leave_days, year_j=year
                )
                if year in eng:
                    engine_estimate = {
                        'raw': eng[year]['AL'],
                        'rounded': round(eng[year]['AL']),
                        'path': get_entitlement_path(),
                    }
            except Exception:
                engine_estimate = None
            if msem.is_conscript(db, membership_code):
                conscript = build_conscript_service_context(db, active, employee=employee)

    balances = {
        b.leave_type: b.balance
        for b in db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user_id, LeaveBalance.year == year)
        .all()
    }

    return {
        'user_id': user_id,
        'year_j': year,
        'membership_code': membership_code,
        'region_code': region,
        'snapshot': snapshot,
        'balances': balances,
        'stored_cw': stored,
        'buyback_quota': buyback_quota,
        'live_annual': live_annual,
        'contract_snapshot_annual': (
            active.annual_leave_days if active else None
        ),
        'storage_cap': storage_cap,
        'buyback_cap': buyback_cap,
        'membership_change_mode': resolve_membership_change_mode(db).value,
        'engine_estimate': engine_estimate,
        'active_contract_id': getattr(active, 'id', None) if active else None,
        'conscript': conscript,
        'contracts_count': len(contracts),
    }


def list_membership_al_policies(db: Session) -> List[Dict[str, Any]]:
    """Admin policy overview from MembershipType + active Rule (read-only)."""
    types = (
        db.query(MembershipType)
        .order_by(MembershipType.sort_order.asc(), MembershipType.code.asc())
        .all()
    )
    rows = []
    for mt in types:
        rule = (
            db.query(MembershipTypeRule)
            .filter(
                MembershipTypeRule.membership_type_code == mt.code,
                MembershipTypeRule.status == 'active',
            )
            .order_by(MembershipTypeRule.effective_from.desc())
            .first()
        )
        rows.append(
            {
                'code': mt.code,
                'name': mt.name,
                'behavior_profile': mt.behavior_profile,
                'annual_leave_base': rule.annual_leave_base if rule else None,
                'effective_from': rule.effective_from if rule else None,
                'supports_service_deduction': (
                    rule.supports_service_deduction if rule else False
                ),
                'leave_start_date_basis': (
                    rule.leave_start_date_basis if rule else 'dispatch'
                ),
                'leave_start_date_basis_label': msem.leave_start_basis_label(
                    rule.leave_start_date_basis if rule else 'dispatch'
                ),
                'storage_cap': resolve_storage_cap(db, mt.code),
                'buyback_cap': resolve_buyback_cap(db, mt.code),
                'membership_change_mode': resolve_membership_change_mode(db).value,
                'is_conscript': msem.is_conscript(db, mt.code),
                'is_permanent': msem.is_permanent(db, mt.code),
            }
        )
    return rows
