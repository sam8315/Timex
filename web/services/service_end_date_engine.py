"""
موتور محاسبه پایان خدمت وظیفه از تاریخ اعزام + پالیسی مدت + تعدیل‌ها.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.service_adjustment import ServiceAdjustment
from web.services.service_duty_region_service import (
    ServiceDutyRegionError,
    resolve_service_duration_months,
)


class ServiceEndDateError(ServiceDutyRegionError):
    pass


def _jalali_days_in_month(year: int, month: int) -> int:
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    # Esfand: jdatetime.date.isleap is an instance method (not year:int)
    return 30 if jdatetime.date(year, 1, 1).isleap() else 29


def add_jalali_months(g_date: date, months: int) -> date:
    """افزودن/کاهش ماه شمسی به تاریخ میلادی (روز clamp می‌شود)."""
    j = jdatetime.date.fromgregorian(date=g_date)
    total = j.year * 12 + (j.month - 1) + int(months)
    year = total // 12
    month = total % 12 + 1
    day = min(j.day, _jalali_days_in_month(year, month))
    return jdatetime.date(year, month, day).togregorian()


def add_jalali_ymd(
    g_date: date,
    *,
    years: int = 0,
    months: int = 0,
    days: int = 0,
) -> date:
    """جابه‌جایی ترکیبی سال/ماه شمسی + روز میلادی."""
    result = add_jalali_months(g_date, years * 12 + months)
    if days:
        result = result + timedelta(days=int(days))
    return result


def _active_adjustments(db: Session, contract: Contract) -> list[ServiceAdjustment]:
    if not getattr(contract, "id", None):
        return []
    return (
        db.query(ServiceAdjustment)
        .filter(
            ServiceAdjustment.contract_id == contract.id,
            ServiceAdjustment.status == "active",
        )
        .all()
    )


def net_adjustment_delta(
    db: Session,
    contract: Contract,
) -> Tuple[int, int, int]:
    """
    خالص اثر تعدیل روی پایان: (years, months, days) با علامت
    مثبت = طولانی‌تر (extra)، منفی = کوتاه‌تر (deduction).
    """
    years = months = days = 0
    for adj in _active_adjustments(db, contract):
        sign = 0
        if adj.adjustment_type == "service_deduction":
            sign = -1
        elif adj.adjustment_type == "extra_service":
            sign = 1
        else:
            # positive_seniority: بدون اثر روی پایان
            continue
        years += sign * int(adj.years or 0)
        months += sign * int(adj.months or 0)
        days += sign * int(adj.days or 0)
    return years, months, days


def compute_legal_end_date(
    db: Session,
    *,
    dispatch_date: date,
    region_code: str,
    is_native: Optional[bool],
) -> date:
    months = resolve_service_duration_months(db, region_code, is_native)
    # پایان = اعزام + N ماه − ۱ روز
    return add_jalali_months(dispatch_date, months) - timedelta(days=1)


def compute_effective_end_date(
    db: Session,
    contract: Contract,
    *,
    dispatch_date: Optional[date] = None,
    region_code: Optional[str] = None,
    is_native: Optional[bool] = None,
) -> date:
    dispatch = dispatch_date if dispatch_date is not None else contract.dispatch_date
    region = (
        region_code
        if region_code is not None
        else contract.service_duty_region_code
    )
    native = is_native if is_native is not None else contract.is_native

    if dispatch is None:
        raise ServiceEndDateError("تاریخ اعزام الزامی است")
    if not region:
        raise ServiceEndDateError("انتخاب منطقه خدمت الزامی است")

    legal_end = compute_legal_end_date(
        db,
        dispatch_date=dispatch,
        region_code=region,
        is_native=native,
    )
    y, m, d = net_adjustment_delta(db, contract)
    return add_jalali_ymd(legal_end, years=y, months=m, days=d)


def apply_end_date_to_contract(
    db: Session,
    contract: Contract,
) -> date:
    """محاسبه و نوشتن end_date روی قرارداد."""
    end = compute_effective_end_date(db, contract)
    contract.end_date = end
    # snapshot سازگاری: جمع روز کسر خدمت فعال (تقریبی ماه=۳۰)
    ded_days = 0
    for adj in _active_adjustments(db, contract):
        if adj.adjustment_type != "service_deduction":
            continue
        ded_days += (
            int(adj.days or 0)
            + int(adj.months or 0) * 30
            + int(adj.years or 0) * 365
        )
    contract.service_deduction_days = max(0, ded_days)
    db.flush()
    return end


def preview_end_date(
    db: Session,
    *,
    dispatch_date: date,
    region_code: str,
    is_native: Optional[bool] = None,
    contract_id: Optional[int] = None,
) -> date:
    """پیش‌نمایش پایان؛ اگر contract_id باشد تعدیل‌های فعال لحاظ می‌شود."""
    stub = Contract(
        user_id="preview",
        contract_type_code="2",
        start_date=dispatch_date,
        dispatch_date=dispatch_date,
        service_duty_region_code=region_code,
        is_native=is_native,
    )
    if contract_id is not None:
        stub.id = contract_id
    return compute_effective_end_date(db, stub)
