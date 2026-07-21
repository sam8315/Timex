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
from core.time_calculator import calculate_shift_hours


class DetailedMonthlyReportGenerator:
    """تولید گزارش تفصیلی ماهانه"""

    # ساعات موظفی روزانه (گروه قراردادی)
    DAILY_REQUIRED_HOURS = 7.33  # 7:20

    # ساعات موظفی هفتگی
    WEEKLY_REQUIRED_HOURS = 44.0

    # ساعات کاری روزانه برای محاسبه اضافه کاری
    DAILY_OVERTIME_THRESHOLD = 8.0

    # کدهای وضعیت
    STATUS_PRESENT = 'P'
    STATUS_ABSENT = 'A'
    STATUS_HOLIDAY = 'H'
    STATUS_LEAVE = 'L'  # مرخصی (AL, SL, RL, UL)
    STATUS_REST = 'R'  # استراحت

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
        ).order_by(Employee.last_name, Employee.first_name).all()

    def generate_detailed_report(
            self,
            user_id: str,
            year: int,
            month: int
    ) -> Dict:
        """
        تولید گزارش تفصیلی ماهانه برای یک کارمند
        """
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
            return {'success': False, 'message': '❌ کارمند یافت نشد'}

        # دریافت تمام رکوردهای تردد ماه
        attendances = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= g_start,
                func.date(Attendance.timestamp) <= g_end,
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

        # دریافت درخواست‌های مرخصی تایید شده
        approved_leaves = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status == 'A',
                LeaveRequest.from_date <= g_end,
                LeaveRequest.to_date >= g_start
            )
        ).all()

        # ساخت لیست روزها
        days = []
        current = g_start
        while current <= g_end:
            j_date = jdatetime.date.fromgregorian(date=current)
            day_name = self._get_day_name(current)

            # تعیین وضعیت روز
            is_friday = current.weekday() == 4
            is_holiday = self._is_holiday(current, employee.department)
            is_day_off = is_friday or is_holiday

            # تعیین وضعیت فرد
            if current in statuses_by_date:
                status_code = statuses_by_date[current]
                if status_code in ['AL', 'SL', 'RL', 'UL']:
                    person_status = 'L'  # مرخصی
                    person_status_name = '🌴 مرخصی'
                elif status_code == 'R':
                    person_status = 'R'  # استراحت
                    person_status_name = '🛌 استراحت'
                elif status_code == 'A':
                    person_status = 'A'  # غیبت
                    person_status_name = '❌ غایب'
                elif status_code == 'P':
                    person_status = 'P'  # حاضر
                    person_status_name = '✅ حاضر'
                else:
                    person_status = 'P'
                    person_status_name = '✅ حاضر'
            elif current in attendances_by_day:
                person_status = 'P'
                person_status_name = '✅ حاضر'
            else:
                person_status = 'A'
                person_status_name = '❌ غایب'

            # اگر روز تعطیل است و حاضر است
            if is_day_off and person_status == 'P':
                if is_friday:
                    person_status_name = '🏢 جمعه کاری'
                else:
                    person_status_name = '🎉 تعطیل کاری'

            # محاسبه ساعات کاری
            day_attendances = attendances_by_day.get(current, [])
            enters = [a for a in day_attendances if a.punch == 0]
            exits = [a for a in day_attendances if a.punch == 1]

            work_hours = 0.0
            overtime = 0.0
            first_enter = None
            last_exit = None
            attendance_count = len(enters) + len(exits)

            if enters and exits:
                first_enter = min(e.timestamp for e in enters)
                last_exit = max(e.timestamp for e in exits)

                if last_exit > first_enter:
                    delta = (last_exit - first_enter).total_seconds() / 3600
                    work_hours = round(delta, 2)

                    # اضافه کاری روزانه
                    if work_hours > self.DAILY_OVERTIME_THRESHOLD:
                        overtime = round(work_hours - self.DAILY_OVERTIME_THRESHOLD, 2)

            # محاسبه ساعات تفکیکی
            shift_hours = {'morning': 0.0, 'evening': 0.0, 'night': 0.0}
            if first_enter and last_exit:
                shift_hours = calculate_shift_hours(first_enter, last_exit)

            # تعیین موظفی روز
            has_duty = True
            if is_day_off:
                has_duty = False
            elif person_status in ['L', 'R']:  # مرخصی یا استراحت
                has_duty = False
            elif person_status == 'A':  # غیبت
                has_duty = True

            daily_duty = self.DAILY_REQUIRED_HOURS if has_duty else 0.0

            days.append({
                'date': current,
                'jalali_date': j_date.strftime('%Y/%m/%d'),
                'day_name': day_name,
                'is_friday': is_friday,
                'is_holiday': is_holiday,
                'is_day_off': is_day_off,
                'day_status': '🔴 تعطیل' if is_day_off else '🟢 کاری',
                'person_status': person_status,
                'person_status_name': person_status_name,
                'first_enter': first_enter,
                'last_exit': last_exit,
                'attendance_count': attendance_count,
                'work_hours': work_hours,
                'overtime': overtime,
                'morning_hours': shift_hours['morning'],
                'evening_hours': shift_hours['evening'],
                'night_hours': shift_hours['night'],
                'has_duty': has_duty,
                'daily_duty': daily_duty
            })

            current += timedelta(days=1)

        # محاسبه خلاصه ماهانه
        summary = self._calculate_monthly_summary(days)

        return {
            'success': True,
            'employee': {
                'user_id': employee.user_id,
                'full_name': employee.full_name,
                'department': employee.department
            },
            'year': year,
            'month': month,
            'month_name': self._get_jalali_month_name(month),
            'days': days,
            'summary': summary
        }

    def _calculate_monthly_summary(self, days: List[Dict]) -> Dict:
        """محاسبه خلاصه ماهانه"""
        # شمارش روزها
        present_days = sum(1 for d in days if d['person_status'] == 'P' and not d['is_day_off'])
        leave_days = sum(1 for d in days if d['person_status'] == 'L')
        absent_days = sum(1 for d in days if d['person_status'] == 'A')
        rest_days = sum(1 for d in days if d['person_status'] == 'R')
        friday_work_days = sum(1 for d in days if d['is_friday'] and d['person_status'] == 'P')
        holiday_work_days = sum(1 for d in days if d['is_holiday'] and d['person_status'] == 'P')

        # محاسبه موظفی
        duty_days = sum(1 for d in days if d['has_duty'])
        total_duty_hours = sum(d['daily_duty'] for d in days)

        # محاسبه کارکرد
        total_work_hours = sum(d['work_hours'] for d in days)
        total_morning = sum(d['morning_hours'] for d in days)
        total_evening = sum(d['evening_hours'] for d in days)
        total_night = sum(d['night_hours'] for d in days)

        # محاسبه اضافه کاری
        daily_overtime = sum(d['overtime'] for d in days)

        # محاسبه اضافه کاری هفتگی
        weekly_overtime = self._calculate_weekly_overtime(days)

        # جمعه کاری و تعطیل کاری
        friday_work_hours = sum(d['work_hours'] for d in days if d['is_friday'] and d['person_status'] == 'P')
        holiday_work_hours = sum(d['work_hours'] for d in days if d['is_holiday'] and d['person_status'] == 'P')

        # کسری و اضافی (بدون تهاتر)
        deficit = max(0, total_duty_hours - total_work_hours)
        surplus = daily_overtime + weekly_overtime + friday_work_hours + holiday_work_hours

        return {
            'duty_days': duty_days,
            'duty_hours': round(total_duty_hours, 2),
            'present_days': present_days,
            'leave_days': leave_days,
            'absent_days': absent_days,
            'rest_days': rest_days,
            'friday_work_days': friday_work_days,
            'holiday_work_days': holiday_work_days,
            'total_work_hours': round(total_work_hours, 2),
            'total_morning': round(total_morning, 2),
            'total_evening': round(total_evening, 2),
            'total_night': round(total_night, 2),
            'daily_overtime': round(daily_overtime, 2),
            'weekly_overtime': round(weekly_overtime, 2),
            'friday_work_hours': round(friday_work_hours, 2),
            'holiday_work_hours': round(holiday_work_hours, 2),
            'deficit': round(deficit, 2),
            'surplus': round(surplus, 2)
        }

    def _calculate_weekly_overtime(self, days: List[Dict]) -> float:
        """محاسبه اضافه کاری هفتگی"""
        weekly_overtime = 0.0

        # گروه‌بندی روزها بر اساس هفته (شنبه تا جمعه)
        weeks = {}
        for day in days:
            # پیدا کردن شنبه هفته
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

            # محاسبه موظفی نسبی هفته
            duty_days_in_week = sum(1 for d in week_days if d['has_duty'])
            weekly_duty = duty_days_in_week * self.DAILY_REQUIRED_HOURS

            # اگر هفته کامل نیست، موظفی نسبی
            if len(week_days) < 7:
                weekly_duty = (len(week_days) / 7) * self.WEEKLY_REQUIRED_HOURS

            # اضافه کاری هفتگی
            if total_hours > self.WEEKLY_REQUIRED_HOURS:
                weekly_overtime += total_hours - self.WEEKLY_REQUIRED_HOURS

        return weekly_overtime

    def _is_holiday(self, target_date: date, department: str) -> bool:
        """بررسی تعطیل بودن"""
        holidays = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).all()

        for holiday in holidays:
            if holiday.group_id is None:  # تعطیل ملی
                return True
            elif holiday.group_id == department:  # تعطیل گروهی
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