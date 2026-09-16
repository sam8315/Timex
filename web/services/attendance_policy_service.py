"""
سرویس مرکزی سیاست‌های حضور و غیاب (Attendance Policy Service)

این سرویس تمام محاسبات مربوط به Required Work، Late، Early Leave و Balance
را متمرکز کرده و توسط User View، Manager View و Reports استفاده می‌شود.

طراحی شده برای پشتیبانی از:
- Employment Type Policy (رسمی، وظیفه، خریدخدمت، قراردادی، پزشک)
- Employee Override (سیاست مخصوص یک کارمند)
- Historical Policies (سیاست‌های تاریخی با effective_from/effective_to)
- Future Shift Integration (رابط برای شیفت در آینده)
"""
from datetime import date, datetime, time, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from models.employee import Employee
from models.attendance import Attendance, AttendancePolicy, AttendancePolicyDay
from models.holiday import Holiday
from models.leave_request import LeaveRequest
from models.daily_status import DailyStatus


class ReferenceMode(str, Enum):
    """حالت مرجع برای محاسبه دیرکرد/زودکرد"""
    FIXED_TIME = "FIXED_TIME"
    SHIFT = "SHIFT"  # آینده - فعلاً پشتیبانی نمی‌شود


@dataclass
class PolicyDayInfo:
    """اطلاعات یک روز از برنامه هفتگی"""
    weekday: int  # 0=Mon ... 6=Sun
    is_working_day: bool
    start_time: Optional[time]
    end_time: Optional[time]
    required_minutes: Optional[int]  # دقیقه موظفی (برای روزهای کاری)


@dataclass
class ResolvedPolicy:
    """سیاست حل‌شده برای یک تاریخ و کارمند خاص"""
    policy: AttendancePolicy
    employment_type_code: str
    policy_days: Dict[int, PolicyDayInfo]  # weekday -> PolicyDayInfo
    is_employee_override: bool


@dataclass
class DailyAttendanceResult:
    """نتیجه محاسبات روزانه"""
    date: date
    is_friday: bool
    is_holiday: bool
    holiday_title: Optional[str]
    is_leave: bool
    leave_type: Optional[str]
    is_mission: bool  # DailyStatus M
    is_rest: bool     # DailyStatus R

    # از Policy
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    required_minutes: int  # 0 برای Non-working/Holiday/Leave

    # از تردد
    actual_minutes: int  # دقیقه کارکرد واقعی
    first_enter: Optional[datetime]
    last_exit: Optional[datetime]

    # Late
    late_enabled: bool
    total_late_minutes: int
    late_allowed_minutes: int
    late_violation_minutes: int
    is_late: bool
    late_reference_mode: str

    # Early Leave
    early_leave_enabled: bool
    total_early_leave_minutes: int
    early_leave_allowed_minutes: int
    early_leave_violation_minutes: int
    is_early_leave: bool
    early_reference_mode: str

    # Balance
    balance_minutes: int  # Actual - Required (Late/Early جدا محاسبه می‌شود)

    def to_dict(self) -> dict:
        return {
            'date': self.date,
            'is_friday': self.is_friday,
            'is_holiday': self.is_holiday,
            'holiday_title': self.holiday_title,
            'is_leave': self.is_leave,
            'leave_type': self.leave_type,
            'is_mission': self.is_mission,
            'is_rest': self.is_rest,
            'scheduled_start': self.scheduled_start.strftime('%H:%M') if self.scheduled_start else None,
            'scheduled_end': self.scheduled_end.strftime('%H:%M') if self.scheduled_end else None,
            'required_minutes': self.required_minutes,
            'actual_minutes': self.actual_minutes,
            'late_enabled': self.late_enabled,
            'total_late_minutes': self.total_late_minutes,
            'late_allowed_minutes': self.late_allowed_minutes,
            'late_violation_minutes': self.late_violation_minutes,
            'is_late': self.is_late,
            'early_leave_enabled': self.early_leave_enabled,
            'total_early_leave_minutes': self.total_early_leave_minutes,
            'early_leave_allowed_minutes': self.early_leave_allowed_minutes,
            'early_leave_violation_minutes': self.early_leave_violation_minutes,
            'is_early_leave': self.is_early_leave,
            'balance_minutes': self.balance_minutes,
        }


