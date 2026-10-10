"""
سرویس تشخیص ترددهای ناقص برای /admin/incomplete

مرجع تحلیلی: فقط Central Attendance Engine
(`core.attendance_calculator.compute_day_attendance`).

این ماژول مسئول bulk-load، گروه‌بندی، و فیلتر نتایج است؛
هیچ منطق مستقل sequence/night-shift پیاده‌سازی نمی‌کند.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session

from core.attendance_calculator import (
    STATUS_COMPLETE,
    STATUS_IMBALANCE,
    STATUS_MISSING_ENTER,
    STATUS_MISSING_EXIT,
    STATUS_NIGHT_SHIFT,
    STATUS_NO_ATTENDANCE,
    STATUS_SEQUENCE_ERROR,
    compute_day_attendance,
)
from models.attendance import Attendance
from models.employee import Employee

# وضعیت‌هایی که همیشه «تردد ناقص واقعی» محسوب می‌شوند
REAL_INCOMPLETE_STATUSES = frozenset({
    STATUS_MISSING_ENTER,
    STATUS_MISSING_EXIT,
    STATUS_IMBALANCE,
    STATUS_SEQUENCE_ERROR,
})

# وضعیت‌هایی که هرگز در لیست ناقص‌ها نمی‌آیند
EXCLUDED_STATUSES = frozenset({
    STATUS_COMPLETE,
    STATUS_NO_ATTENDANCE,
})

ISSUE_LABELS = {
    STATUS_MISSING_ENTER: '❌ خروج بدون ورود',
    STATUS_MISSING_EXIT: '⚠️  ورود بدون خروج',
    STATUS_IMBALANCE: '🔄 عدم تعادل ورود/خروج',
    STATUS_SEQUENCE_ERROR: '❌ خطای ترتیب',
    STATUS_NIGHT_SHIFT: '🌙 شیفت شب',
}


class IncompleteDateError(ValueError):
    """خطای قابل نمایش برای تاریخ‌های نامعتبر فیلتر."""


def day_bounds(day: date) -> Tuple[datetime, datetime]:
    """بازه [نیمه‌شب, نیمه‌شب بعد) — معادل date(timestamp) == day بدون func.date."""
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def parse_jalali_date(value: str, field_label: str) -> date:
    """تبدیل رشته شمسی YYYY/MM/DD به date میلادی؛ در خطا پیام قابل فهم می‌دهد."""
    raw = (value or '').strip()
    if not raw:
        raise IncompleteDateError(f'{field_label} خالی است')
    try:
        j_day = jdatetime.datetime.strptime(raw, '%Y/%m/%d').date()
    except (ValueError, TypeError) as exc:
        raise IncompleteDateError(
            f'{field_label} نامعتبر است؛ فرمت صحیح: YYYY/MM/DD (مثال: 1404/07/01)'
        ) from exc
    return j_day.togregorian()


def default_month_range() -> Tuple[date, date]:
    """بازه پیش‌فرض: از اول ماه شمسی جاری تا امروز."""
    today_j = jdatetime.date.today()
    from_date = jdatetime.date(today_j.year, today_j.month, 1).togregorian()
    to_date = today_j.togregorian()
    return from_date, to_date


def resolve_date_range(
    from_date_str: Optional[str],
    to_date_str: Optional[str],
    *,
    show_all: bool = False,
) -> Tuple[date, date]:
    """
    تعیین بازه میلادی از ورودی‌های شمسی.

    - اگر show_all و تاریخی داده نشده → ماه جاری شمسی
    - اگر یکی از تاریخ‌ها خالی باشد → با پیش‌فرض ماه جاری تکمیل می‌شود
    - from_date > to_date → IncompleteDateError
    """
    default_from, default_to = default_month_range()

    if from_date_str:
        from_date = parse_jalali_date(from_date_str, 'از تاریخ')
    elif show_all or to_date_str:
        from_date = default_from
    else:
        from_date = default_from

    if to_date_str:
        to_date = parse_jalali_date(to_date_str, 'تا تاریخ')
    elif show_all or from_date_str:
        to_date = default_to
    else:
        to_date = default_to

    if from_date > to_date:
        raise IncompleteDateError('از تاریخ نمی‌تواند بعد از تا تاریخ باشد')

    return from_date, to_date


def _record_day(record: Attendance) -> date:
    """تاریخ تقویمی رکورد؛ هم‌راستا با سایر consumerهای موتور مرکزی."""
    ts = record.timestamp
    return ts.date() if hasattr(ts, 'date') else ts


def find_incomplete_attendances(
    db: Session,
    from_date: date,
    to_date: date,
    *,
    department: Optional[str] = None,
    membership_type: Optional[str] = None,
    department_id: Optional[int] = None,
    issue_type: Optional[str] = None,
    include_night_shift: bool = False,
    user_id: Optional[str] = None,
) -> List[Dict]:
    """
    یافتن روزهای ناقص در بازه با یک bulk query و موتور مرکزی.

    رکوردها از (from_date - 1) تا (to_date + 1) بارگذاری می‌شوند تا context
    شیفت شب برای مرزهای بازه در دسترس باشد.
    """
    load_start, _ = day_bounds(from_date - timedelta(days=1))
    _, load_end = day_bounds(to_date + timedelta(days=1))

    record_query = db.query(Attendance).filter(
        Attendance.timestamp >= load_start,
        Attendance.timestamp < load_end,
        Attendance.is_deleted.is_(False),
    )
    if user_id:
        record_query = record_query.filter(Attendance.user_id == user_id)
    records = record_query.order_by(
        Attendance.user_id, Attendance.timestamp
    ).all()

    by_user_day: Dict[Tuple[str, date], List[Attendance]] = defaultdict(list)
    user_ids = set()
    for rec in records:
        day = _record_day(rec)
        by_user_day[(rec.user_id, day)].append(rec)
        user_ids.add(rec.user_id)

    if not user_ids:
        return []

    employees = (
        db.query(Employee)
        .filter(Employee.user_id.in_(list(user_ids)))
        .all()
    )
    emp_by_uid = {e.user_id: e for e in employees}

    # روزهای داخل بازهٔ درخواستی که حداقل یک رکورد دارند
    candidate_keys = [
        (uid, day)
        for (uid, day) in by_user_day.keys()
        if from_date <= day <= to_date
    ]
    candidate_keys.sort(key=lambda x: (x[1], x[0]), reverse=True)

    results: List[Dict] = []
    for user_id, day in candidate_keys:
        emp = emp_by_uid.get(user_id)
        code = (emp.membership_type_code if emp and emp.membership_type_code else 'بدون گروه')
        wanted = membership_type or department
        if wanted and code != wanted:
            continue
        if department_id is not None and (emp is None or emp.department_id != department_id):
            continue

        day_records = by_user_day.get((user_id, day), [])
        prev_day_records = by_user_day.get((user_id, day - timedelta(days=1)), [])
        next_day_records = by_user_day.get((user_id, day + timedelta(days=1)), [])

        result = compute_day_attendance(
            day=day,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
        )

        status = result.main_status
        if status in EXCLUDED_STATUSES:
            continue

        is_night = result.is_night_shift or status == STATUS_NIGHT_SHIFT
        if is_night:
            if not include_night_shift:
                continue
            issue = STATUS_NIGHT_SHIFT
        elif status in REAL_INCOMPLETE_STATUSES:
            issue = status
        else:
            # وضعیت ناشناخته/غیربحرانی (مثلاً leave اگر جایی ست شود)
            continue

        if issue_type and issue != issue_type:
            continue

        j_date = jdatetime.date.fromgregorian(date=day)
        full_name = emp.full_name if emp else f'کاربر {user_id}'

        results.append({
            'user_id': user_id,
            'name': emp.full_name if emp else user_id,
            'full_name': full_name,
            'department': code,
            'membership_type_code': None if code == 'بدون گروه' else code,
            'date': day,
            'date_j': j_date.strftime('%Y/%m/%d'),
            'year_j': j_date.year,
            'month_j': j_date.month,
            'type': ISSUE_LABELS.get(issue, result.main_label),
            'issue': issue,
            'issue_detail': result.sequence_error_detail or '',
            'enter_count': result.enter_count,
            'exit_count': result.exit_count,
            'first_enter': result.first_enter,
            'last_exit': result.last_exit,
            'is_night_shift': is_night,
            'has_sequence_error': result.has_sequence_error,
            'main_status': result.main_status,
            'main_label': result.main_label,
        })

    return results


def build_incomplete_stats(items: List[Dict]) -> Dict[str, int]:
    return {
        'total': len(items),
        'missing_enter': sum(1 for i in items if i['issue'] == STATUS_MISSING_ENTER),
        'missing_exit': sum(1 for i in items if i['issue'] == STATUS_MISSING_EXIT),
        'imbalance': sum(1 for i in items if i['issue'] == STATUS_IMBALANCE),
        'sequence_error': sum(1 for i in items if i['issue'] == STATUS_SEQUENCE_ERROR),
        'night_shift': sum(1 for i in items if i['issue'] == STATUS_NIGHT_SHIFT),
    }


def group_by_department(items: List[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for item in items:
        dept = item['department']
        grouped.setdefault(dept, []).append(item)
    return grouped
