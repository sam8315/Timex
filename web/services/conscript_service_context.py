"""
Conscript / service-duration context builder (architecture).

Collects human-entered facts from Contract + ServiceAdjustment + Employee.
Does **not** invent legal service duration thresholds (bomi/non-bomi, unit
duration tables). Those remain owner-dependent Policies (ServiceDurationPolicy).

Effective duration formula (when legal duration is provided by Policy):
  effective = max(0, legal_duration_days - deduction_days)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.service_adjustment import ServiceAdjustment
from web.services import membership_semantics as msem


@dataclass(frozen=True)
class ConscriptServiceContext:
    """Immutable facts for Conscript entitlement / duration resolution."""

    user_id: str
    contract_id: Optional[int]
    membership_code: str
    enlistment_or_start: Optional[date]
    unit_entry: Optional[date]  # not yet modeled separately → None / start
    department_entry: Optional[date]
    service_type: Optional[str]  # owner-dependent; unset until Policy exists
    bomi_non_bomi: Optional[str]  # owner-dependent
    unit_code: Optional[str]
    region_code: Optional[str]
    service_deduction_days: int
    legal_duration_days: Optional[int]  # from Policy only; None = unresolved
    effective_duration_days: Optional[int]
    calculated_end_date: Optional[date]
    unresolved_owner_rules: tuple[str, ...]


def build_conscript_service_context(
    db: Session,
    contract: Contract,
    *,
    employee: Optional[Employee] = None,
    legal_duration_days: Optional[int] = None,
) -> ConscriptServiceContext:
    """
    Build Conscript context from existing DB facts.

    ``legal_duration_days`` must come from an injected ServiceDurationPolicy
    result — this builder never hard-codes legal thresholds.
    """
    if employee is None:
        employee = (
            db.query(Employee).filter(Employee.user_id == contract.user_id).first()
        )
    code = str(contract.contract_type_code)
    deduction = int(contract.service_deduction_days or 0)
    # Sum active service_deduction adjustments if present (extra ledger)
    adj_days = (
        db.query(ServiceAdjustment)
        .filter(
            ServiceAdjustment.employee_id == contract.user_id,
            ServiceAdjustment.contract_id == contract.id,
            ServiceAdjustment.adjustment_type == 'service_deduction',
            ServiceAdjustment.status == 'active',
        )
        .all()
    )
    for adj in adj_days:
        deduction += int(adj.days or 0) + int(adj.months or 0) * 30 + int(adj.years or 0) * 365

    unresolved = []
    if not msem.is_conscript(db, code):
        unresolved.append('not_conscript_membership')
    if legal_duration_days is None:
        unresolved.append('legal_duration_policy_unresolved')
    unresolved.append('service_type_owner_dependent')
    unresolved.append('bomi_non_bomi_owner_dependent')
    unresolved.append('unit_master_owner_dependent')

    effective = None
    calc_end = None
    start = contract.start_date
    if legal_duration_days is not None and start is not None:
        effective = max(0, int(legal_duration_days) - deduction)
        calc_end = start + timedelta(days=max(0, effective - 1))

    return ConscriptServiceContext(
        user_id=contract.user_id,
        contract_id=getattr(contract, 'id', None),
        membership_code=code,
        enlistment_or_start=start,
        unit_entry=start,  # until dedicated field exists
        department_entry=None,
        service_type=None,
        bomi_non_bomi=None,
        unit_code=None,
        region_code=employee.region_code if employee else None,
        service_deduction_days=deduction,
        legal_duration_days=legal_duration_days,
        effective_duration_days=effective,
        calculated_end_date=calc_end,
        unresolved_owner_rules=tuple(unresolved),
    )


def conscript_context_as_dict(ctx: ConscriptServiceContext) -> Dict[str, Any]:
    return {
        'user_id': ctx.user_id,
        'contract_id': ctx.contract_id,
        'membership_code': ctx.membership_code,
        'enlistment_or_start': ctx.enlistment_or_start,
        'unit_entry': ctx.unit_entry,
        'department_entry': ctx.department_entry,
        'service_type': ctx.service_type,
        'bomi_non_bomi': ctx.bomi_non_bomi,
        'unit_code': ctx.unit_code,
        'region_code': ctx.region_code,
        'service_deduction_days': ctx.service_deduction_days,
        'legal_duration_days': ctx.legal_duration_days,
        'effective_duration_days': ctx.effective_duration_days,
        'calculated_end_date': ctx.calculated_end_date,
        'unresolved_owner_rules': list(ctx.unresolved_owner_rules),
    }