# ============================================
# 🆕 Fallback Configuration (برای حفظ رفتار فعلی در صورت عدم وجود Policy)
# ============================================

# مقدار پیش‌فرض برای حفظ رفتار legacy: 7:20 = 440 دقیقه
DEFAULT_REQUIRED_MINUTES = 440  # 7h 20m

# ============================================
# 🆕 توابع کمکی برای تبدیل فرمت‌ها
# ============================================

def minutes_to_hours_hhmm(minutes: int) -> str:
    """تبدیل دقیقه به فرمت H:MM"""
    if minutes is None:
        return '-'
    sign = '-' if minutes < 0 else ''
    minutes = abs(minutes)
    h = minutes // 60
    m = minutes % 60
    return f"{sign}{h}:{m:02d}"


def time_to_minutes(t: time) -> int:
    """تبدیل time به دقیقه"""
    if t is None:
        return 0
    return t.hour * 60 + t.minute


# ============================================
# 🆕 Policy Resolution
# ============================================

def resolve_policy(db: Session, employee: Employee, target_date: date) -> Optional[ResolvedPolicy]:
    """
    پیدا کردن سیاست معتبر برای یک کارمند در یک تاریخ

    Priority:
    1. Employee Override (user_id = employee.user_id)
    2. Employment Type Policy (employment_type_code = employee.department)

    Returns:
        ResolvedPolicy یا None اگر سیافت نشود
    """
    employment_type = employee.department if employee else None

    if not employment_type:
        return None

    # مرحله ۱: جستجوی Employee Override
    query = db.query(AttendancePolicy).filter(
        and_(
            AttendancePolicy.user_id == employee.user_id,
            AttendancePolicy.is_active == True,
            AttendancePolicy.effective_from_date <= target_date,
            or_(
                AttendancePolicy.effective_to_date.is_(None),
                AttendancePolicy.effective_to_date >= target_date
            )
        )
    ).order_by(AttendancePolicy.effective_from_date.desc())

    override_policy = query.first()

    if override_policy:
        # Load days
        days = db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id == override_policy.id
        ).all()

        policy_days = {}
        for d in days:
            policy_days[d.weekday] = PolicyDayInfo(
                weekday=d.weekday,
                is_working_day=d.is_working_day,
                start_time=d.start_time,
                end_time=d.end_time,
                required_minutes=d.required_minutes
            )

        return ResolvedPolicy(
            policy=override_policy,
            employment_type_code=employment_type,
            policy_days=policy_days,
            is_employee_override=True
        )

    # مرحله ۲: جستجوی Employment Type Policy
    query = db.query(AttendancePolicy).filter(
        and_(
            AttendancePolicy.employment_type_code == employment_type,
            AttendancePolicy.user_id.is_(None),  # فقط Employment Type
            AttendancePolicy.is_active == True,
            AttendancePolicy.effective_from_date <= target_date,
            or_(
                AttendancePolicy.effective_to_date.is_(None),
                AttendancePolicy.effective_to_date >= target_date
            )
        )
    ).order_by(AttendancePolicy.effective_from_date.desc())

    emp_policy = query.first()

    if emp_policy:
        # Load days
        days = db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id == emp_policy.id
        ).all()

        policy_days = {}
        for d in days:
            policy_days[d.weekday] = PolicyDayInfo(
                weekday=d.weekday,
                is_working_day=d.is_working_day,
                start_time=d.start_time,
                end_time=d.end_time,
                required_minutes=d.required_minutes
            )

        return ResolvedPolicy(
            policy=emp_policy,
            employment_type_code=employment_type,
            policy_days=policy_days,
            is_employee_override=False
        )

    return None


