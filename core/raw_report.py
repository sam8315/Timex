"""مرکزی‌سازی دیتاست گزارش خام تردد."""
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

import jdatetime
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from models.attendance import Attendance
from models.contract import CONTRACT_TYPES
from models.daily_status import DailyStatus
from models.employee import Employee
from models.holiday import Holiday
from models.hourly_mission import HourlyMission
from models.leave_request import LeaveRequest
from web.services.hourly_mission_service import format_hm_display
from web.services.travel_leave_service import build_leave_days_by_date


JALALI_MONTHS = {
    1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
    4: 'تیر', 5: 'مرداد', 6: 'شهریور',
    7: 'مهر', 8: 'آبان', 9: 'آذر',
    10: 'دی', 11: 'بهمن', 12: 'اسفند',
}

DAY_NAMES_FA = {
    0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
    3: 'پنج‌شنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه',
}

LEAVE_TYPE_NAMES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'CW': 'ذخیره سال قبل',
    'UL': 'بدون حقوق',
    'TL': 'توراهی',
}

LEAVE_PERSON_STATUS = {
    'AL': 'مرخصی',
    'SL': 'مرخصی',
    'RL': 'مرخصی',
    'CW': 'مرخصی',
    'UL': 'مرخصی',
    'TL': 'مرخصی',
    'HL': 'مرخصی',
}

PERSON_STATUS_NAMES = {
    'P': 'حاضر',
    'M': 'مأموریت',
    'R': 'استراحت',
    'A': 'غایب',
    'N': 'بدون تردد',
    'H': 'تعطیل',
}

EMPLOYMENT_TYPE_OPTIONS = [
    ('all', 'همه'),
    ('1', 'رسمی'),
    ('2', 'وظیفه'),
    ('3', 'خریدخدمت'),
    ('4', 'قراردادی'),
    ('5', 'پزشک'),
    ('6', 'سایر / متفرقه'),
    ('7', 'قرارداد با بیمه‌ها'),
]

STATUS_FILTER_OPTIONS = [
    ('all', 'همه'),
    ('P', 'حاضر'),
    ('leave', 'انواع مرخصی'),
    ('M', 'مأموریت'),
    ('R', 'استراحت'),
    ('N', 'بدون تردد'),
    ('working', 'کاری'),
    ('off', 'تعطیل'),
]


def get_month_days_count(year: int, month: int) -> int:
    if month < 1 or month > 12:
        raise ValueError('ماه نامعتبر است')
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    try:
        return 30 if jdatetime.date(year, 1, 1).isleap() else 29
    except Exception:
        return 29


def get_month_end_jalali(year: int, month: int) -> jdatetime.date:
    if month == 12:
        return jdatetime.date(year, 12, get_month_days_count(year, month))
    return jdatetime.date(year, month + 1, 1) - timedelta(days=1)


def month_bounds(year: int, month: int) -> Tuple[date, date]:
    start_j = jdatetime.date(year, month, 1)
    end_j = get_month_end_jalali(year, month)
    return start_j.togregorian(), end_j.togregorian()


def fmt_time(value) -> str:
    if value is None:
        return '—'
    if isinstance(value, (datetime, time)):
        return f"{value.hour:02d}:{value.minute:02d}"
    return str(value)


def is_manual_source(source, status=None) -> bool:
    """رکورد دستی را با source استاندارد یا status قدیمی/دستی تشخیص می‌دهد."""
    return source == 'M' or status == 15


def _record_dict(record: Attendance) -> dict:
    return {
        'time': record.timestamp,
        'is_manual': is_manual_source(
            getattr(record, 'source', None),
            getattr(record, 'status', None),
        ),
        'punch': record.punch,
        'source': getattr(record, 'source', None),
        'status': getattr(record, 'status', None),
    }


def _format_segment(segment: dict) -> str:
    kind = segment['kind']
    if kind == 'pair':
        enter = segment['enter']
        exit_record = segment['exit']
        left = fmt_time(enter['time'])
        if enter['is_manual']:
            left += ' (M)'
        right = fmt_time(exit_record['time'])
        if exit_record['is_manual']:
            right += ' (M)'
        return f"{left} → {right}"
    record = segment['record']
    value = fmt_time(record['time'])
    if record['is_manual']:
        value += ' (M)'
    if kind == 'entry_only':
        return f"{value} → —"
    if kind == 'exit_only':
        return f"— → {value}"
    return f"{value} (نامشخص)"


