"""
Conscript / service-duration context builder.

Collects human-entered facts from Contract + ServiceAdjustment + Employee.
Legal duration comes from ServiceDutyRegion policy (DB), never hard-coded.
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
from web.services.service_duty_region_service import (
    ServiceDutyRegionError,
    get_duty_region,
)
from web.services.service_end_date_engine import (
    ServiceEndDateError,
    compute_effective_end_date,
    compute_legal_end_date,
)


@dataclass(frozen=True)
class ConscriptServiceContext:
    """Immutable facts for Conscript entitlement / duration resolution."""

    user_id: str
    contract_id: Optional[int]
    membership_code: str
    enlistment_or_start: Optional[date]
    leave_entitlement_start: Optional[date]
    leave_start_date_basis: Optional[str]
    unit_entry: Optional[date]
    department_entry: Optional[date]
    service_type: Optional[str]
    bomi_non_bomi: Optional[str]
    unit_code: Optional[str]
    region_code: Optional[str]
    service_duty_region_code: Optional[str]
    service_deduction_days: int
    legal_duration_days: Optional[int]
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
    Build Conscript context from DB facts + ServiceDutyRegion policy.
    """
    if employee is None:
        employee = (
            db.query(Employee).filter(Employee.user_id == contract.user_id).first()
        )
    code = str(contract.contract_type_code)
    deduction = int(contract.service_deduction_days or 0)
    adj_days = (
        db.query(ServiceAdjustment)
        .filter(
            ServiceAdjustment.employee_id == contract.user_id,
            ServiceAdjustment.contract_id == contract.id,
            ServiceAdjustment.adjustment_type == "service_deduction",
            ServiceAdjustment.status == "active",
        )
        .all()
    )
    # Prefer engine snapshot; fall back to ledger sum if snapshot empty
    if deduction <= 0:
        for adj in adj_days:
            deduction += (
                int(adj.days or 0)
                + int(adj.months or 0) * 30
                + int(adj.years or 0) * 365
            )

    unresolved = []
    if not msem.is_conscript(db, code):
        unresolved.append("not_conscript_membership")

    duty_region = contract.service_duty_region_code
    is_native = contract.is_native
    dispatch = contract.dispatch_date or contract.start_date

    resolved_legal_days = legal_duration_days
    if resolved_legal_days is None and duty_region and dispatch is not None:
        try:
            legal_end = compute_legal_end_date(
                db,
                dispatch_date=dispatch,
                region_code=duty_region,
                is_native=is_native,
            )
            resolved_legal_days = (legal_end - dispatch).days + 1
        except (ServiceEndDateError, ServiceDutyRegionError):
            unresolved.append("legal_duration_policy_unresolved")
    elif resolved_legal_days is None:
        unresolved.append("legal_duration_policy_unresolved")

    if duty_region is None:
        unresolved.append("service_duty_region_missing")
    if contract.is_native is None and duty_region:
        region = get_duty_region(db, duty_region)
        if region and region.native_affects:
            unresolved.append("bomi_non_bomi_unresolved")

    bomi = None
    if is_native is True:
        bomi = "bomi"
    elif is_native is False:
        bomi = "non_bomi"

    effective = None
    calc_end = None
    start = dispatch
    leave_basis = msem.resolve_leave_start_basis(
        db, code, on_date=contract.start_date or date.today()
    )
    leave_start = msem.resolve_conscript_leave_start(db, contract)
    if resolved_legal_days is not None and start is not None:
        try:
            calc_end = compute_effective_end_date(db, contract)
            effective = (calc_end - start).days + 1
            if effective < 0:
                effective = 0
        except (ServiceEndDateError, ServiceDutyRegionError):
            effective = max(0, int(resolved_legal_days) - deduction)
            calc_end = start + timedelta(days=max(0, effective - 1))

    return ConscriptServiceContext(
        user_id=contract.user_id,
        contract_id=getattr(contract, "id", None),
        membership_code=code,
        enlistment_or_start=start,
        leave_entitlement_start=leave_start,
        leave_start_date_basis=leave_basis,
        unit_entry=contract.unit_entry_date or start,
        department_entry=contract.clinic_entry_date,
        service_type=None,
        bomi_non_bomi=bomi,
        unit_code=None,
        region_code=employee.region_code if employee else None,
        service_duty_region_code=duty_region,
        service_deduction_days=deduction,
        legal_duration_days=resolved_legal_days,
        effective_duration_days=effective,
        calculated_end_date=calc_end,
        unresolved_owner_rules=tuple(unresolved),
    )


def conscript_context_as_dict(ctx: ConscriptServiceContext) -> Dict[str, Any]:
    return {
        "user_id": ctx.user_id,
        "contract_id": ctx.contract_id,
        "membership_code": ctx.membership_code,
        "enlistment_or_start": ctx.enlistment_or_start,
        "leave_entitlement_start": ctx.leave_entitlement_start,
        "leave_start_date_basis": ctx.leave_start_date_basis,
        "unit_entry": ctx.unit_entry,
        "department_entry": ctx.department_entry,
        "service_type": ctx.service_type,
        "bomi_non_bomi": ctx.bomi_non_bomi,
        "unit_code": ctx.unit_code,
        "region_code": ctx.region_code,
        "service_duty_region_code": ctx.service_duty_region_code,
        "service_deduction_days": ctx.service_deduction_days,
        "legal_duration_days": ctx.legal_duration_days,
        "effective_duration_days": ctx.effective_duration_days,
        "calculated_end_date": ctx.calculated_end_date,
        "unresolved_owner_rules": list(ctx.unresolved_owner_rules),
    }
