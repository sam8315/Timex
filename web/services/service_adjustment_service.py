"""
سرویس ثبت تعدیل خدمت — immutable + correction chain.
پس از ثبت/اصلاح/ابطال، پایان قرارداد وظیفه بازمحاسبه می‌شود.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.service_adjustment import ADJUSTMENT_TYPES, ServiceAdjustment
from web.services.membership_service import MembershipError, get_effective_rule
from web.services import membership_semantics as msem


class ServiceAdjustmentError(MembershipError):
    pass


ADJUSTMENT_TYPE_LABELS = {
    "service_deduction": "کسر خدمت",
    "extra_service": "اضافه خدمت",
    "positive_seniority": "سنوات مثبت",
}


def format_adjustment_duration(years: int, months: int, days: int) -> str:
    parts = []
    if years:
        parts.append(f"{int(years)} سال")
    if months:
        parts.append(f"{int(months)} ماه")
    if days:
        parts.append(f"{int(days)} روز")
    return " و ".join(parts) if parts else "۰ روز"


def list_adjustments_for_contract(
    db: Session,
    contract_id: int,
    *,
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """لیست تعدیل‌های یک قرارداد برای نمایش UI."""
    q = (
        db.query(ServiceAdjustment)
        .filter(ServiceAdjustment.contract_id == contract_id)
        .order_by(ServiceAdjustment.effective_date.desc(), ServiceAdjustment.id.desc())
    )
    if active_only:
        q = q.filter(ServiceAdjustment.status == "active")
    rows = []
    for adj in q.all():
        rows.append(
            {
                "id": adj.id,
                "adjustment_type": adj.adjustment_type,
                "type_label": ADJUSTMENT_TYPE_LABELS.get(
                    adj.adjustment_type, adj.adjustment_type
                ),
                "years": int(adj.years or 0),
                "months": int(adj.months or 0),
                "days": int(adj.days or 0),
                "duration_text": format_adjustment_duration(
                    adj.years or 0, adj.months or 0, adj.days or 0
                ),
                "effective_date": adj.effective_date,
                "effective_date_j": jdatetime.date.fromgregorian(
                    date=adj.effective_date
                ).strftime("%Y/%m/%d"),
                "title": adj.title or "",
                "reason": adj.reason or "",
                "status": adj.status,
            }
        )
    return rows


def _recalculate_contract_end_after_adjustment(
    db: Session,
    contract_id: Optional[int],
) -> None:
    """بازمحاسبه پایان وظیفه و همگام‌سازی شارژ مرخصی در صورت تغییر پایان."""
    if contract_id is None:
        return
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        return
    if not msem.is_conscript(db, contract.contract_type_code):
        return
    if not contract.dispatch_date or not contract.service_duty_region_code:
        return

    from web.services.service_end_date_engine import (
        ServiceEndDateError,
        apply_end_date_to_contract,
    )
    from web.services.leave_service import update_leave_for_contract

    old_end = contract.end_date
    old_deduction = int(contract.service_deduction_days or 0)
    try:
        apply_end_date_to_contract(db, contract)
    except ServiceEndDateError:
        return

    if old_end == contract.end_date and old_deduction == contract.service_deduction_days:
        return

    update_leave_for_contract(
        db,
        contract,
        old_annual_leave=contract.annual_leave_days,
        old_sick_leave=contract.sick_leave_days,
        old_start_date=contract.start_date,
        old_end_date=old_end,
        old_deduction=old_deduction,
        old_type_code=contract.contract_type_code,
        commit=False,
    )


def resolve_contract_for_effective_date(
    db: Session,
    employee_id: str,
    effective_date: date,
) -> Contract:
    """
    قراردادی که در effective_date پوشش دارد.
    tie-break: start_date desc, id desc.
    بدون پوشش → خطا (نه fallback آخرین قرارداد).
    """
    candidates = (
        db.query(Contract)
        .filter(
            Contract.user_id == employee_id,
            Contract.start_date <= effective_date,
        )
        .order_by(Contract.start_date.desc(), Contract.id.desc())
        .all()
    )
    for contract in candidates:
        if contract.end_date is None or contract.end_date >= effective_date:
            return contract
    raise ServiceAdjustmentError(
        "هیچ قراردادی در تاریخ مؤثر تعدیل یافت نشد"
    )


def _gate_for_type(
    db: Session,
    *,
    employee_id: str,
    contract_id: Optional[int],
    adjustment_type: str,
    effective_date: date,
) -> Optional[int]:
    """Gate با Rule مؤثر همان تاریخ. برمی‌گرداند contract_id حل‌شده."""
    if adjustment_type not in ADJUSTMENT_TYPES:
        raise ServiceAdjustmentError("نوع تعدیل نامعتبر است")

    resolved_contract_id = contract_id
    membership_code = None
    if contract_id is not None:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            raise ServiceAdjustmentError("قرارداد یافت نشد")
        if contract.user_id != employee_id:
            raise ServiceAdjustmentError("قرارداد متعلق به این کارمند نیست")
        # قرارداد انتخاب‌شده باید تاریخ را پوشش دهد
        if contract.start_date > effective_date or (
            contract.end_date is not None and contract.end_date < effective_date
        ):
            raise ServiceAdjustmentError(
                "قرارداد انتخاب‌شده تاریخ مؤثر را پوشش نمی‌دهد"
            )
        membership_code = contract.contract_type_code
    else:
        contract = resolve_contract_for_effective_date(
            db, employee_id, effective_date
        )
        resolved_contract_id = contract.id
        membership_code = contract.contract_type_code

    if not membership_code:
        raise ServiceAdjustmentError("عضویت مؤثر برای بررسی مجوز یافت نشد")

    rule = get_effective_rule(db, membership_code, on_date=effective_date)
    if not rule:
        raise ServiceAdjustmentError("Rule عضویت مؤثر یافت نشد")

    flag_map = {
        "service_deduction": rule.supports_service_deduction,
        "extra_service": rule.supports_extra_service,
        "positive_seniority": rule.supports_positive_seniority,
    }
    if not flag_map.get(adjustment_type):
        raise ServiceAdjustmentError(
            "این نوع تعدیل برای عضویت مؤثر مجاز نیست"
        )
    return resolved_contract_id


def create_adjustment(
    db: Session,
    *,
    employee_id: str,
    adjustment_type: str,
    effective_date: date,
    years: int = 0,
    months: int = 0,
    days: int = 0,
    title: Optional[str] = None,
    reason: Optional[str] = None,
    description: Optional[str] = None,
    contract_id: Optional[int] = None,
    created_by: Optional[str] = None,
) -> ServiceAdjustment:
    resolved_contract_id = _gate_for_type(
        db,
        employee_id=employee_id,
        contract_id=contract_id,
        adjustment_type=adjustment_type,
        effective_date=effective_date,
    )
    years = max(0, int(years))
    months = max(0, min(11, int(months)))
    days = max(0, int(days))
    if years == 0 and months == 0 and days == 0:
        raise ServiceAdjustmentError("حداقل یکی از سال/ماه/روز باید مثبت باشد")

    row = ServiceAdjustment(
        employee_id=employee_id,
        contract_id=resolved_contract_id,
        adjustment_type=adjustment_type,
        years=years,
        months=months,
        days=days,
        title=(title or None),
        reason=(reason or None),
        effective_date=effective_date,
        description=(description or None),
        status="active",
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    _recalculate_contract_end_after_adjustment(db, resolved_contract_id)
    return row


def correct_adjustment(
    db: Session,
    *,
    original_id: int,
    years: int,
    months: int,
    days: int,
    title: Optional[str] = None,
    reason: Optional[str] = None,
    description: Optional[str] = None,
    effective_date: Optional[date] = None,
    created_by: Optional[str] = None,
) -> ServiceAdjustment:
    """اصلاح با رکورد correction؛ ویرایش مستقیم اصل مجاز نیست."""
    original = (
        db.query(ServiceAdjustment)
        .filter(ServiceAdjustment.id == original_id)
        .first()
    )
    if not original:
        raise ServiceAdjustmentError("رکورد تعدیل یافت نشد")
    if original.status != "active":
        raise ServiceAdjustmentError("فقط رکورد فعال قابل اصلاح است")

    eff = effective_date or original.effective_date
    resolved_contract_id = _gate_for_type(
        db,
        employee_id=original.employee_id,
        contract_id=original.contract_id,
        adjustment_type=original.adjustment_type,
        effective_date=eff,
    )

    years = max(0, int(years))
    months = max(0, min(11, int(months)))
    days = max(0, int(days))

    correction = ServiceAdjustment(
        employee_id=original.employee_id,
        contract_id=resolved_contract_id,
        adjustment_type=original.adjustment_type,
        years=years,
        months=months,
        days=days,
        title=title if title is not None else original.title,
        reason=reason if reason is not None else original.reason,
        effective_date=eff,
        description=description if description is not None else original.description,
        status="active",
        created_by=created_by,
        corrects_adjustment_id=original.id,
    )
    original.status = "corrected"
    db.add(correction)
    db.flush()
    _recalculate_contract_end_after_adjustment(db, resolved_contract_id)
    return correction


def void_adjustment(
    db: Session,
    adjustment_id: int,
    *,
    created_by: Optional[str] = None,
) -> ServiceAdjustment:
    """باطل‌سازی فقط با وضعیت void — حذف فیزیکی ممنوع."""
    row = (
        db.query(ServiceAdjustment)
        .filter(ServiceAdjustment.id == adjustment_id)
        .first()
    )
    if not row:
        raise ServiceAdjustmentError("رکورد تعدیل یافت نشد")
    if row.status != "active":
        raise ServiceAdjustmentError("فقط رکورد فعال قابل ابطال است")
    contract_id = row.contract_id
    row.status = "void"
    db.flush()
    _recalculate_contract_end_after_adjustment(db, contract_id)
    return row