def resolve_policy_day(resolved: Optional[ResolvedPolicy], target_date: date) -> Optional[PolicyDayInfo]:
    """
    دریافت اطلاعات روز از سیاست

    Returns:
        PolicyDayInfo برای روز مورد نظر، یا None اگر Policy وجود نداشته باشد
    """
    if not resolved:
        return None

    weekday = target_date.weekday()  # 0=Mon ... 6=Sun
    return resolved.policy_days.get(weekday)


def resolve_scheduled_times(
    resolved: Optional[ResolvedPolicy],
    target_date: date
) -> Tuple[Optional[time], Optional[time]]:
    """
    دریافت ساعت‌های ورود و خروج برنامه‌ریزی‌شده

    Returns:
        (start_time, end_time) یا (None, None) اگر Policy یا روز کاری وجود نداشته باشد
    """
    policy_day = resolve_policy_day(resolved, target_date)

    if not policy_day or not policy_day.is_working_day:
        return None, None

    return policy_day.start_time, policy_day.end_time


def resolve_required_minutes(
    resolved: Optional[ResolvedPolicy],
    target_date: date,
    is_holiday: bool = False,
    is_leave: bool = False,
    is_mission: bool = False,
    is_rest: bool = False,
    is_friday: bool = False
) -> int:
    """
    محاسبه دقایق موظفی برای یک روز

    Rules (from Phase 4):
    - Non-working Day: 0
    - Holiday: 0
    - Full-day Leave: 0
    - Mission: 0 (طبق رفتار فعلی)
    - Rest: 0 (طبق رفتار فعلی)
    - Friday: از Policy (می‌تواند Non-working باشد)
    - Working Day: از Policy.schedule

    Returns:
        دقایق موظفی (یا DEFAULT_REQUIRED_MINUTES اگر Policy وجود نداشته باشد)
    """
    # روزهای بدون کارکرد موظفی
    if is_holiday or is_leave or is_mission or is_rest:
        return 0

    policy_day = resolve_policy_day(resolved, target_date)

    if not policy_day:
        # Fallback: اگر Policy وجود ندارد از رفتار قبلی استفاده کن
        # این فقط برای سازگاری با داده‌های قدیمی است
        if is_friday:
            return 0  # جمعه پیش‌فرض تعطیل
        return DEFAULT_REQUIRED_MINUTES

    if not policy_day.is_working_day:
        return 0

    return policy_day.required_minutes or 0


def compute_required_minutes_for_range(
    db: Session,
    employee: Employee,
    start_date: date,
    end_date: date,
    rest_dates: set,
    holiday_dates: dict,
    leaves_by_date: dict,
    hourly_leave_minutes_by_date: dict = None,
    mission_dates: set = None,
) -> int:
    """
    مجموع دقایق موظفی برای یک بازه تاریخی (بر اساس Policy)

    جایگزین N_days × DAILY_DUTY_HOURS می‌شود.
    برای هر روز: resolve_policy → resolve_required_minutes → جمع‌بندی

    Fallback: اگر Policy وجود نداشته باشد، DEFAULT_REQUIRED_MINUTES (440)
    برای روزهای کاری (غیر جمعه) استفاده می‌شود — رفتار فعلی حفظ می‌شود.

    Phase 7: hourly_leave_minutes_by_date (dict[date, int]) — approved HL minutes
    per date. Subtracted from base required minutes: effective = max(0, base - hl).
    """
    if hourly_leave_minutes_by_date is None:
        hourly_leave_minutes_by_date = {}
    if mission_dates is None:
        mission_dates = set()

    total = 0
    current = start_date
    while current <= end_date:
        resolved = resolve_policy(db, employee, current)
        base_required = resolve_required_minutes(
            resolved=resolved,
            target_date=current,
            is_holiday=current in holiday_dates,
            is_leave=current in leaves_by_date,
            is_mission=current in mission_dates,
            is_rest=current in rest_dates,
            is_friday=current.weekday() == 4,
        )

        # Phase 7: subtract approved HL minutes from required (not from actual)
        hl_minutes = hourly_leave_minutes_by_date.get(current, 0)
        effective_required = max(0, base_required - hl_minutes)

        total += effective_required
        current += timedelta(days=1)
    return total


