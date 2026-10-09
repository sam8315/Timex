"""
ماژول گزارش تفصیلی ماهانه کارمند - نسخه ۲
با ستون‌های متعدد ورود/خروج و مبنای محاسبه بر اساس سیاست گروه

Phase 5: محاسبه «تردد واقعی» (Actual Attendance) از Central Attendance Engine
(`core/attendance_calculator.compute_day_attendance`) انجام می‌شود؛
این ماژول فقط لایه Report است:

    Central Engine  → Actual Work / pairs / وضعیت تردد
    Policy Engine   → Required Duty / موظفی روز
    Report Layer    → surplus / deficit / weekly overtime / monthly summary
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.employee import Employee
from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.leave_request import LeaveRequest
from models.holiday import Holiday
from core.time_calculator import sum_shift_hours_from_pairs
from core.attendance_calculator import (
    STATUS_NIGHT_SHIFT,
    STATUS_NO_ATTENDANCE,
    compute_day_attendance,
)
from web.services.attendance_policy_service import (
    resolve_policy,
    resolve_policy_day,
    compute_effective_required_minutes_for_day,
    compute_late_early_for_day,
    grace_credit_minutes,
    effective_work_hours,
)
from web.services.hourly_leave_service import (
    get_approved_hl_minutes,
    get_approved_hl_intervals,
    format_hl_display,
)
from web.services.hourly_mission_service import (
    get_approved_hourly_mission_minutes,
    get_approved_hourly_missions_for_display,
    format_hm_display,
)


def _hours_to_minutes(hours: float) -> int:
    """تبدیل ساعت اعشاری به دقیقهٔ صحیح (مبنای نمایش H:MM)."""
    return int(round(float(hours or 0) * 60))


def _minutes_to_hours(minutes: int) -> float:
    """دقیقه → ساعت اعشاری طوری که round(h*60) همان دقیقه را برگرداند."""
    return minutes / 60.0


def punch_grace_totals(days: List[Dict]) -> Dict:
    """جمع کارکرد واقعی، فرجه و جمع آن دو برای کارت خلاصه."""
    punch_m = 0
    grace_m = 0
    for day in days:
        if 'punch_hours' in day:
            punch_m += _hours_to_minutes(day.get('punch_hours') or 0)
        else:
            punch_m += _hours_to_minutes(day.get('work_hours') or 0)
        grace_m += int(day.get('grace_credit_minutes') or 0)
    return {
        'total_punch_hours': _minutes_to_hours(punch_m),
        'total_grace_hours': _minutes_to_hours(grace_m),
        'total_punch_grace_hours': _minutes_to_hours(punch_m + grace_m),
    }


# موظفی پیش‌فرض وقتی Policy نباشد: ۷:۲۰ = ۴۴۰ دقیقه (نه ۷.۳۳ شناور)
_DEFAULT_DUTY_MINUTES = 440

# نام فارسی نوع عضویت (فیلد Employee.department)
EMPLOYMENT_TYPE_LABELS = {
    '1': 'رسمی',
    '2': 'وظیفه',
    '3': 'خریدخدمت',
    '4': 'قراردادی',
    '5': 'پزشکی',
    '6': 'سایر / متفرقه',
    '7': 'قرارداد با بیمه‌ها',
}


def employment_type_label(code) -> str:
    """کد عضویت → نام فارسی؛ اگر ناشناخته باشد همان کد برمی‌گردد."""
    if code is None or code == '':
        return '-'
    key = str(code)
    return EMPLOYMENT_TYPE_LABELS.get(key, key)


class DetailedMonthlyReportGeneratorV2:
    """تولید گزارش تفصیلی ماهانه - نسخه ۲"""

    # حداکثر تعداد جفت ورود/خروج
    MAX_PAIRS = 3

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def get_employees_by_department(self, department: str = '4') -> List[Employee]:
        """دریافت کارمندان فعال یک دپارتمان"""
        return self.db.query(Employee).filter(
            and_(
                Employee.is_active == True,
                Employee.department == department
            )
        ).order_by(Employee.hire_date, Employee.last_name, Employee.first_name).all()

    def generate_detailed_report(
        self,
        user_id: str,
        year: int,
        month: int
    ) -> Dict:
        """تولید گزارش تفصیلی ماهانه برای یک کارمند - نسخه ۲"""
        # محاسبه بازه ماه
        j_month_start = jdatetime.date(year, month, 1)
        if month == 12:
            try:
                j_month_end = jdatetime.date(year, 12, 30)
            except ValueError:
                j_month_end = jdatetime.date(year, 12, 29)
        else:
            j_month_end = jdatetime.date(year, month + 1, 1) - timedelta(days=1)

        g_start = j_month_start.togregorian()
        g_end = j_month_end.togregorian()

        # دریافت اطلاعات کارمند
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            return {'success': False, 'message': 'کارمند یافت نشد'}

        # دریافت رکوردهای تردد — با حاشیه مرز ماه (Phase 5)
        # روزهای حاشیه (‎-1 / +2 روز) صرفاً context موتور مرکزی برای تشخیص
        # شیفت شبِ عبور از مرز ماه هستند؛ فقط روزهای داخل ماه در گزارش و
        # summary لحاظ می‌شوند (در حلقه ساخت `days` فقط ماه فیلتر می‌شود).
        attendances = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= g_start - timedelta(days=1),
                func.date(Attendance.timestamp) <= g_end + timedelta(days=2),
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).all()

        # گروه‌بندی بر اساس روز
        attendances_by_day = {}
        for att in attendances:
            day = att.timestamp.date()
            if day not in attendances_by_day:
                attendances_by_day[day] = []
            attendances_by_day[day].append(att)

        # دریافت وضعیت‌های روزانه
        daily_statuses = self.db.query(DailyStatus).filter(
            and_(
                DailyStatus.user_id == user_id,
                DailyStatus.status_date >= g_start,
                DailyStatus.status_date <= g_end
            )
        ).all()

        statuses_by_date = {ds.status_date: ds.status_code for ds in daily_statuses}

        # ✅ دریافت درخواست‌های مرخصی تایید شده (فقط مرخصی‌های روزانه، HL جداگانه پردازش می‌شود)
        approved_leaves = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status == 'A',  # تایید شده
                LeaveRequest.leave_type != 'HL',  # ✅ HL در leaves_by_date نباشد
                LeaveRequest.from_date <= g_end,
                LeaveRequest.to_date >= g_start
            )
        ).all()

        # ✅ ساخت دیکشنری مرخصی‌ها بر اساس تاریخ (فقط full-day leaves)
        leaves_by_date = {}
        for leave in approved_leaves:
            current = leave.from_date
            while current <= leave.to_date:
                if current >= g_start and current <= g_end:
                    leaves_by_date[current] = leave.leave_type
                current += timedelta(days=1)

        # Phase 7: Fetch approved HL minutes for day-level duty adjustment
        hl_minutes_by_date = get_approved_hl_minutes(
            db=self.db, employee=employee,
            start_date=g_start, end_date=g_end
        )
        # بازه‌های HL برای کسر همپوشانی از تأخیر/تعجیل
        hl_intervals_by_date = get_approved_hl_intervals(
            db=self.db, employee=employee,
            start_date=g_start, end_date=g_end
        )

        # Phase 6A: Approved HM missions for display only (no duty change here)
        hm_by_date = get_approved_hourly_missions_for_display(
            db=self.db, employee=employee,
            start_date=g_start, end_date=g_end
        )

        # Phase 6C: Approved HM minutes for Effective Required (policy aware:
        # only status='A'; deduct_from_required_minutes=False → 0)
        hm_minutes_by_date = get_approved_hourly_mission_minutes(
            db=self.db, employee=employee,
            start_date=g_start, end_date=g_end
        )

        # ✅ ترکیب وضعیت‌ها: DailyStatus اولویت بالاتر دارد
        for leave_date, leave_type in leaves_by_date.items():
            if leave_date not in statuses_by_date:
                statuses_by_date[leave_date] = leave_type

        # ساخت لیست روزها
        days = []
        current = g_start
        while current <= g_end:
            j_date = jdatetime.date.fromgregorian(date=current)
            day_name = self._get_day_name(current)

            # تعیین وضعیت روز
            is_friday = current.weekday() == 4
            holiday = self._find_holiday(current, employee.department)
            is_holiday = holiday is not None
            holiday_title = holiday.title if holiday is not None else None

            # Phase 6C: سیاست گروه برای روز — روز غیرکاری Policy هم «تعطیل» است
            # (همان semantics resolve_required_minutes → Non-working = 0)
            resolved = resolve_policy(self.db, employee, current)
            policy_day = resolve_policy_day(resolved, current)
            is_day_off = is_friday or is_holiday or (
                policy_day is not None and not policy_day.is_working_day
            )

            # تعیین وضعیت فرد
            person_status = self._determine_person_status(
                current, statuses_by_date, attendances_by_day, is_day_off
            )

            # Actual Attendance فقط از Central Engine (Phase 5) —
            # با context روز قبل/بعد (روزهای حاشیه ماه هم fetch شده‌اند)
            day_data = self._compute_day_actual(
                current,
                attendances_by_day.get(current, []),
                attendances_by_day.get(current - timedelta(days=1), []),
                attendances_by_day.get(current + timedelta(days=1), []),
                is_friday=is_friday,
                holiday_title=holiday_title,
            )

            work_hours = day_data['work_hours']
            attendance_pairs = day_data['pairs']
            attendance_status = day_data['attendance_status']
            has_incomplete = day_data['has_incomplete']

            # Phase 7: approved HL minutes (display + duty)
            hl_mins = hl_minutes_by_date.get(current, 0)
            # Phase 6C: approved HM minutes (duty only — نمایش از hm_by_date)
            hm_mins = hm_minutes_by_date.get(current, 0)

            # Phase 6C: Effective Required — همان تابع مرکزی
            # (Base → روز کامل → HL → HM → clamp)؛ DailyStatus 'M' و 'R'
            # و مرخصی کامل از person_status استخراج می‌شوند.
            required_minutes = compute_effective_required_minutes_for_day(
                resolved=resolved,
                target_date=current,
                is_holiday=is_holiday,
                is_leave=person_status['code'] == 'L',
                is_mission=person_status['code'] == 'M',
                is_rest=person_status['code'] == 'R',
                is_friday=is_friday,
                hourly_leave_minutes=hl_mins,
                hourly_mission_minutes=hm_mins,
            )
            daily_required_hours = _minutes_to_hours(int(required_minutes))

            # تأخیر / تعجیل از سیاست (Grace کامل؛ در مرخصی/استراحت صفر؛
            # همپوشانی HL از پنجرهٔ تأخیر/تعجیل کم می‌شود)
            late_early = compute_late_early_for_day(
                resolved=resolved,
                target_date=current,
                first_enter=day_data.get('first_enter'),
                last_exit=day_data.get('last_exit'),
                skip=person_status['code'] in ('L', 'R'),
                hl_intervals=hl_intervals_by_date.get(current),
            )

            # کارکرد خام و اعتبار فرجه در همان رکورد روز؛
            # سوئیچ سیاست فقط کارکرد مؤثر گزارش را عوض می‌کند.
            punch_hours = float(work_hours)
            grace_m = grace_credit_minutes(late_early)
            include_grace = bool(
                resolved and resolved.policy
                and getattr(resolved.policy, 'include_grace_in_work', False)
            )
            work_hours = effective_work_hours(punch_hours, grace_m, include_grace)

            # محاسبه اضافی/کسری بر اساس موظفی روز + تخلف تأخیر/تعجیل
            surplus, deficit = self._calculate_surplus_deficit(
                work_hours,
                is_day_off,
                person_status,
                daily_required_hours,
                late_violation_minutes=late_early['late_violation_minutes'],
                early_leave_violation_minutes=late_early['early_leave_violation_minutes'],
            )

            # تفکیک صبح/عصر/شب روی *همه* جفت‌های موتور (نه first→last و
            # نه فقط pairهای سقف‌خورده‌ی نمایشی). فاصله بین جفت‌ها کار نیست.
            shift_hours = day_data.get('shift_hours') or {
                'morning': 0.0, 'evening': 0.0, 'night': 0.0,
            }

            # تعیین موظفی روز
            has_duty = daily_required_hours > 0
            daily_duty = daily_required_hours

            days.append({
                'date': current,
                'jalali_date': j_date.strftime('%Y/%m/%d'),
                'day_name': day_name,
                'is_friday': is_friday,
                'is_holiday': is_holiday,
                'is_day_off': is_day_off,
                'day_status': 'تعطیل' if is_day_off else 'کاری',
                'person_status': person_status['code'],
                'person_status_name': person_status['name'],
                'attendance_pairs': attendance_pairs,
                'attendance_status': attendance_status,
                'has_incomplete': has_incomplete,
                'punch_hours': punch_hours,
                'grace_credit_minutes': grace_m,
                'work_hours': float(work_hours),
                'surplus': surplus,
                'deficit': deficit,
                'morning_hours': shift_hours['morning'],
                'evening_hours': shift_hours['evening'],
                'night_hours': shift_hours['night'],
                'has_duty': has_duty,
                'daily_duty': daily_duty,
                # 🕐 HL تأییدشده برای نمایش (از Effective Required کم شده)
                'hourly_leave_minutes': hl_mins,
                'hourly_leave_display': format_hl_display(hl_mins),
                # 🚗 HM تأییدشده برای نمایش (از Effective Required کم شده —
                # نمایش همیشگی است، حتی اگر policy کسر خاموش باشد)
                'hourly_mission_minutes': hm_mins,
                'hourly_mission_display': format_hm_display(hm_by_date.get(current)),
                # تأخیر / تعجیل
                'late_minutes': late_early['late_minutes'],
                'late_violation_minutes': late_early['late_violation_minutes'],
                'late_allowed_minutes': late_early['late_allowed_minutes'],
                'is_late': late_early['is_late'],
                'early_leave_minutes': late_early['early_leave_minutes'],
                'early_leave_violation_minutes': late_early['early_leave_violation_minutes'],
                'early_leave_allowed_minutes': late_early['early_leave_allowed_minutes'],
                'is_early_leave': late_early['is_early_leave'],
            })

            current += timedelta(days=1)

        # محاسبه خلاصه ماهانه
        summary = self._calculate_monthly_summary(days)

        return {
            'success': True,
            'employee': {
                'user_id': employee.user_id,
                'full_name': employee.full_name,
                'department': employee.department,
                'department_name': employment_type_label(employee.department),
            },
            'year': year,
            'month': month,
            'month_name': self._get_jalali_month_name(month),
            'days': days,
            'summary': summary
        }

    def _determine_person_status(
        self,
        current: date,
        statuses_by_date: Dict,
        attendances_by_day: Dict,
        is_day_off: bool
    ) -> Dict:
        """تعیین وضعیت فرد در یک روز

        مرخصی روی جمعه / تعطیل رسمی / روز غیرکاری Policy به‌عنوان «تعطیل»
        ثبت می‌شود (نه مرخصی) تا در کارت خلاصه فقط روزهای کاری مرخصی شمرده شوند.
        هم‌تراز با ویو حضور که روی جمعه/تعطیل badge مرخصی نمی‌گذارد.
        """
        if current in statuses_by_date:
            status_code = statuses_by_date[current]
            # ✅ بررسی انواع مرخصی (همه leave-type های canonical: AL/SL/RL/UL/CW/TL)
            if status_code in ['AL', 'SL', 'RL', 'UL', 'CW', 'TL', 'L']:
                if is_day_off:
                    return {'code': 'H', 'name': 'تعطیل'}
                return {'code': 'L', 'name': 'مرخصی'}
            # ✅ مأموریت روزانه (DailyStatus 'M') — موظفی روز صفر است
            elif status_code == 'M':
                return {'code': 'M', 'name': 'مأموریت'}
            elif status_code == 'R':
                return {'code': 'R', 'name': 'استراحت'}
            elif status_code == 'A':
                return {'code': 'A', 'name': 'غایب'}
            elif status_code == 'P':
                if is_day_off:
                    return {'code': 'P', 'name': 'حاضر (تعطیل کاری)'}
                return {'code': 'P', 'name': 'حاضر'}

        if current in attendances_by_day:
            if is_day_off:
                return {'code': 'P', 'name': 'حاضر (تعطیل کاری)'}
            return {'code': 'P', 'name': 'حاضر'}

        # اگر روز تعطیل است و تردد ندارد → تعطیل
        if is_day_off:
            return {'code': 'H', 'name': 'تعطیل'}

        return {'code': 'A', 'name': 'غایب'}

    def _compute_day_actual(
        self,
        current: date,
        day_records: List,
        prev_day_records: List,
        next_day_records: List,
        is_friday: bool,
        holiday_title: Optional[str],
    ) -> Dict:
        """
        Actual Attendance یک روز - فقط از Central Attendance Engine.

        خروجی موتور (status / night shift / pairs / work_hours) اینجا به
        ساختار فعلی گزارش تبدیل می‌شود تا template بدون تغییر کار کند:
            - work_hours: مقدار خام موتور (بدون round داخلی)
            - pairs: همان pairهای موتور؛ نمایش حداکثر MAX_PAIRS جفت
            - attendance_status: label نمایشی فعلی monthly-full
        """
        result = compute_day_attendance(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title,
        )

        # موتور برای محاسبه، زمان‌ها را naive نگه می‌دارد؛ ساختار قدیمیِ گزارش
        # pairها را با همان timezone رکوردهای تردد می‌دهد (فقط نمایش/سازگاری)
        tzinfo = None
        for rec in day_records:
            if rec.timestamp.tzinfo is not None:
                tzinfo = rec.timestamp.tzinfo
                break

        def _with_tz(value):
            if value is not None and tzinfo is not None and value.tzinfo is None:
                return value.replace(tzinfo=tzinfo)
            return value

        pairs = [
            {'enter': _with_tz(pair['enter']),
             'exit': _with_tz(pair['exit']),
             'hours': pair['hours']}
            for pair in result.pairs
        ]
        attendance_status, has_incomplete = self._display_status(result)
        # تفکیک شیفت از همه جفت‌ها؛ سقف نمایشی فقط روی attendance_pairs است
        shift_hours = sum_shift_hours_from_pairs(pairs)

        return {
            # مقدار خام موتور (بدون round داخلی)؛ float برای سازگاری نوع با خروجی قدیمی
            'work_hours': float(result.work_hours),
            'pairs': pairs[:self.MAX_PAIRS],
            'shift_hours': shift_hours,
            'first_enter': _with_tz(result.first_enter),
            'last_exit': _with_tz(result.last_exit),
            'attendance_status': attendance_status,
            'has_incomplete': has_incomplete,
        }

    @staticmethod
    def _display_status(result) -> tuple:
        """
        نگاشت وضعیت فنی Central Engine به labelهای نمایشی فعلی گزارش.
        (لایه نمایش - متن‌های UI به خاطر migration عوض نمی‌شوند.)
        """
        enters = result.enter_count
        exits = result.exit_count

        if result.main_status == STATUS_NO_ATTENDANCE or (enters == 0 and exits == 0):
            return 'بدون تردد', False

        if result.main_status == STATUS_NIGHT_SHIFT:
            if exits == 0:
                return 'کامل (خروج فردا)', False
            if enters == 0:
                return 'کامل (ورود دیروز)', False
            # خروجِ صبحِ قبل از ورودِ شب در همان روز
            if enters == exits:
                return ('کامل' if enters == 1 else f'کامل{enters}'), False
            return f'ناقص ({enters}و/{exits}خ)', True

        if exits == 0:
            return f'ورود بدون خروج ({enters} ورود)', True
        if enters == 0:
            return f'خروج بدون ورود ({exits} خروج)', True
        if enters == exits:
            return ('کامل' if enters == 1 else f'کامل{enters}'), False
        return f'ناقص ({enters}و/{exits}خ)', True

    def _calculate_surplus_deficit(
        self,
        work_hours: float,
        is_day_off: bool,
        person_status: Dict,
        daily_required_hours: float = None,
        late_violation_minutes: int = 0,
        early_leave_violation_minutes: int = 0,
    ) -> tuple:
        """
        محاسبه اضافی و کسری بر اساس موظفی روز (Policy) با دقت دقیقه.

        daily_required_hours: ساعات موظفی روز از Policy؛ اگر نباشد ۷:۲۰ (۴۴۰ دقیقه).
        کسری نهایی = کسری کارکرد + تخلف تأخیر + تخلف تعجیل (بعد از Grace).
        """
        if daily_required_hours is None:
            daily_required_hours = _minutes_to_hours(_DEFAULT_DUTY_MINUTES)

        work_m = _hours_to_minutes(work_hours)
        duty_m = _hours_to_minutes(daily_required_hours)
        violation_m = max(0, int(late_violation_minutes or 0)) + max(
            0, int(early_leave_violation_minutes or 0)
        )

        if is_day_off and person_status['code'] == 'H':
            return 0.0, _minutes_to_hours(violation_m) if violation_m else 0.0

        if is_day_off and person_status['code'] == 'P':
            return _minutes_to_hours(work_m), _minutes_to_hours(violation_m)

        if person_status['code'] in ['L', 'R']:
            if work_m > 0:
                return _minutes_to_hours(work_m), _minutes_to_hours(violation_m)
            return 0.0, _minutes_to_hours(violation_m)

        if work_m > duty_m:
            return _minutes_to_hours(work_m - duty_m), _minutes_to_hours(violation_m)
        if 0 < work_m < duty_m:
            return 0.0, _minutes_to_hours((duty_m - work_m) + violation_m)
        if work_m == 0:
            return 0.0, _minutes_to_hours(duty_m + violation_m)

        # work_m == duty_m
        return 0.0, _minutes_to_hours(violation_m)

    def _calculate_monthly_summary(self, days: List[Dict]) -> Dict:
        """محاسبه خلاصه ماهانه (جمع‌ها با دقت دقیقه)."""
        present_days = sum(
            1 for d in days
            if d['person_status'] == 'P' and not d['is_friday'] and not d['is_holiday']
        )

        friday_work_days = sum(1 for d in days if d['is_friday'] and d['person_status'] == 'P')
        holiday_work_days = sum(
            1 for d in days if d['is_holiday'] and not d['is_friday'] and d['person_status'] == 'P'
        )

        leave_days = sum(1 for d in days if d['person_status'] == 'L')
        absent_days = sum(1 for d in days if d['person_status'] == 'A')
        rest_days = sum(1 for d in days if d['person_status'] == 'R')
        holiday_days = sum(1 for d in days if d['person_status'] == 'H')
        mission_days = sum(1 for d in days if d['person_status'] == 'M')

        duty_days = sum(1 for d in days if d['has_duty'])

        def _sum_hours(key: str) -> float:
            # جمع اعشاری روزها، سپس یک‌بار به دقیقه گرد می‌شود تا نمایش H:MM پایدار بماند
            return _minutes_to_hours(
                _hours_to_minutes(sum(float(d[key] or 0) for d in days))
            )

        total_duty_hours = _sum_hours('daily_duty')
        total_work_hours = _sum_hours('work_hours')
        grace_totals = punch_grace_totals(days)
        total_morning = _sum_hours('morning_hours')
        total_evening = _sum_hours('evening_hours')
        total_night = _sum_hours('night_hours')
        # اضافی/کسری از قبل دقیقه‌ای‌اند → جمع دقیقه‌ای
        total_surplus = _minutes_to_hours(
            sum(_hours_to_minutes(d['surplus']) for d in days))
        total_deficit = _minutes_to_hours(
            sum(_hours_to_minutes(d['deficit']) for d in days))
        total_late_violation_m = sum(
            int(d.get('late_violation_minutes') or 0) for d in days
        )
        total_early_leave_violation_m = sum(
            int(d.get('early_leave_violation_minutes') or 0) for d in days
        )
        total_late_violation = _minutes_to_hours(total_late_violation_m)
        total_early_leave_violation = _minutes_to_hours(total_early_leave_violation_m)

        net_balance_m = _hours_to_minutes(total_surplus) - _hours_to_minutes(total_deficit)
        net_balance = _minutes_to_hours(net_balance_m)

        if net_balance_m > 0:
            overall_status = 'اضافی'
            net_balance_hours = net_balance
        elif net_balance_m < 0:
            overall_status = 'کسری'
            net_balance_hours = abs(net_balance)
        else:
            overall_status = 'متعادل'
            net_balance_hours = 0.0

        weekly_overtime = self._calculate_weekly_overtime(days)

        friday_work_hours = _minutes_to_hours(sum(
            _hours_to_minutes(d['work_hours'])
            for d in days if d['is_friday'] and d['person_status'] == 'P'
        ))
        holiday_work_hours = _minutes_to_hours(sum(
            _hours_to_minutes(d['work_hours'])
            for d in days
            if d['is_holiday'] and not d['is_friday'] and d['person_status'] == 'P'
        ))

        return {
            'duty_days': duty_days,
            'duty_hours': total_duty_hours,
            'present_days': present_days,
            'leave_days': leave_days,
            'absent_days': absent_days,
            'rest_days': rest_days,
            'holiday_days': holiday_days,
            'mission_days': mission_days,
            'friday_work_days': friday_work_days,
            'holiday_work_days': holiday_work_days,
            'total_work_hours': total_work_hours,
            'total_punch_hours': grace_totals['total_punch_hours'],
            'total_grace_hours': grace_totals['total_grace_hours'],
            'total_punch_grace_hours': grace_totals['total_punch_grace_hours'],
            'grace_included_in_work': _hours_to_minutes(total_work_hours) == (
                _hours_to_minutes(grace_totals['total_punch_hours'])
                + _hours_to_minutes(grace_totals['total_grace_hours'])
            ),
            'total_morning': total_morning,
            'total_evening': total_evening,
            'total_night': total_night,
            'total_surplus': total_surplus,
            'total_deficit': total_deficit,
            'total_late_violation': total_late_violation,
            'total_early_leave_violation': total_early_leave_violation,
            'total_late_violation_minutes': total_late_violation_m,
            'total_early_leave_violation_minutes': total_early_leave_violation_m,
            'net_balance': net_balance,
            'overall_status': overall_status,
            'net_balance_hours': net_balance_hours,
            'weekly_overtime': weekly_overtime,
            'friday_work_hours': friday_work_hours,
            'holiday_work_hours': holiday_work_hours,
        }

    def _calculate_weekly_overtime(self, days: List[Dict]) -> float:
        """محاسبه اضافه کار هفتگی با دقت دقیقه (بر اساس Policy هر روز)."""
        weekly_overtime_m = 0

        weeks = {}
        for day in days:
            current = day['date']
            while current.weekday() != 5:
                current -= timedelta(days=1)

            week_start = current
            if week_start not in weeks:
                weeks[week_start] = []
            weeks[week_start].append(day)

        for week_start, week_days in weeks.items():
            total_m = sum(_hours_to_minutes(d['work_hours']) for d in week_days)
            required_m = sum(_hours_to_minutes(d['daily_duty']) for d in week_days)

            if required_m > 0 and total_m > required_m:
                weekly_overtime_m += total_m - required_m

        return _minutes_to_hours(weekly_overtime_m)

    def _find_holiday(self, target_date: date, department: str) -> Optional[Holiday]:
        """رکورد تعطیلِ مؤثر برای تاریخ/گروه (برای عنوان و پرچم تعطیلی)"""
        holidays = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).all()

        for holiday in holidays:
            if holiday.group_id is None:
                return holiday
            elif holiday.group_id == department:
                return holiday

        return None

    def _is_holiday(self, target_date: date, department: str) -> bool:
        """بررسی تعطیل بودن"""
        return self._find_holiday(target_date, department) is not None

    def _get_day_name(self, d: date) -> str:
        """دریافت نام روز هفته"""
        names = {
            0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
            3: 'پنجشنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه'
        }
        return names.get(d.weekday(), '')

    def _get_jalali_month_name(self, month: int) -> str:
        """دریافت نام ماه شمسی"""
        names = {
            1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
            4: 'تیر', 5: 'مرداد', 6: 'شهریور',
            7: 'مهر', 8: 'آبان', 9: 'آذر',
            10: 'دی', 11: 'بهمن', 12: 'اسفند'
        }
        return names.get(month, '')