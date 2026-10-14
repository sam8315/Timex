"""استخراج ساعات جمعه‌کاری و اضافه‌کار از موتور گزارش ماهانه."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from sqlalchemy.orm import Session

from core.payroll.money import D


@dataclass
class PayrollAttendanceContext:
    friday_hours: Decimal = D(0)
    overtime_hours: Decimal = D(0)
    holiday_hours: Decimal = D(0)
    deficit_hours: Decimal = D(0)
    morning_hours: Decimal = D(0)
    evening_hours: Decimal = D(0)
    night_hours: Decimal = D(0)
    excluded_sick_days: int = 0
    normal_absence_days: int = 0
    not_yet_days: int = 0
    absence_duty_hours: Decimal = D(0)
    scheduled_work_days: int = 0
    warnings: list[str] = field(default_factory=list)


def _in_contract(day, contract) -> bool:
    if contract is None:
        return True
    start = getattr(contract, "start_date", None)
    if start is not None and day < start:
        return False
    end = None
    if hasattr(contract, "actual_end_date"):
        try:
            end = contract.actual_end_date
        except Exception:
            end = getattr(contract, "end_date", None)
    else:
        end = getattr(contract, "end_date", None)
    if end is not None and day > end:
        return False
    return True


def _payroll_summary(report: dict) -> dict:
    days = report.get("days") or []
    summary = dict(report.get("summary") or {})
    if not any(day.get("sick_payment_unknown") for day in days):
        return summary
    shadow = []
    for day in days:
        copied = dict(day)
        copied["work_hours"] = day.get("payroll_work_hours", day.get("work_hours") or 0)
        copied["morning_hours"] = day.get("payroll_morning_hours", day.get("morning_hours") or 0)
        copied["evening_hours"] = day.get("payroll_evening_hours", day.get("evening_hours") or 0)
        copied["night_hours"] = day.get("payroll_night_hours", day.get("night_hours") or 0)
        shadow.append(copied)
    summary["total_work_hours"] = sum(float(day.get("work_hours") or 0) for day in shadow)
    from core.legal_overtime_monthly_report import build_legal_ot_summary
    return build_legal_ot_summary(
        shadow, summary,
        reference_at=report.get("reference_at"),
        policy=report.get("report_policy"),
    )


def _count_sick_inputs(report: dict, contract) -> dict:
    days = report.get("days") or []
    excluded = 0
    absence_days = 0
    absence_duty = 0.0
    scheduled = 0
    for day in days:
        current = day.get("date")
        if current is None or not _in_contract(current, contract):
            continue
        if not day.get("is_day_off"):
            scheduled += 1
        if day.get("person_status") == "A":
            absence_days += 1
            absence_duty += float(day.get("daily_duty") or 0)
        if day.get("sick_covered") and day.get("employer_pays_wages") is False:
            excluded += 1
    return {
        "excluded_sick_days": excluded,
        "normal_absence_days": absence_days,
        "not_yet_days": 0,
        "absence_duty_hours": absence_duty,
        "scheduled_work_days": scheduled,
        "warnings": list(report.get("sick_warnings") or []),
    }


def get_payroll_attendance_context(
    db: Session,
    user_id: str,
    year_j: int,
    month_j: int,
    contract=None,
) -> PayrollAttendanceContext:
    """ساعات حقوق. استعلاجی با پرچم نامشخص کارکرد خام را برای پول نگه می‌دارد."""
    del db
    empty = PayrollAttendanceContext()
    try:
        from core.legal_overtime_monthly_report import LegalOvertimeMonthlyReportGenerator

        gen = LegalOvertimeMonthlyReportGenerator()
        try:
            report = gen.generate_report(user_id, year_j, month_j)
        finally:
            gen.close()
        if not report.get("success"):
            return empty
        summary = _payroll_summary(report)
        counted = _count_sick_inputs(report, contract)
        return PayrollAttendanceContext(
            friday_hours=D(summary.get("friday_work_hours") or 0),
            overtime_hours=D(summary.get("overtime_total") or 0),
            holiday_hours=D(summary.get("holiday_work_hours") or 0),
            deficit_hours=D(summary.get("monthly_deficit") or 0),
            morning_hours=D(summary.get("total_morning") or 0),
            evening_hours=D(summary.get("total_evening") or 0),
            night_hours=D(summary.get("total_night") or 0),
            excluded_sick_days=counted["excluded_sick_days"],
            normal_absence_days=counted["normal_absence_days"],
            not_yet_days=counted["not_yet_days"],
            absence_duty_hours=D(counted["absence_duty_hours"]),
            scheduled_work_days=counted["scheduled_work_days"],
            warnings=counted["warnings"],
        )
    except Exception:
        return empty


def get_attendance_hour_buckets(
    db: Session,
    user_id: str,
    year_j: int,
    month_j: int,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """جمعه‌کاری، اضافه‌کار، تعطیل‌کاری، کسر کار، و ساعات صبح/عصر/شب."""
    ctx = get_payroll_attendance_context(db, user_id, year_j, month_j)
    return (
        ctx.friday_hours,
        ctx.overtime_hours,
        ctx.holiday_hours,
        ctx.deficit_hours,
        ctx.morning_hours,
        ctx.evening_hours,
        ctx.night_hours,
    )


def get_friday_work_hours(
    db: Session,
    user_id: str,
    year_j: int,
    month_j: int,
) -> Decimal:
    """ساعات جمعه‌کاری با حضور؛ در صورت خطا صفر برمی‌گرداند."""
    friday, *_rest = get_attendance_hour_buckets(db, user_id, year_j, month_j)
    return friday
