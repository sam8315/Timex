"""استخراج ساعات جمعه‌کاری و اضافه‌کار از موتور گزارش ماهانه."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from core.payroll.money import D


def get_attendance_hour_buckets(
    db: Session,
    user_id: str,
    year_j: int,
    month_j: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """جمعه‌کاری، اضافه‌کار، تعطیل‌کاری، کسر کار، و ساعات صبح/عصر/شب."""
    del db  # generator opens its own session
    zeros = (D(0), D(0), D(0), D(0), D(0), D(0), D(0))
    try:
        from core.legal_overtime_monthly_report import LegalOvertimeMonthlyReportGenerator

        gen = LegalOvertimeMonthlyReportGenerator()
        try:
            report = gen.generate_report(user_id, year_j, month_j)
        finally:
            gen.close()
        if not report.get("success"):
            return zeros
        summary = report.get("summary") or {}
        return (
            D(summary.get("friday_work_hours") or 0),
            D(summary.get("overtime_total") or 0),
            D(summary.get("holiday_work_hours") or 0),
            D(summary.get("monthly_deficit") or 0),
            D(summary.get("total_morning") or 0),
            D(summary.get("total_evening") or 0),
            D(summary.get("total_night") or 0),
        )
    except Exception:
        return zeros


def get_friday_work_hours(
    db: Session,
    user_id: str,
    year_j: int,
    month_j: int,
) -> Decimal:
    """ساعات جمعه‌کاری با حضور؛ در صورت خطا صفر برمی‌گرداند."""
    friday, *_rest = get_attendance_hour_buckets(db, user_id, year_j, month_j)
    return friday
