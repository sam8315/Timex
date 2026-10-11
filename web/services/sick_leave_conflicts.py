"""تعارض تأیید مرخصی استعلاجی روزانه. جمعه و استراحت به‌تنهایی تعارض نیستند."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

import jdatetime
from sqlalchemy.orm import Session

from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.hourly_mission import HourlyMission
from models.leave_request import LeaveRequest


def _jalali(day: date) -> str:
    return jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d")


def _iter_days(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def find_sick_leave_conflicts(
    db: Session,
    user_id: str,
    from_date: date,
    to_date: date,
    *,
    exclude_request_id: Optional[int] = None,
) -> list[dict]:
    """تردد معتبر، مرخصی هم‌پوشان و مأموریت متداخل را با تاریخ برمی‌گرداند."""
    conflicts: list[dict] = []

    start_dt = datetime.combine(from_date, time.min)
    end_dt = datetime.combine(to_date + timedelta(days=1), time.min)
    punches = (
        db.query(Attendance)
        .filter(
            Attendance.user_id == user_id,
            Attendance.is_deleted.is_(False),
            Attendance.timestamp >= start_dt,
            Attendance.timestamp < end_dt,
        )
        .all()
    )
    punch_days = sorted({row.timestamp.date() for row in punches})
    for day in punch_days:
        if from_date <= day <= to_date:
            conflicts.append({
                "date": day,
                "kind": "punch",
                "label": "تردد",
            })

    leave_query = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user_id,
        LeaveRequest.status.in_(("P", "A")),
        LeaveRequest.from_date <= to_date,
        LeaveRequest.to_date >= from_date,
    )
    if exclude_request_id is not None:
        leave_query = leave_query.filter(LeaveRequest.id != exclude_request_id)
    for other in leave_query.all():
        overlap_start = max(from_date, other.from_date)
        overlap_end = min(to_date, other.to_date)
        for day in _iter_days(overlap_start, overlap_end):
            conflicts.append({
                "date": day,
                "kind": "leave",
                "label": f"مرخصی {other.leave_type}",
            })

    missions = (
        db.query(DailyStatus)
        .filter(
            DailyStatus.user_id == user_id,
            DailyStatus.status_code == "M",
            DailyStatus.status_date >= from_date,
            DailyStatus.status_date <= to_date,
        )
        .all()
    )
    for row in missions:
        conflicts.append({
            "date": row.status_date,
            "kind": "mission",
            "label": "مأموریت",
        })

    hourly = (
        db.query(HourlyMission)
        .filter(
            HourlyMission.user_id == user_id,
            HourlyMission.status.in_(("P", "A")),
            HourlyMission.mission_date >= from_date,
            HourlyMission.mission_date <= to_date,
        )
        .all()
    )
    for row in hourly:
        conflicts.append({
            "date": row.mission_date,
            "kind": "hourly_mission",
            "label": "مأموریت ساعتی",
        })

    conflicts.sort(key=lambda item: (item["date"], item["kind"]))
    return conflicts


def format_conflict_message(conflicts: list[dict]) -> str:
    if not conflicts:
        return ""
    parts = [
        f"{_jalali(item['date'])}: {item['label']}"
        for item in conflicts
    ]
    return "تأیید استعلاجی تا رفع تعارض ممکن نیست — " + "؛ ".join(parts)


def parse_employer_pays(raw: Optional[str], *, required: bool) -> Optional[bool]:
    if raw is None or str(raw).strip() == "":
        if required:
            raise ValueError(
                "برای تأیید مرخصی استعلاجی باید مشخص شود حقوق روزها بر عهده کارفرماست یا نه"
            )
        return None
    value = str(raw).strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ValueError("وضعیت پرداخت استعلاجی نامعتبر است")
