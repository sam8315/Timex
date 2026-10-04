"""
سرویس ثبت تعدیل خدمت — immutable + correction chain.
موتور پایان خدمت اینجا پیاده نمی‌شود.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from models.service_adjustment import ADJUSTMENT_TYPES, ServiceAdjustment
from web.services.membership_service import MembershipError, get_effective_rule


class ServiceAdjustmentError(MembershipError):
    pass


def _gate_for_type(
    db: Session,
    *,
    employee_id: str,
    contract_id: Optional[int],
    adjustment_type: str,
    effective_date: date,
) -> None:
    if adjustment_type not in ADJUSTMENT_TYPES:
        raise ServiceAdjustmentError("نوع تعدیل نامعتبر است")

    membership_code = None
    if contract_id is not None:
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            raise ServiceAdjustmentError("قرارداد یافت نشد")
        if contract.user_id != employee_id:
            raise ServiceAdjustmentError("قرارداد متعلق به این کارمند نیست")
        membership_code = contract.contract_type_code
    else:
        # آخرین قرارداد فعال/اخیر
        contract = (
            db.query(Contract)
            .filter(Contract.user_id == employee_id)
            .order_by(Contract.start_date.desc())
            .first()
        )
        if contract:
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
    _gate_for_type(
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
        contract_id=contract_id,
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
    _gate_for_type(
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
        contract_id=original.contract_id,
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
    row.status = "void"
    db.flush()
    return row
