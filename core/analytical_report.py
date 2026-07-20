"""
ماژول گزارش تحلیلی ماهانه
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.employee import Employee
from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.leave_request import LeaveRequest
from models.holiday import Holiday
from core.time_calculator import calculate_shift_hours


class AnalyticalReportGenerator:
    """تولید گزارش تحلیلی ماهانه"""

    # ساعات موظفی روزانه بر اساس گروه
    DAILY_REQUIRED_HOURS = {
        '0': 7.33,  # بدون گروه (7:20)
        '1': 7.33,  # رسمی (7:20) - بعداً تغییر می‌کند
        '2': 7.33,  # وظیفه (7:20) - بعداً تغییر می‌کند
        '3': 7.33,  # خریدخدمت (7:20) - بعداً تغییر می‌کند
        '4': 7.33,  # قراردادی (7:20)
        '5': 7.33,  # پزشک (7:20) - بعداً تغییر می‌کند
    }

    # کدهای مرخصی
    LEAVE_CODES = ['AL', 'SL', 'RL', 'UL']

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def get_month_days_info(self, year: int, month: int) -> Dict:
        """دریافت اطلاعات روزهای ماه"""
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

        # شمارش جمعه‌ها
        fridays = 0
        current = g_start
        while current <= g_end:
            if current.weekday() == 4:  # جمعه
                fridays += 1
            current += timedelta(days=1)

        # دریافت تعطیلات ثبت شده
        holidays = self.db.query(Holiday).filter(
            and_(
                Holiday.holiday_date >= g_start,
                Holiday.holiday_date <= g_end
            )
        ).count()

        total_days = (g_end - g_start).days + 1
        working_days = total_days - fridays - holidays

        return {
            'total_days': total_days,
            'fridays': fridays,
            'holidays': holidays,
            'working_days': working_days,
            'start_date': g_start,
            'end_date': g_end
        }

    def generate_monthly_report(
            self,
            year: int,
            month: int,
            group_id: Optional[int] = None
    ) -> Dict:
        """
        تولید گزارش تحلیلی ماهانه

        Returns:
            Dict: شامل لیست کاربران به تفکیک گروه
        """
        month_info = self.get_month_days_info(year, month)
        g_start = month_info['start_date']
        g_end = month_info['end_date']

        # دریافت کاربران
        users_query = self.db.query(User)
        if group_id is not None:
            users_query = users_query.filter(User.group_id == str(group_id))

        users = users_query.all()

        # گروه‌بندی بر اساس group_id
        groups = {}

        for user in users:
            # دریافت اطلاعات کاربر
            employee = self.db.query(Employee).filter(Employee.user_id == user.user_id).first()
            full_name = employee.full_name if employee else user.name

            # دریافت وضعیت‌های روزانه ماه
            daily_statuses = self.db.query(DailyStatus).filter(
                and_(
                    DailyStatus.user_id == user.user_id,
                    DailyStatus.status_date >= g_start,
                    DailyStatus.status_date <= g_end
                )
            ).all()

            # شمارش وضعیت‌ها
            status_counts = {
                'P': 0, 'A': 0, 'H': 0, 'AL': 0, 'SL': 0,
                'RL': 0, 'UL': 0, 'M': 0, 'LP': 0, 'S': 0
            }

            leave_days = 0
            for ds in daily_statuses:
                if ds.status_code in status_counts:
                    status_counts[ds.status_code] += 1

                # شمارش روزهای مرخصی
                if ds.status_code in self.LEAVE_CODES:
                    leave_days += 1

            # ماموریت و حضور کم جزو حاضر
            present_days = status_counts['P'] + status_counts['M'] + status_counts['LP']
            absent_days = status_counts['A']
            total_leave = sum(status_counts[code] for code in self.LEAVE_CODES)

            # اگر کاربر هیچ ترددی نداشته، رد کن
            attendances = self.db.query(Attendance).filter(
                and_(
                    Attendance.user_id == user.user_id,
                    func.date(Attendance.timestamp) >= g_start,
                    func.date(Attendance.timestamp) <= g_end,
                    Attendance.is_deleted == False
                )
            ).all()

            if not attendances and present_days == 0:
                continue  # کاربر بدون تردد

            # محاسبه ساعات کاری تفکیکی
            total_morning = 0.0
            total_evening = 0.0
            total_night = 0.0
            total_work = 0.0

            # گروه‌بندی تردد بر اساس روز
            attendances_by_day = {}
            for att in attendances:
                day = att.timestamp.date()
                if day not in attendances_by_day:
                    attendances_by_day[day] = []
                attendances_by_day[day].append(att)

            # محاسبه برای هر روز
            for day, day_attendances in attendances_by_day.items():
                enters = [a for a in day_attendances if a.punch == 0]
                exits = [a for a in day_attendances if a.punch == 1]

                if enters and exits:
                    first_in = min(e.timestamp for e in enters)
                    last_out = max(e.timestamp for e in exits)

                    if last_out > first_in:
                        shift_hours = calculate_shift_hours(first_in, last_out)
                        total_morning += shift_hours['morning']
                        total_evening += shift_hours['evening']
                        total_night += shift_hours['night']
                        total_work += shift_hours['total']

            # محاسبه موظفی
            required_days = month_info['working_days'] - leave_days
            daily_required = self.DAILY_REQUIRED_HOURS.get(user.group_id, 7.33)
            required_hours = required_days * daily_required

            # محاسبه کسری/اضافی
            difference = total_work - required_hours

            # ساخت رکورد کاربر
            user_record = {
                'user_id': user.user_id,
                'full_name': full_name,
                'group_id': user.group_id,
                'present_days': present_days,
                'absent_days': absent_days,
                'leave_days': total_leave,
                'required_days': required_days,
                'required_hours': round(required_hours, 2),
                'morning_hours': round(total_morning, 2),
                'evening_hours': round(total_evening, 2),
                'night_hours': round(total_night, 2),
                'total_hours': round(total_work, 2),
                'difference': round(difference, 2)
            }

            # اضافه به گروه
            group_name = self._get_group_name(user.group_id)
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(user_record)

        # مرتب‌سازی کاربران در هر گروه بر اساس نام
        for group_name in groups:
            groups[group_name].sort(key=lambda x: x['full_name'])

        return {
            'year': year,
            'month': month,
            'month_name': self._get_jalali_month_name(month),
            'month_info': month_info,
            'groups': groups
        }

    def _get_group_name(self, group_id: str) -> str:
        """دریافت نام گروه"""
        group_names = {
            '0': 'بدون گروه',
            '1': 'رسمی',
            '2': 'وظیفه',
            '3': 'خریدخدمت',
            '4': 'قراردادی',
            '5': 'پزشک'
        }
        return group_names.get(group_id, f'گروه {group_id}')

    def _get_jalali_month_name(self, month: int) -> str:
        """دریافت نام ماه شمسی"""
        names = {
            1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
            4: 'تیر', 5: 'مرداد', 6: 'شهریور',
            7: 'مهر', 8: 'آبان', 9: 'آذر',
            10: 'دی', 11: 'بهمن', 12: 'اسفند'
        }
        return names.get(month, '')