def build_attendance_segments(records: List[Attendance]) -> List[dict]:
    """همه رکوردها را به‌ترتیب زمانی نگه می‌دارد و فقط برای نمایش جفت می‌کند.

    Pairing logic matches AttendanceAnalyzer:
    - one pending entry at a time
    - when a second consecutive entry appears, the previous becomes entry_only
    - the next exit pairs with the current pending entry
    - an exit without a pending entry is exit_only
    """
    ordered = sorted(records, key=lambda record: (record.timestamp, record.id or 0))
    pending_entry = None
    segments = []
    for record in ordered:
        if record.punch == 0:
            if pending_entry is not None:
                segments.append({
                    'kind': 'entry_only',
                    'record': pending_entry,
                })
            pending_entry = _record_dict(record)
        elif record.punch == 1:
            if pending_entry is not None:
                segments.append({
                    'kind': 'pair',
                    'enter': pending_entry,
                    'exit': _record_dict(record),
                })
                pending_entry = None
            else:
                segments.append({
                    'kind': 'exit_only',
                    'record': _record_dict(record),
                })
        else:
            segments.append({
                'kind': 'unknown',
                'record': _record_dict(record),
            })
    if pending_entry is not None:
        segments.append({
            'kind': 'entry_only',
            'record': pending_entry,
        })
    return segments


def format_attendance_display(records: List[Attendance]) -> str:
    segments = build_attendance_segments(records)
    return ' | '.join(_format_segment(segment) for segment in segments) if segments else '—'