# ============================================
# 🆕 Late / Early Leave Computation
# ============================================

def compute_late(
    actual_first_check_in: Optional[datetime],
    scheduled_start: Optional[time],
    late_enabled: bool,
    late_allowed_minutes: int,
    reference_mode: str
) -> Dict:
    """
    محاسبه دیرکرد

    Formula:
        total_late_minutes = max(0, actual_first_check_in - scheduled_start)
        late_violation_minutes = max(0, total_late_minutes - late_allowed_minutes)
        is_late = total_late_minutes > late_allowed_minutes
    """
    if not late_enabled or not actual_first_check_in or not scheduled_start:
        return {
            'total_late_minutes': 0,
            'late_violation_minutes': 0,
            'is_late': False
        }

    # ترکیب تاریخ و ساعت برای محاسبه
    scheduled_dt = datetime.combine(actual_first_check_in.date(), scheduled_start)
    if actual_first_check_in.tzinfo:
        scheduled_dt = scheduled_dt.replace(tzinfo=actual_first_check_in.tzinfo)

    diff_seconds = (actual_first_check_in - scheduled_dt).total_seconds()
    total_late_minutes = max(0, int(diff_seconds / 60))

    late_violation_minutes = max(0, total_late_minutes - late_allowed_minutes)
    is_late = total_late_minutes > late_allowed_minutes

    return {
        'total_late_minutes': total_late_minutes,
        'late_violation_minutes': late_violation_minutes,
        'is_late': is_late
    }


def compute_early_leave(
    actual_last_check_out: Optional[datetime],
    scheduled_end: Optional[time],
    early_leave_enabled: bool,
    early_leave_allowed_minutes: int,
    reference_mode: str
) -> Dict:
    """
    محاسبه خروج زود

    Formula:
        total_early_leave_minutes = max(0, scheduled_end - actual_last_check_out)
        early_leave_violation_minutes = max(0, total_early_leave_minutes - early_leave_allowed_minutes)
        is_early_leave = total_early_leave_minutes > early_leave_allowed_minutes
    """
    if not early_leave_enabled or not actual_last_check_out or not scheduled_end:
        return {
            'total_early_leave_minutes': 0,
            'early_leave_violation_minutes': 0,
            'is_early_leave': False
        }

    # ترکیب تاریخ و ساعت برای محاسبه
    scheduled_dt = datetime.combine(actual_last_check_out.date(), scheduled_end)
    if actual_last_check_out.tzinfo:
        scheduled_dt = scheduled_dt.replace(tzinfo=actual_last_check_out.tzinfo)

    diff_seconds = (scheduled_dt - actual_last_check_out).total_seconds()
    total_early_leave_minutes = max(0, int(diff_seconds / 60))

    early_leave_violation_minutes = max(0, total_early_leave_minutes - early_leave_allowed_minutes)
    is_early_leave = total_early_leave_minutes > early_leave_allowed_minutes

    return {
        'total_early_leave_minutes': total_early_leave_minutes,
        'early_leave_violation_minutes': early_leave_violation_minutes,
        'is_early_leave': is_early_leave
    }


# ============================================
# 🆕 Daily Balance Computation
# ============================================

def compute_daily_balance(
    actual_minutes: int,
    required_minutes: int,
    late_info: Dict,
    early_info: Dict
) -> int:
    """
    محاسبه تراز روزانه

    Formula (from Phase 4):
        Balance = Actual Work Minutes - Required Work Minutes

    نکته مهم: Late و Early از Balance کم نمی‌شوند (Double Counting ممنوع)
    این مقادیر فقط برای نمایش و گزارش استفاده می‌شوند
    """
    return actual_minutes - required_minutes


