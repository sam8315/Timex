"""
Shared Daily Status Resolver

Centralizes mission/rest/leave/holiday status resolution for:
- User Attendance page
- Admin Attendance page
- Monthly Statistics report
- Detailed Monthly V2 report
- Monthly Full report (via V2)

Status priority (from audit):
1. معرفی (intro) — hire/contract start
2. تسویه (settle) — contract end / termination
3. Approved full-day leave
4. Mission (M)
5. Rest (R)
6. Friday / official holiday
7. Attendance exists → Present
8. No attendance → Absent
"""
from datetime import date
from typing import Dict, Optional, Set, List
from dataclasses import dataclass

from models.daily_status import DailyStatus, STATUS_CODES


# Status codes (reuse existing project codes)
STATUS_CODE_MISSION = 'M'
STATUS_CODE_REST = 'R'

# Internal status keys for resolved results
STATUS_KEY_MISSION = 'mission'
STATUS_KEY_REST = 'rest'
STATUS_KEY_LEAVE = 'leave'
STATUS_KEY_HOLIDAY = 'holiday'
STATUS_KEY_FRIDAY = 'friday'
STATUS_KEY_PRESENT = 'present'
STATUS_KEY_ABSENT = 'absent'
STATUS_KEY_INTRO = 'intro'
STATUS_KEY_SETTLE = 'settle'


@dataclass
class DayStatusResult:
    """Resolved status for a single day."""
    status_code: str           # Internal status key (STATUS_KEY_*)
    status_name: str           # Persian display name
    status_display: str        # Badge/label for UI (with emoji)
    is_duty_exempt: bool       # True if M/R/Leave/Holiday/Friday → no duty
    required_minutes: int      # 0 when exempt
    daily_status_code: Optional[str]  # Raw DailyStatus code (M/R) or None
    attendance_records: list   # Actual attendance records (preserved)
    work_minutes: int          # Actual work minutes from attendance
    deficit_minutes: int       # 0 when exempt
    surplus_minutes: int       # Any surplus (only when not exempt)


@dataclass
class DayContext:
    """Input context for resolving a day's status."""
    target_date: date
    is_friday: bool
    is_holiday: bool
    holiday_title: Optional[str]
    is_leave: bool
    leave_type: Optional[str]
    daily_status_code: Optional[str]   # M, R, or None
    has_attendance: bool
    attendance_records: list
    work_minutes: int                  # Calculated work minutes


def resolve_day_status(ctx: DayContext) -> DayStatusResult:
    """
    Resolve the status for a single day based on the priority chain.

    This is the SINGLE source of truth for daily status resolution.
    All consumers (user attendance, admin attendance, reports) must use this.
    """
    # Priority 1-2: Intro/Settle are handled at the caller level
    # (they need contract/hire info which varies by context)

    # Priority 3: Approved full-day leave
    if ctx.is_leave:
        return _make_leave_result(ctx)

    # Priority 4: Mission (M)
    if ctx.daily_status_code == STATUS_CODE_MISSION:
        return _make_mission_result(ctx)

    # Priority 5: Rest (R)
    if ctx.daily_status_code == STATUS_CODE_REST:
        return _make_rest_result(ctx)

    # Priority 6: Friday / holiday
    if ctx.is_friday:
        return _make_friday_result(ctx)

    if ctx.is_holiday:
        return _make_holiday_result(ctx)

    # Priority 7: Attendance exists → Present
    if ctx.has_attendance:
        return _make_present_result(ctx)

    # Priority 8: No attendance → Absent
    return _make_absent_result(ctx)


def build_daily_status_map(
    db_session,
    user_id: str,
    start_date: date,
    end_date: date,
) -> Dict[date, str]:
    """
    Fetch all DailyStatus records for a user in a date range.
    Returns: {date: status_code}
    """
    statuses = db_session.query(DailyStatus).filter(
        DailyStatus.user_id == user_id,
        DailyStatus.status_date >= start_date,
        DailyStatus.status_date <= end_date,
    ).all()

    return {ds.status_date: ds.status_code for ds in statuses}


def build_mission_dates(
    daily_status_map: Dict[date, str],
) -> Set[date]:
    """Extract mission dates from a daily_status_map."""
    return {d for d, c in daily_status_map.items() if c == STATUS_CODE_MISSION}


def build_rest_dates(
    daily_status_map: Dict[date, str],
) -> Set[date]:
    """Extract rest dates from a daily_status_map."""
    return {d for d, c in daily_status_map.items() if c == STATUS_CODE_REST}


def get_status_display_code(
    daily_status_code: Optional[str],
    is_friday: bool,
    is_holiday: bool,
    has_attendance: bool,
    is_leave: bool,
) -> str:
    """
    Get the one-character display code for monthly stats grid.
    M → م, R → اس, leave → code, etc.
    """
    if daily_status_code == STATUS_CODE_MISSION:
        return 'م'
    if daily_status_code == STATUS_CODE_REST:
        return 'اس'
    # Leave codes are handled by the caller via leaves_by_date
    return None


