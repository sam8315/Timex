"""
سرویس مأموریت ساعتی (Hourly Mission Service)

Policy Resolution + Submission-time Validation

Priority (mirrors HourlyLeavePolicy / phase-1 guide):
    Employee Override → Employment Type Policy → Default

NOT Leave: no LeaveRequest, no leave balance, no attendance/punch.
Duration is computed (end - start), never stored.
"""
from datetime import date, time
from typing import Optional, Dict, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from models.employee import Employee
from models.holiday import Holiday
from models.hourly_mission import HourlyMission, HourlyMissionPolicy
from web.services.attendance_policy_service import (
    resolve_policy as resolve_attendance_policy,
    resolve_policy_day,
    time_to_minutes,
)


# System/default fallback (بخش ۷ راهنما)
DEFAULT_HOURLY_MISSION_SETTINGS: Dict[str, bool] = {
    'enabled': True,
    'working_hours_only': True,
    'allowed_on_holidays': False,
    'deduct_from_required_minutes': True,
}

# Statuses that block a new request (pending + approved)
OVERLAP_BLOCKING_STATUSES = ('P', 'A')


def resolve_hourly_mission_policy(
    db: Session,
    employee: Employee,
    target_date: date
) -> Optional[HourlyMissionPolicy]:
    """
    پیدا کردن سیاست مأموریت ساعتی معتبر برای یک کارمند در یک تاریخ

    Priority:
    1. Employee Override (user_id = employee.user_id)
    2. Employment Type Policy (employment_type_code = employee.department)

    Returns:
        HourlyMissionPolicy یا None اگر پیدا نشود
    """
    employment_type = employee.department if employee else None
    if not employment_type:
        return None

    # مرحله ۱: Employee Override
    override = db.query(HourlyMissionPolicy).filter(
        and_(
            HourlyMissionPolicy.user_id == employee.user_id,
            HourlyMissionPolicy.is_active == True,
            HourlyMissionPolicy.effective_from_date <= target_date,
            (
                HourlyMissionPolicy.effective_to_date.is_(None) |
                (HourlyMissionPolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyMissionPolicy.effective_from_date.desc()).first()

    if override:
        return override

    # مرحله ۲: Employment Type Policy
    emp_policy = db.query(HourlyMissionPolicy).filter(
        and_(
            HourlyMissionPolicy.employment_type_code == employment_type,
            HourlyMissionPolicy.user_id.is_(None),
            HourlyMissionPolicy.is_active == True,
            HourlyMissionPolicy.effective_from_date <= target_date,
            (
                HourlyMissionPolicy.effective_to_date.is_(None) |
                (HourlyMissionPolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyMissionPolicy.effective_from_date.desc()).first()

    return emp_policy


def get_effective_hourly_mission_settings(
    db: Session,
    employee: Employee,
    target_date: date
) -> Dict[str, bool]:
    """
    دریافت چهار تنظیم مؤثر برای کارمند در تاریخ مشخص.

    اگر policy پیدا نشود → defaultهای سراسری.
    """
    policy = resolve_hourly_mission_policy(db, employee, target_date)
    if not policy:
        return dict(DEFAULT_HOURLY_MISSION_SETTINGS)
    return policy.settings


# ============================================
# Duration helpers (computed — not stored)
# ============================================

def compute_mission_minutes(start_time: time, end_time: time) -> int:
    """محاسبه دقایق مأموریت = end - start (ذخیره نمی‌شود)"""
    if start_time is None or end_time is None:
        return 0
    return time_to_minutes(end_time) - time_to_minutes(start_time)


def get_authorized_mission_minutes(
    settings: Dict[str, bool],
    start_time: time,
    end_time: time,
) -> int:
    """
    دقایق مأموریت مجاز برای لایه محاسباتی (compute_required_minutes_for_range).

    اگر deduct_from_required_minutes=False → 0
    """
    if not settings.get('deduct_from_required_minutes', True):
        return 0
    return compute_mission_minutes(start_time, end_time)


def get_approved_hourly_mission_minutes(
    db: Session,
    employee: Employee,
    start_date: date,
    end_date: date
) -> Dict[date, int]:
    """
    مجموع دقایق مأموریت ساعتی تأییدشده برای هر تاریخ در بازه.

    فقط status='A' (Pending/Rejected/Cancelled محاسبه نمی‌شوند).
    policy deduct_from_required_minutes per date resolve می‌شود؛
    خاموش → 0 برای آن مأموریت. مأموریت‌های چندگانه یک روز جمع می‌شوند.
    Returns: dict[date] → minutes
    """
    missions = db.query(HourlyMission).filter(
        and_(
            HourlyMission.user_id == employee.user_id,
            HourlyMission.status == 'A',
            HourlyMission.mission_date >= start_date,
            HourlyMission.mission_date <= end_date,
        )
    ).all()

    result: Dict[date, int] = {}
    settings_cache: Dict[date, Dict[str, bool]] = {}
    for m in missions:
        if m.mission_date not in settings_cache:
            settings_cache[m.mission_date] = get_effective_hourly_mission_settings(
                db, employee, m.mission_date
            )
        minutes = get_authorized_mission_minutes(
            settings_cache[m.mission_date], m.start_time, m.end_time
        )
        if minutes > 0:
            result[m.mission_date] = result.get(m.mission_date, 0) + minutes
    return result


# ============================================
# Holiday helper (uses existing project logic — no new definition)
# ============================================

def is_holiday_for_employee(
    db: Session,
    employee: Employee,
    target_date: date,
) -> bool:
    """
    holiday بودن روز — عین سازوکار موجود Timex.

    ترکیب:
    1. Friday: date.weekday() == 4 (Python; هفته کاری شمسی)
    2. جدول holidays: group_id NULL (ملی) یا group_id == employee.department

    AttendancePolicyDay.is_working_day جداگانه بررسی می‌شود (روز غیرکاری).
    الگو: query در calculate_daily_attendance (attendance_policy_service).
    """
    if target_date.weekday() == 4:  # Friday
        return True

    employment_type = employee.department if employee else None
    query = db.query(Holiday).filter(Holiday.holiday_date == target_date)
    if employment_type:
        query = query.filter(
            or_(Holiday.group_id.is_(None), Holiday.group_id == employment_type)
        )
    else:
        query = query.filter(Holiday.group_id.is_(None))
    return query.first() is not None


# ============================================
# Submission-time Validation
# ============================================

def validate_hourly_mission_request(
    db: Session,
    employee: Employee,
    mission_date: date,
    start_time: time,
    end_time: time,
    exclude_mission_id: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    اعتبارسنجی درخواست مأموریت ساعتی در زمان ثبت.

    Returns:
        (is_valid, error_message)
    """
    if employee is None:
        return False, "کارمند یافت نشد"

    # ۱. فعال بودن قابلیت
    settings = get_effective_hourly_mission_settings(db, employee, mission_date)
    if not settings.get('enabled', True):
        return False, "مأموریت ساعتی برای این کارمند فعال نیست"

    # ۲. وجود و ترتیب start/end + duration مثبت
    if start_time is None or end_time is None:
        return False, "ساعت شروع و پایان باید مشخص باشند"
    if start_time >= end_time:
        return False, "ساعت شروع باید قبل از ساعت پایان باشد"
    duration = compute_mission_minutes(start_time, end_time)
    if duration <= 0:
        return False, "مدت مأموریت باید مثبت باشد"

    # ۳. روز تعطیل (allowed_on_holidays=false → رد)
    if not settings.get('allowed_on_holidays', False):
        if is_holiday_for_employee(db, employee, mission_date):
            return False, "مأموریت ساعتی در روز تعطیل مجاز نیست"

    # ۴. ساعات موظفی + روز غیرکاری (working_hours_only=true)
    if settings.get('working_hours_only', True):
        attendance_policy = resolve_attendance_policy(db, employee, mission_date)
        policy_day = resolve_policy_day(attendance_policy, mission_date)

        if policy_day is None:
            # بدون AttendancePolicy → محدودیت ساعات موظفی قابل اعمال نیست
            # (همان رفتار hourly leave: skip)
            pass
        elif not policy_day.is_working_day:
            # روز غیرکاری در AttendancePolicyDay — حتی اگر holiday نباشد
            # working_hours_only=true → ساعات موظفی ندارد → رد
            return False, (
                "مأموریت ساعتی فقط در روزهای کاری "
                "(طبق سیاست حضور) امکان‌پذیر است"
            )
        else:
            start_min = time_to_minutes(start_time)
            end_min = time_to_minutes(end_time)
            work_start = (
                time_to_minutes(policy_day.start_time)
                if policy_day.start_time else None
            )
            work_end = (
                time_to_minutes(policy_day.end_time)
                if policy_day.end_time else None
            )
            if work_start is not None and start_min < work_start:
                return False, "ساعت شروع مأموریت قبل از ساعت شروع شیفت کاری است"
            if work_end is not None and end_min > work_end:
                return False, "ساعت پایان مأموریت بعد از ساعت پایان شیفت کاری است"

    # ۵. حداقل/حداکثر مدت و granularity:
    # HourlyMissionPolicy فیلد min/max/granularity ندارد (برخلاف HourlyLeavePolicy).
    # محدودیت جدید اختراع نمی‌شود — فقط start < end.

    # ۶. Overlap با مأموریت‌های موجود (P/A)
    start_min = time_to_minutes(start_time)
    end_min = time_to_minutes(end_time)
    query = db.query(HourlyMission).filter(
        and_(
            HourlyMission.user_id == employee.user_id,
            HourlyMission.mission_date == mission_date,
            HourlyMission.status.in_(OVERLAP_BLOCKING_STATUSES),
        )
    )
    if exclude_mission_id is not None:
        query = query.filter(HourlyMission.id != exclude_mission_id)

    for existing in query.all():
        ex_start = time_to_minutes(existing.start_time)
        ex_end = time_to_minutes(existing.end_time)
        # Overlap: NOT (new_end <= ex_start OR new_start >= ex_end)
        # بازه‌های مجاور (end == start دیگری) overlap نیستند
        if not (end_min <= ex_start or start_min >= ex_end):
            return False, "با مأموریت ساعتی موجود در این تاریخ تداخل زمانی دارد"

    return True, None