# ============================================
# 🆕 Main Daily Calculation
# ============================================

def calculate_daily_attendance(
    db: Session,
    employee: Employee,
    target_date: date,
    day_records: List[Attendance],
    is_friday: bool = False,
    prev_day_records: List[Attendance] = None,
    next_day_records: List[Attendance] = None
) -> DailyAttendanceResult:
    """
    محاسبه کامل وضعیت روزانه برای یک کارمند

    این تابع اصلی است که توسط تمام بخش‌ها (User, Manager, Reports) استفاده می‌شود
    """
    from web.routes.attendance import analyze_day_status

    # ۱. بررسی تعطیلی
    employment_type = employee.department if employee else None
    holiday_query = db.query(Holiday).filter(Holiday.holiday_date == target_date)
    if employment_type:
        holiday_query = holiday_query.filter(
            or_(Holiday.group_id.is_(None), Holiday.group_id == employment_type)
        )
    else:
        holiday_query = holiday_query.filter(Holiday.group_id.is_(None))
    holiday = holiday_query.first()

    is_holiday = holiday is not None
    holiday_title = holiday.title if holiday else None

    # ۲. بررسی مرخصی
    leave = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == employee.user_id,
            LeaveRequest.status == 'A',
            LeaveRequest.from_date <= target_date,
            LeaveRequest.to_date >= target_date
        )
    ).first()

    is_leave = leave is not None
    leave_type = leave.leave_type if leave else None

    # ۳. بررسی مأموریت/استراحت
    daily_status = db.query(DailyStatus).filter(
        and_(
            DailyStatus.user_id == employee.user_id,
            DailyStatus.status_date == target_date
        )
    ).first()

    is_mission = daily_status and daily_status.status_code == 'M'
    is_rest = daily_status and daily_status.status_code == 'R'

    # ۴. Resolve Policy
    resolved = resolve_policy(db, employee, target_date)

    # ۵. دریافت ساعت‌های برنامه‌ریزی‌شده
    scheduled_start_time, scheduled_end_time = resolve_scheduled_times(resolved, target_date)

    # ۶. محاسبه Required Minutes
    required_minutes = resolve_required_minutes(
        resolved=resolved,
        target_date=target_date,
        is_holiday=is_holiday,
        is_leave=is_leave,
        is_mission=is_mission,
        is_rest=is_rest,
        is_friday=is_friday
    )

    # ۷. تشخیص Night Shift و محاسبه Actual Minutes
    status_info = analyze_day_status(
        day=target_date,
        day_records=day_records,
        prev_day_records=prev_day_records or [],
        next_day_records=next_day_records or [],
        is_friday=is_friday,
        holiday_title=holiday_title
    )
    is_night_shift = status_info.get('main_status') == 'night_shift'

    # محاسبه کارکرد واقعی (از تابع موجود)
    from web.routes.attendance import calculate_work_hours
    work_hours, first_enter, last_exit = calculate_work_hours(day_records, is_night_shift)
    actual_minutes = int(work_hours * 60)

    # ۸. Late Calculation
    late_enabled = resolved.policy.late_enabled if resolved else True
    late_allowed = resolved.policy.late_allowed_minutes if resolved else 0
    late_ref_mode = resolved.policy.late_reference_mode if resolved else 'FIXED_TIME'

    late_info = compute_late(
        actual_first_check_in=first_enter,
        scheduled_start=scheduled_start_time,
        late_enabled=late_enabled,
        late_allowed_minutes=late_allowed,
        reference_mode=late_ref_mode
    )

    # ۹. Early Leave Calculation
    early_enabled = resolved.policy.early_leave_enabled if resolved else True
    early_allowed = resolved.policy.early_leave_allowed_minutes if resolved else 0
    early_ref_mode = resolved.policy.early_leave_reference_mode if resolved else 'FIXED_TIME'

    early_info = compute_early_leave(
        actual_last_check_out=last_exit,
        scheduled_end=scheduled_end_time,
        early_leave_enabled=early_enabled,
        early_leave_allowed_minutes=early_allowed,
        reference_mode=early_ref_mode
    )

    # ۱۰. Balance
    balance_minutes = compute_daily_balance(
        actual_minutes=actual_minutes,
        required_minutes=required_minutes,
        late_info=late_info,
        early_info=early_info
    )

    # ساخت نتیجه
    return DailyAttendanceResult(
        date=target_date,
        is_friday=is_friday,
        is_holiday=is_holiday,
        holiday_title=holiday_title,
        is_leave=is_leave,
        leave_type=leave_type,
        is_mission=is_mission,
        is_rest=is_rest,
        scheduled_start=datetime.combine(target_date, scheduled_start_time) if scheduled_start_time else None,
        scheduled_end=datetime.combine(target_date, scheduled_end_time) if scheduled_end_time else None,
        required_minutes=required_minutes,
        actual_minutes=actual_minutes,
        first_enter=first_enter,
        last_exit=last_exit,
        late_enabled=late_enabled,
        total_late_minutes=late_info['total_late_minutes'],
        late_allowed_minutes=late_allowed,
        late_violation_minutes=late_info['late_violation_minutes'],
        is_late=late_info['is_late'],
        late_reference_mode=late_ref_mode,
        early_leave_enabled=early_enabled,
        total_early_leave_minutes=early_info['total_early_leave_minutes'],
        early_leave_allowed_minutes=early_allowed,
        early_leave_violation_minutes=early_info['early_leave_violation_minutes'],
        is_early_leave=early_info['is_early_leave'],
        early_reference_mode=early_ref_mode,
        balance_minutes=balance_minutes
    )