# ============================================
# Internal builders
# ============================================

def _make_mission_result(ctx: DayContext) -> DayStatusResult:
    return DayStatusResult(
        status_code=STATUS_KEY_MISSION,
        status_name='مأموریت',
        status_display='🟦 مأموریت',
        is_duty_exempt=True,
        required_minutes=0,
        daily_status_code=STATUS_CODE_MISSION,
        attendance_records=ctx.attendance_records,
        work_minutes=ctx.work_minutes,
        deficit_minutes=0,
        surplus_minutes=ctx.work_minutes if ctx.work_minutes > 0 else 0,
    )


def _make_rest_result(ctx: DayContext) -> DayStatusResult:
    return DayStatusResult(
        status_code=STATUS_KEY_REST,
        status_name='استراحت',
        status_display='🟣 استراحت',
        is_duty_exempt=True,
        required_minutes=0,
        daily_status_code=STATUS_CODE_REST,
        attendance_records=ctx.attendance_records,
        work_minutes=ctx.work_minutes,
        deficit_minutes=0,
        surplus_minutes=ctx.work_minutes if ctx.work_minutes > 0 else 0,
    )


def _make_leave_result(ctx: DayContext) -> DayStatusResult:
    LEAVE_NAMES = {
        'AL': 'استحقاقی', 'SL': 'استعلاجی', 'RL': 'تشویقی',
        'UL': 'بدون حقوق', 'CW': 'ذخیره',
    }
    leave_name = LEAVE_NAMES.get(ctx.leave_type, ctx.leave_type or '')
    return DayStatusResult(
        status_code=STATUS_KEY_LEAVE,
        status_name=f'مرخصی {leave_name}',
        status_display=f'🌴 مرخصی {leave_name}',
        is_duty_exempt=True,
        required_minutes=0,
        daily_status_code=None,
        attendance_records=ctx.attendance_records,
        work_minutes=ctx.work_minutes,
        deficit_minutes=0,
        surplus_minutes=0,
    )


def _make_friday_result(ctx: DayContext) -> DayStatusResult:
    if ctx.has_attendance:
        return DayStatusResult(
            status_code=STATUS_KEY_PRESENT,
            status_name='جمعه‌کاری',
            status_display='✅ جمعه‌کاری',
            is_duty_exempt=True,
            required_minutes=0,
            daily_status_code=None,
            attendance_records=ctx.attendance_records,
            work_minutes=ctx.work_minutes,
            deficit_minutes=0,
            surplus_minutes=ctx.work_minutes,
        )
    return DayStatusResult(
        status_code=STATUS_KEY_FRIDAY,
        status_name='جمعه',
        status_display='🟡 جمعه',
        is_duty_exempt=True,
        required_minutes=0,
        daily_status_code=None,
        attendance_records=[],
        work_minutes=0,
        deficit_minutes=0,
        surplus_minutes=0,
    )


def _make_holiday_result(ctx: DayContext) -> DayStatusResult:
    if ctx.has_attendance:
        return DayStatusResult(
            status_code=STATUS_KEY_PRESENT,
            status_name=f'تعطیل‌کاری ({ctx.holiday_title})',
            status_display=f'🔴 تعطیل‌کاری ({ctx.holiday_title})',
            is_duty_exempt=True,
            required_minutes=0,
            daily_status_code=None,
            attendance_records=ctx.attendance_records,
            work_minutes=ctx.work_minutes,
            deficit_minutes=0,
            surplus_minutes=ctx.work_minutes,
        )
    return DayStatusResult(
        status_code=STATUS_KEY_HOLIDAY,
        status_name=f'تعطیل ({ctx.holiday_title})',
        status_display=f'🔴 تعطیل: {ctx.holiday_title}',
        is_duty_exempt=True,
        required_minutes=0,
        daily_status_code=None,
        attendance_records=[],
        work_minutes=0,
        deficit_minutes=0,
        surplus_minutes=0,
    )


def _make_present_result(ctx: DayContext) -> DayStatusResult:
    return DayStatusResult(
        status_code=STATUS_KEY_PRESENT,
        status_name='حاضر',
        status_display='✅ کامل',
        is_duty_exempt=False,
        required_minutes=0,  # Caller should set this from policy
        daily_status_code=None,
        attendance_records=ctx.attendance_records,
        work_minutes=ctx.work_minutes,
        deficit_minutes=0,   # Caller should calculate
        surplus_minutes=0,   # Caller should calculate
    )


def _make_absent_result(ctx: DayContext) -> DayStatusResult:
    return DayStatusResult(
        status_code=STATUS_KEY_ABSENT,
        status_name='غایب',
        status_display='⚪ بدون تردد',
        is_duty_exempt=False,
        required_minutes=0,  # Caller should set this from policy
        daily_status_code=None,
        attendance_records=[],
        work_minutes=0,
        deficit_minutes=0,   # Caller should calculate
        surplus_minutes=0,
    )