class RawReportService:
    def __init__(self, db: Session):
        self.db = db

    def _holidays_by_date(self, start_g: date, end_g: date) -> Dict[date, List[Holiday]]:
        holidays = self.db.query(Holiday).filter(
            and_(Holiday.holiday_date >= start_g, Holiday.holiday_date <= end_g)
        ).all()
        result: Dict[date, List[Holiday]] = {}
        for holiday in holidays:
            result.setdefault(holiday.holiday_date, []).append(holiday)
        return result

    @staticmethod
    def _is_national(holiday: Holiday) -> bool:
        return bool(holiday.is_national) or holiday.group_id is None

    @classmethod
    def _applicable_holiday(
        cls,
        day: date,
        department: Optional[str],
        holidays_by_date: Dict[date, List[Holiday]],
    ) -> Optional[Holiday]:
        holidays = holidays_by_date.get(day, [])
        national = next((holiday for holiday in holidays if cls._is_national(holiday)), None)
        if national:
            return national
        return next((holiday for holiday in holidays if holiday.group_id == department), None)

    @staticmethod
    def _membership_name(department: Optional[str]) -> str:
        return CONTRACT_TYPES.get(department or '', {}).get('name', department or '-')

    @staticmethod
    def _holiday_dates_for_department(
        department: Optional[str],
        holidays_by_date: Dict[date, List[Holiday]],
    ) -> set:
        return {
            day
            for day, holidays in holidays_by_date.items()
            if any(
                RawReportService._is_national(holiday)
                or holiday.group_id == department
                for holiday in holidays
            )
        }

    @staticmethod
    def _hourly_leave_display(requests: List[LeaveRequest]) -> dict:
        ranges = []
        total_minutes = 0
        for request in requests:
            if request.start_time and request.end_time:
                ranges.append(f"{fmt_time(request.start_time)} تا {fmt_time(request.end_time)}")
                minutes = (
                    request.end_time.hour * 60 + request.end_time.minute
                    - request.start_time.hour * 60 - request.start_time.minute
                )
                total_minutes += max(0, minutes)
        return {
            'minutes': total_minutes,
            'display': '، '.join(ranges),
        }

    @staticmethod
    def _hourly_mission_export_detail(missions: List[HourlyMission]) -> List[dict]:
        """ساختار نمایشی مأموریت‌های ساعتی برای خروجی (start/end/minutes)."""
        detail = []
        for mission in missions:
            start = mission.start_time
            end = mission.end_time
            minutes = max(0, (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute))
            detail.append({
                'start': start.strftime('%H:%M'),
                'end': end.strftime('%H:%M'),
                'minutes': minutes,
            })
        return detail

    def _build_day(
        self,
        day: date,
        department: Optional[str],
        holidays_by_date: Dict[date, List[Holiday]],
        daily_status_map: Dict[date, str],
        leaves_by_date: Dict[date, str],
        hourly_leaves_by_date: Dict[date, List[LeaveRequest]],
        attendances: List[Attendance],
        hourly_missions_by_date: Optional[Dict[date, List[HourlyMission]]] = None,
    ) -> dict:
        holiday = self._applicable_holiday(day, department, holidays_by_date)
        is_day_off = day.weekday() == 4 or holiday is not None
        daily_status = daily_status_map.get(day)
        daily_leave = leaves_by_date.get(day)
        hourly_leaves = hourly_leaves_by_date.get(day, [])
        has_attendance = bool(attendances)

        # Phase 6B: approved HourlyMission (status='A') — display only.
        # Does NOT change person_status cascade (M/leave/rest/holiday stay).
        hourly_missions = (hourly_missions_by_date or {}).get(day, [])
        hourly_mission_display = format_hm_display(hourly_missions)
        hourly_mission_detail = self._hourly_mission_export_detail(hourly_missions)

        if daily_status == 'M':
            person_status = 'M'
        elif daily_status == 'R':
            person_status = 'R'
        elif daily_status in LEAVE_PERSON_STATUS:
            person_status = daily_status
            daily_leave = daily_status
        elif daily_status == 'A':
            person_status = 'A'
        elif daily_leave in LEAVE_PERSON_STATUS:
            person_status = daily_leave
        elif has_attendance:
            person_status = 'P'
        elif hourly_leaves and not is_day_off:
            person_status = 'HL'
        elif is_day_off:
            person_status = 'H'
        else:
            person_status = 'N'

        hourly_leave_display = self._hourly_leave_display(hourly_leaves)
        leave_parts = []
        if daily_leave in LEAVE_TYPE_NAMES:
            leave_parts.append(LEAVE_TYPE_NAMES[daily_leave])
        if hourly_leave_display.get('display'):
            leave_parts.append(f"ساعتی: {hourly_leave_display['display']}")
        leave_name = '\n'.join(leave_parts) if leave_parts else None

        return {
            'date': day,
            'jalali_date': jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d'),
            'day_name': DAY_NAMES_FA.get(day.weekday(), ''),
            'day_status': 'تعطیل' if is_day_off else 'کاری',
            'holiday_title': holiday.title if holiday else None,
            'person_status': person_status,
            'person_status_name': (
                LEAVE_PERSON_STATUS.get(person_status)
                or PERSON_STATUS_NAMES.get(person_status)
                or daily_status
                or person_status
            ),
            'leave_type': daily_leave if daily_leave in LEAVE_PERSON_STATUS else None,
            'leave_name': leave_name,
            'hourly_leave': hourly_leave_display,
            # Phase 6B: hourly mission display (independent of leave / punches)
            'hourly_mission_display': hourly_mission_display,
            'hourly_missions': hourly_mission_detail,
            'hourly_mission_minutes': sum(
                item['minutes'] for item in hourly_mission_detail
            ),
            'has_attendance': has_attendance,
            'punches': [_record_dict(record) for record in sorted(
                attendances, key=lambda record: (record.timestamp, record.id or 0)
            )],
            'attendance_segments': build_attendance_segments(attendances),
            'attendance_str': format_attendance_display(attendances),
        }

    def build_report(
        self,
        year: int,
        month: int,
        employee_user_id: Optional[str] = None,
        employment_type: str = 'all',
        status_filter: str = 'all',
    ) -> dict:
        start_g, end_g = month_bounds(year, month)
        end_exclusive = end_g + timedelta(days=1)
        days_count = get_month_days_count(year, month)

        employee_query = self.db.query(Employee).filter(Employee.is_active.is_(True))
        if employee_user_id:
            employee_query = employee_query.filter(Employee.user_id == employee_user_id)
        elif employment_type != 'all':
            employee_query = employee_query.filter(Employee.department == employment_type)
        employees = employee_query.order_by(
            Employee.first_name, Employee.last_name, Employee.user_id
        ).all()
        user_ids = {employee.user_id for employee in employees}
        employees_by_id = {employee.user_id: employee for employee in employees}

        holidays_by_date = self._holidays_by_date(start_g, end_g)

        attendances_by_user: Dict[str, Dict[date, List[Attendance]]] = {}
        if user_ids:
            attendances = self.db.query(Attendance).filter(
                and_(
                    Attendance.user_id.in_(user_ids),
                    Attendance.timestamp >= start_g,
                    Attendance.timestamp < end_exclusive,
                    or_(
                        Attendance.is_deleted.is_(False),
                        Attendance.is_deleted.is_(None),
                    ),
                )
            ).order_by(Attendance.timestamp, Attendance.id).all()
            for attendance in attendances:
                attendances_by_user.setdefault(attendance.user_id, {}).setdefault(
                    attendance.timestamp.date(), []
                ).append(attendance)

        statuses_by_user: Dict[str, Dict[date, str]] = {}
        if user_ids:
            daily_statuses = self.db.query(DailyStatus).filter(
                and_(
                    DailyStatus.user_id.in_(user_ids),
                    DailyStatus.status_date >= start_g,
                    DailyStatus.status_date <= end_g,
                )
            ).all()
            for daily_status in daily_statuses:
                code = daily_status.status_code.strip().upper() if isinstance(
                    daily_status.status_code, str
                ) else daily_status.status_code
                statuses_by_user.setdefault(daily_status.user_id, {})[
                    daily_status.status_date
                ] = code

        leaves_by_user: Dict[str, Dict[date, str]] = {}
        hourly_leaves_by_user: Dict[str, Dict[date, List[LeaveRequest]]] = {}
        if user_ids:
            approved_leaves = self.db.query(LeaveRequest).options(
                selectinload(LeaveRequest.travel_leave_detail)
            ).filter(
                and_(
                    LeaveRequest.user_id.in_(user_ids),
                    LeaveRequest.status == 'A',
                    LeaveRequest.from_date <= end_g,
                    LeaveRequest.to_date >= start_g,
                )
            ).all()
            for leave in approved_leaves:
                if leave.leave_type == 'HL':
                    current = leave.from_date
                    while current <= leave.to_date and current <= end_g:
                        if current >= start_g:
                            hourly_leaves_by_user.setdefault(leave.user_id, {}).setdefault(
                                current, []
                            ).append(leave)
                        current += timedelta(days=1)
                    continue

                employee = employees_by_id.get(leave.user_id)
                department = employee.department if employee else None
                applicable_holidays = self._holiday_dates_for_department(
                    department, holidays_by_date
                )
                mapped = build_leave_days_by_date(
                    [leave], applicable_holidays, start_g, end_g
                )
                for mapped_date, mapped_type in mapped.items():
                    leaves_by_user.setdefault(leave.user_id, {})[mapped_date] = mapped_type

        # Phase 6B: bulk-fetch approved HourlyMission for the whole range (no N+1).
        hourly_missions_by_user: Dict[str, Dict[date, List[HourlyMission]]] = {}
        if user_ids:
            approved_missions = self.db.query(HourlyMission).filter(
                and_(
                    HourlyMission.user_id.in_(user_ids),
                    HourlyMission.status == 'A',
                    HourlyMission.mission_date >= start_g,
                    HourlyMission.mission_date <= end_g,
                )
            ).order_by(HourlyMission.start_time).all()
            for mission in approved_missions:
                hourly_missions_by_user.setdefault(mission.user_id, {}).setdefault(
                    mission.mission_date, []
                ).append(mission)

        employee_reports = []
        for employee in employees:
            department = employee.department
            leaves_by_date = leaves_by_user.get(employee.user_id, {})
            hourly_leaves_by_date = hourly_leaves_by_user.get(employee.user_id, {})
            hourly_missions_by_date = hourly_missions_by_user.get(employee.user_id, {})
            days = []
            for offset in range(days_count):
                day = start_g + timedelta(days=offset)
                days.append(self._build_day(
                    day,
                    department,
                    holidays_by_date,
                    statuses_by_user.get(employee.user_id, {}),
                    leaves_by_date,
                    hourly_leaves_by_date,
                    attendances_by_user.get(employee.user_id, {}).get(day, []),
                    hourly_missions_by_date,
                ))
            employee_reports.append({
                'user_id': employee.user_id,
                'full_name': employee.full_name,
                'first_name': employee.first_name or '',
                'last_name': employee.last_name or '',
                'department': department or '',
                'membership': self._membership_name(department),
                'hire_date_j': (
                    jdatetime.date.fromgregorian(date=employee.hire_date).strftime('%Y/%m/%d')
                    if employee.hire_date else None
                ),
                'termination_date_j': (
                    jdatetime.date.fromgregorian(date=employee.termination_date).strftime('%Y/%m/%d')
                    if employee.termination_date else None
                ),
                'days': days,
            })

        if status_filter != 'all':
            filtered = []
            for employee_report in employee_reports:
                days = employee_report['days']
                if status_filter == 'leave':
                    days = [
                        day for day in days
                        if day['person_status'] in LEAVE_PERSON_STATUS
                        or day['leave_type'] is not None
                        or day['person_status'] == 'HL'
                        or (day.get('hourly_leave') and day['hourly_leave'].get('minutes', 0) > 0)
                    ]
                elif status_filter == 'working':
                    days = [day for day in days if day['day_status'] == 'کاری']
                elif status_filter == 'off':
                    days = [day for day in days if day['day_status'] == 'تعطیل']
                else:
                    days = [
                        day for day in days
                        if day['person_status'] == status_filter
                    ]
                if days:
                    employee_report = dict(employee_report)
                    employee_report['days'] = days
                    filtered.append(employee_report)
            employee_reports = filtered

        return {
            'year': year,
            'month': month,
            'month_name': JALALI_MONTHS.get(month, ''),
            'days_count': days_count,
            'mode': 'individual' if employee_user_id else 'group',
            'employee_user_id': employee_user_id,
            'employment_type': employment_type,
            'status_filter': status_filter,
            'employees': employee_reports,
        }


def build_raw_report(
    db: Session,
    year: int,
    month: int,
    employee_user_id: Optional[str] = None,
    employment_type: str = 'all',
    status_filter: str = 'all',
) -> dict:
    return RawReportService(db).build_report(
        year,
        month,
        employee_user_id=employee_user_id,
        employment_type=employment_type,
        status_filter=status_filter,
    )
