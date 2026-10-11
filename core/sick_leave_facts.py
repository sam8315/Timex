"""وضعیت روز استعلاجی برای حضور، گزارش و ساعات قابل پرداخت.

موتور تردد فقط ساعات خام را می‌دهد. این ماژول حقوق را حساب نمی‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Sequence


@dataclass(frozen=True)
class SickSpan:
    request_id: int
    from_date: date
    to_date: date
    status: str
    employer_pays_wages: Optional[bool]


@dataclass(frozen=True)
class SickDayEffect:
    covered: bool = False
    display_as_sick: bool = False
    payroll_uses_punch: bool = True
    payment_label: str = ""
    employer_pays_wages: Optional[bool] = None
    request_id: Optional[int] = None
    suppress_absence: bool = False
    suppress_incomplete: bool = False
    payment_unknown: bool = False


def payment_label(employer_pays_wages: Optional[bool]) -> str:
    if employer_pays_wages is True:
        return "حقوق بر عهده کارفرما هست"
    if employer_pays_wages is False:
        return "حقوق بر عهده کارفرما نیست"
    return "وضعیت پرداخت نامشخص"


def spans_from_leaves(leaves: Sequence[object]) -> list[SickSpan]:
    spans: list[SickSpan] = []
    for leave in leaves:
        if getattr(leave, "leave_type", None) != "SL":
            continue
        spans.append(
            SickSpan(
                request_id=int(leave.id),
                from_date=leave.from_date,
                to_date=leave.to_date,
                status=str(leave.status or ""),
                employer_pays_wages=getattr(leave, "employer_pays_wages", None),
            )
        )
    return spans


def index_spans(
    spans: Sequence[SickSpan],
    start: date,
    end: date,
    *,
    approved_only: bool = True,
) -> dict[date, SickSpan]:
    """هر روز تقویمی بازه، از جمله جمعه و تعطیل، به درخواست پوشاننده وصل می‌شود."""
    indexed: dict[date, SickSpan] = {}
    for span in spans:
        if approved_only and span.status != "A":
            continue
        cursor = max(span.from_date, start)
        last = min(span.to_date, end)
        while cursor <= last:
            current = indexed.get(cursor)
            if current is None or span.request_id < current.request_id:
                indexed[cursor] = span
            cursor += timedelta(days=1)
    return indexed


def effect_for_span(
    span: Optional[SickSpan],
    *,
    is_friday: bool = False,
    is_holiday: bool = False,
    is_weekly_rest: bool = False,
    is_mission: bool = False,
) -> SickDayEffect:
    if span is None or span.status != "A":
        return SickDayEffect()
    calendar_hold = bool(is_friday or is_holiday or is_weekly_rest or is_mission)
    unknown = span.employer_pays_wages is None
    return SickDayEffect(
        covered=True,
        display_as_sick=not calendar_hold,
        payroll_uses_punch=unknown,
        payment_label=payment_label(span.employer_pays_wages),
        employer_pays_wages=span.employer_pays_wages,
        request_id=span.request_id,
        suppress_absence=True,
        suppress_incomplete=True,
        payment_unknown=unknown,
    )


def apply_work_hours(
    punch_hours: float,
    effect: SickDayEffect,
    shift_hours: Optional[dict] = None,
) -> dict:
    """کارکرد نمایشی استعلاجی صفر است. کارکرد حقوق برای پرچم نامشخص همان تردد می‌ماند."""
    shifts = dict(shift_hours or {"morning": 0.0, "evening": 0.0, "night": 0.0})
    if not effect.covered:
        return {
            "work_hours": float(punch_hours or 0),
            "payroll_work_hours": float(punch_hours or 0),
            "morning_hours": float(shifts.get("morning") or 0),
            "evening_hours": float(shifts.get("evening") or 0),
            "night_hours": float(shifts.get("night") or 0),
            "payroll_morning_hours": float(shifts.get("morning") or 0),
            "payroll_evening_hours": float(shifts.get("evening") or 0),
            "payroll_night_hours": float(shifts.get("night") or 0),
        }
    payroll_hours = float(punch_hours or 0) if effect.payroll_uses_punch else 0.0
    payroll_shifts = shifts if effect.payroll_uses_punch else {
        "morning": 0.0, "evening": 0.0, "night": 0.0,
    }
    display_shifts = {"morning": 0.0, "evening": 0.0, "night": 0.0}
    return {
        "work_hours": 0.0,
        "payroll_work_hours": payroll_hours,
        "morning_hours": display_shifts["morning"],
        "evening_hours": display_shifts["evening"],
        "night_hours": display_shifts["night"],
        "payroll_morning_hours": float(payroll_shifts.get("morning") or 0),
        "payroll_evening_hours": float(payroll_shifts.get("evening") or 0),
        "payroll_night_hours": float(payroll_shifts.get("night") or 0),
    }


def is_full_day_leave_status(code: Optional[str]) -> bool:
    return code in ("L", "SL")


def sick_status_dict(effect: SickDayEffect) -> dict:
    if not effect.display_as_sick:
        return {}
    return {
        "main_status": "leave",
        "main_label": f"🌴 مرخصی استعلاجی — {effect.payment_label}",
        "main_color": "info",
        "warnings": [],
    }


def coverage_note(effect: SickDayEffect) -> str:
    if not effect.covered or effect.display_as_sick:
        return ""
    return f"پوشش استعلاجی — {effect.payment_label}"
