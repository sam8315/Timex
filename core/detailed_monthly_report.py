"""
ماژول گزارش تفصیلی ماهانه کارمند
"""
from datetime import date, timedelta, datetime
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


class DetailedMonthlyReportGenerator:
    """تولید گزارش تفصیلی ماهانه"""

    # ساعات موظفی روزانه (گروه قراردادی)
    # 🆕 Phase 5: این مقدار باید از Attendance Policy Service خوانده شود
    # فعلاً برای سازگاری با داده‌های قبلی نگه داشته شده
    DAILY_REQUIRED_HOURS = 7.33  # 7:20

    # ساعات موظفی هفتگی
    WEEKLY_REQUIRED_HOURS = 44.0

    # ساعات کاری روزانه برای محاسبه اضافه کاری
    DAILY_OVERTIME_THRESHOLD = 8.0

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
                Employee.membership_type_code == department
            )
        ).order_by(Employee.last_name, Employee.first_name).all()

    def generate_detailed_report(
        self,
        user_id: str,
        year: int,
        month: int
    ) -> Dict:
        """تولید گزارش تفصیلی ماهانه برای یک کارمند"""
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

        # دریافت رکوردهای تردد ماه + حاشیه روز قبل/بعد (برای context شیفت شب)
        # روزهای خارج از ماه فقط context هستند و وارد لیست روزها/خلاصه نمی‌شوند.
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

        # ساخت لیست روزها
        days = []
        current = g_start
        day_index = 0
        while current <= g_end:
            j_date = jdatetime.date.fromgregorian(date=current)
            day_name = self._get_day_name(current)

            # تعیین وضعیت روز
            is_friday = current.weekday() == 4
            from web.services.membership_resolve import membership_code_for
            is_holiday = self._is_holiday(current, membership_code_for(self.db, employee, current))
            is_day_off = is_friday or is_holiday

            # تعیین وضعیت فرد
            person_status = self._determine_person_status(
                current, statuses_by_date, attendances_by_day, is_day_off
            )

            # Actual Attendance فقط از Central Engine (Phase 7)
            day_data = self._compute_day_actual(
                current,
                attendances_by_day.get(current, []),
                attendances_by_day.get(current - timedelta(days=1), []),
                attendances_by_day.get(current + timedelta(days=1), []),
                is_friday=is_friday,
            )

            work_hours = day_data['work_hours']
            first_enter = day_data['first_enter']
            last_exit = day_data['last_exit']
            attendance_status = day_data['attendance_status']
            has_incomplete = day_data['has_incomplete']

            # محاسبه اضافه کار روزانه
            overtime = self._calculate_daily_overtime(
                work_hours, is_day_off, person_status
            )

            # محاسبه ساعات تفکیکی روی همه جفت‌ها (نه first→last)
            shift_hours = day_data.get('shift_hours') or {
                'morning': 0.0, 'evening': 0.0, 'night': 0.0,
            }

            # تعیین موظفی روز
            has_duty = self._has_duty(is_day_off, person_status)
            daily_duty = self.DAILY_REQUIRED_HOURS if has_duty else 0.0

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
                'first_enter': first_enter,
                'last_exit': last_exit,
                'attendance_status': attendance_status,
                'has_incomplete': has_incomplete,
                'work_hours': work_hours,
                'overtime': overtime,
                'morning_hours': shift_hours['morning'],
                'evening_hours': shift_hours['evening'],
                'night_hours': shift_hours['night'],
                'has_duty': has_duty,
                'daily_duty': daily_duty
            })

            current += timedelta(days=1)
            day_index += 1

        # محاسبه خلاصه ماهانه
        summary = self._calculate_monthly_summary(days)

        return {
            'success': True,
            'employee': {
                'user_id': employee.user_id,
                'full_name': employee.full_name,
                'department': employee.membership_type_code or ''
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
        """تعیین وضعیت فرد در یک روز"""
        if current in statuses_by_date:
            status_code = statuses_by_date[current]
            if status_code in ['AL', 'SL', 'RL', 'UL']:
                return {'code': 'L', 'name': 'مرخصی'}
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

        return {'code': 'A', 'name': 'غایب'}

    def _compute_day_actual(
        self,
        current: date,
        day_records: List,
        prev_day_records: List,
        next_day_records: List,
        is_friday: bool,
        holiday_title: Optional[str] = None,
    ) -> Dict:
        """
        Actual Attendance یک روز - فقط از Central Attendance Engine.

        خروجی موتور (status / night shift / work hours / first enter / last exit)
        در اینجا به ساختار فعلی گزارش تبدیل می‌شود تا رفتار قبلی حفظ شود:
            - work_hours: مقدار خام موتور؛ گرد کردن در لایه گزارش (نمایش)
            - attendance_status: همان labelهای نمایشی قبلی این گزارش
        """
        result = compute_day_attendance(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title,
        )

        # موتور زمان‌ها را naive نگه می‌دارد؛ گزارش قبلی tz رکوردها را برمی‌گرداند
        tzinfo = None
        for rec in day_records:
            if rec.timestamp.tzinfo is not None:
                tzinfo = rec.timestamp.tzinfo
                break

        def _with_tz(value):
            if value is not None and tzinfo is not None and value.tzinfo is None:
                return value.replace(tzinfo=tzinfo)
            return value

        attendance_status, has_incomplete = self._display_status(result)
        pairs = [
            {'enter': _with_tz(pair['enter']),
             'exit': _with_tz(pair['exit']),
             'hours': pair['hours']}
            for pair in result.pairs
        ]

        return {
            'work_hours': round(float(result.work_hours), 2),
            'first_enter': _with_tz(result.first_enter),
            'last_exit': _with_tz(result.last_exit),
            'attendance_status': attendance_status,
            'has_incomplete': has_incomplete,
            'shift_hours': sum_shift_hours_from_pairs(pairs),
        }

    @staticmethod
    def _display_status(result) -> tuple:
        """
        نگاشت وضعیت فنی Central Engine به labelهای نمایشی قبلی این گزارش
        (لایه نمایش - متن‌های گزارش به خاطر migration عوض نمی‌شوند).
        """
        enters = result.enter_count
        exits = result.exit_count

        if result.main_status == STATUS_NO_ATTENDANCE or (enters == 0 and exits == 0):
            return 'بدون تردد', False

        if result.main_status == STATUS_NIGHT_SHIFT:
            if exits == 0:
                return 'کامل(خروج سیستمی)', False
            if enters == 0:
                return 'کامل(ورود سیستمی)', False
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

    def _calculate_daily_overtime(
        self,
        work_hours: float,
        is_day_off: bool,
        person_status: Dict
    ) -> float:
        """محاسبه اضافه کار روزانه"""
        if work_hours == 0:
            return 0.0

        # اگر روز تعطیل/جمعه/استراحت/مرخصی باشد و حضور داشته باشد
        # کل کارکرد = اضافه کار
        if is_day_off and person_status['code'] == 'P':
            return work_hours

        if person_status['code'] in ['L', 'R'] and work_hours > 0:
            return work_hours

        # روز کاری عادی
        if work_hours > self.DAILY_OVERTIME_THRESHOLD:
            return round(work_hours - self.DAILY_OVERTIME_THRESHOLD, 2)

        return 0.0

    def _has_duty(self, is_day_off: bool, person_status: Dict) -> bool:
        """تعیین اینکه آیا روز موظفی دارد"""
        if is_day_off:
            return False
        if person_status['code'] in ['L', 'R']:  # مرخصی یا استراحت
            return False
        if person_status['code'] == 'A':  # غیبت
            return True
        return True

    def _calculate_monthly_summary(self, days: List[Dict]) -> Dict:
        """محاسبه خلاصه ماهانه"""
        # شمارش روزها
        present_days = sum(1 for d in days if d['person_status'] == 'P' and not d['is_day_off'])
        leave_days = sum(1 for d in days if d['person_status'] == 'L')
        absent_days = sum(1 for d in days if d['person_status'] == 'A')
        rest_days = sum(1 for d in days if d['person_status'] == 'R')
        friday_work_days = sum(1 for d in days if d['is_friday'] and d['person_status'] == 'P')

        # محاسبه موظفی
        duty_days = sum(1 for d in days if d['has_duty'])
        total_duty_hours = sum(d['daily_duty'] for d in days)

        # محاسبه کارکرد
        total_work_hours = sum(d['work_hours'] for d in days)
        total_morning = sum(d['morning_hours'] for d in days)
        total_evening = sum(d['evening_hours'] for d in days)
        total_night = sum(d['night_hours'] for d in days)

        # محاسبه اضافه کار روزانه
        daily_overtime = sum(d['overtime'] for d in days)

        # محاسبه اضافه کار هفتگی (با کم کردن اضافه کار روزانه)
        weekly_overtime = self._calculate_weekly_overtime(days, daily_overtime)

        # جمعه کاری (فقط برای نمایش، نه برای محاسبه اضافی)
        friday_work_hours = sum(d['work_hours'] for d in days if d['is_friday'] and d['person_status'] == 'P')

        # ✅ اصلاح: کسری و اضافی (بدون تهاتر)
        # اضافی = اضافه کار روزانه + اضافه کار هفتگی
        # (جمعه کاری در دل اضافه کار روزانه است)
        deficit = max(0, total_duty_hours - total_work_hours)
        surplus = daily_overtime + weekly_overtime  # ✅ اصلاح شد

        return {
            'duty_days': duty_days,
            'duty_hours': round(total_duty_hours, 2),
            'present_days': present_days,
            'leave_days': leave_days,
            'absent_days': absent_days,
            'rest_days': rest_days,
            'friday_work_days': friday_work_days,
            'total_work_hours': round(total_work_hours, 2),
            'total_morning': round(total_morning, 2),
            'total_evening': round(total_evening, 2),
            'total_night': round(total_night, 2),
            'daily_overtime': round(daily_overtime, 2),
            'weekly_overtime': round(weekly_overtime, 2),
            'friday_work_hours': round(friday_work_hours, 2),
            'deficit': round(deficit, 2),
            'surplus': round(surplus, 2)
        }

    def _calculate_weekly_overtime(self, days: List[Dict], total_daily_overtime: float) -> float:
        """محاسبه اضافه کار هفتگی (با کم کردن اضافه کار روزانه)"""
        weekly_overtime = 0.0

        # گروه‌بندی روزها بر اساس هفته (شنبه تا جمعه)
        weeks = {}
        for day in days:
            current = day['date']
            while current.weekday() != 5:  # 5 = شنبه
                current -= timedelta(days=1)

            week_start = current
            if week_start not in weeks:
                weeks[week_start] = []
            weeks[week_start].append(day)

        # محاسبه برای هر هفته
        for week_start, week_days in weeks.items():
            # محاسبه مجموع ساعات هفته
            total_hours = sum(d['work_hours'] for d in week_days)

            # محاسبه اضافه کار روزانه هفته
            week_daily_overtime = sum(d['overtime'] for d in week_days)

            # اضافه کار هفتگی = مجموع کارکرد - 44 - اضافه کار روزانه
            if total_hours > self.WEEKLY_REQUIRED_HOURS:
                week_overtime = total_hours - self.WEEKLY_REQUIRED_HOURS - week_daily_overtime
                if week_overtime > 0:
                    weekly_overtime += week_overtime

        return weekly_overtime

    def _is_holiday(self, target_date: date, department: str) -> bool:
        """بررسی تعطیل بودن"""
        holidays = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).all()

        for holiday in holidays:
            if holiday.group_id is None:
                return True
            elif holiday.group_id == department:
                return True

        return False

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