# ============================================
# 🆕 Weekly Schedule Helpers
# ============================================

def get_default_schedule() -> Dict[int, PolicyDayInfo]:
    """
    دریافت برنامه پیش‌فرض (برای نمایش در UI)
    شنبه تا پنج‌شنبه: 07:00 - 14:00 (7h 20m = 440 min)
    جمعه: تعطیل
    """
    schedule = {}

    # شنبه (0) تا چهارشنبه (3): کامل
    for wd in range(4):
        schedule[wd] = PolicyDayInfo(
            weekday=wd,
            is_working_day=True,
            start_time=time(7, 0),
            end_time=time(14, 0),
            required_minutes=420  # 7h
        )

    # پنج‌شنبه (4): نیم‌روز
    schedule[4] = PolicyDayInfo(
        weekday=4,
        is_working_day=True,
        start_time=time(7, 0),
        end_time=time(11, 30),
        required_minutes=270  # 4.5h
    )

    # جمعه (5): تعطیل
    schedule[5] = PolicyDayInfo(
        weekday=5,
        is_working_day=False,
        start_time=None,
        end_time=None,
        required_minutes=0
    )

    # شنبه (6): کامل
    schedule[6] = PolicyDayInfo(
        weekday=6,
        is_working_day=True,
        start_time=time(7, 0),
        end_time=time(14, 0),
        required_minutes=420  # 7h
    )

    return schedule


def policy_day_to_dict(pd: PolicyDayInfo) -> dict:
    """تبدیل PolicyDayInfo به dict برای JSON serialization"""
    return {
        'weekday': pd.weekday,
        'is_working_day': pd.is_working_day,
        'start_time': pd.start_time.strftime('%H:%M') if pd.start_time else None,
        'end_time': pd.end_time.strftime('%H:%M') if pd.end_time else None,
        'required_minutes': pd.required_minutes
    }


def format_balance_minutes(minutes: int) -> str:
    """فرمت‌بندی تراز برای نمایش"""
    return minutes_to_hours_hhmm(minutes)