"""
ماژول گزارش تفصیلی ماهانه کارمند - نسخه ۲
با ستون‌های متعدد ورود/خروج و مبنای محاسبه 7:20
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


class DetailedMonthlyReportGeneratorV2:
    """تولید گزارش تفصیلی ماهانه - نسخه ۲"""

    # ساعات موظفی روزانه (گروه قراردادی)
    DAILY_REQUIRED_HOURS = 7.33  # 7:20

    # ساعات موظفی هفتگی
    WEEKLY_REQUIRED_HOURS = 44.0

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

        # ✅ دریافت درخواست‌های مرخصی تایید شده
        approved_leaves = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status == 'A',  # تایید شده
                LeaveRequest.from_date <= g_end,
                LeaveRequest.to_date >= g_start
            )
        ).all()

        # ✅ ساخت دیکشنری مرخصی‌ها بر اساس تاریخ
        leaves_by_date = {}
        for leave in approved_leaves:
            current = leave.from_date
            while current <= leave.to_date:
                if current >= g_start and current <= g_end:
                    leaves_by_date[current] = leave.leave_type
                current += timedelta(days=1)

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
            is_holiday = self._is_holiday(current, employee.department)
            is_day_off = is_friday or is_holiday

            # تعیین وضعیت فرد
            person_status = self._determine_person_status(
                current, statuses_by_date, attendances_by_day, is_day_off
            )

            # محاسبه ساعات کاری با چند جفت ورود/خروج
            day_data = self._calculate_day_work_hours_v2(
                current, attendances_by_day.get(current, []), attendances
            )

            work_hours = day_data['work_hours']
            attendance_pairs = day_data['pairs']
            attendance_status = day_data['attendance_status']
            has_incomplete = day_data['has_incomplete']

            # محاسبه اضافی/کسری بر اساس 7:20
            surplus, deficit = self._calculate_surplus_deficit(
                work_hours, is_day_off, person_status
            )

            # محاسبه ساعات تفکیکی
            shift_hours = {'morning': 0.0, 'evening': 0.0, 'night': 0.0}
            if attendance_pairs:
                first_enter = attendance_pairs[0]['enter']
                last_exit = attendance_pairs[-1]['exit']
                if first_enter and last_exit and last_exit > first_enter:
                    shift_hours = calculate_shift_hours(first_enter, last_exit)

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
                'attendance_pairs': attendance_pairs,
                'attendance_status': attendance_status,
                'has_incomplete': has_incomplete,
                'work_hours': work_hours,
                'surplus': surplus,
                'deficit': deficit,
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
            # ✅ بررسی انواع مرخصی
            if status_code in ['AL', 'SL', 'RL', 'UL', 'L']:
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

        # اگر روز تعطیل است و تردد ندارد → تعطیل
        if is_day_off:
            return {'code': 'H', 'name': 'تعطیل'}

        return {'code': 'A', 'name': 'غایب'}

    def _calculate_day_work_hours_v2(self, current: date, day_attendances: List, all_attendances: List) -> Dict:
        """
        محاسبه ساعات کاری روز با چند جفت ورود/خروج - نسخه ۲
        """
        if not day_attendances:
            return {
                'work_hours': 0.0,
                'pairs': [],
                'attendance_status': 'بدون تردد',
                'has_incomplete': False
            }

        enters = sorted([a for a in day_attendances if a.punch == 0], key=lambda x: x.timestamp)
        exits = sorted([a for a in day_attendances if a.punch == 1], key=lambda x: x.timestamp)

        # تابع کمکی برای ساخت datetime با timezone صحیح
        def make_aware_datetime(d: date, hour: int, minute: int, second: int, microsecond: int, ref_timestamp):
            naive_dt = datetime.combine(d, datetime.min.time().replace(
                hour=hour, minute=minute, second=second, microsecond=microsecond
            ))
            if ref_timestamp.tzinfo is not None:
                return naive_dt.replace(tzinfo=ref_timestamp.tzinfo)
            return naive_dt

        # حالت ۱: ورود و خروج هر دو در این روز
        if enters and exits:
            first_enter = min(e.timestamp for e in enters)
            last_exit = max(e.timestamp for e in exits)

            # بررسی آیا خروج فردا است
            if last_exit.date() > current:
                end_of_day = make_aware_datetime(current, 23, 59, 59, 999999, first_enter)

                pairs = []
                for i, enter in enumerate(enters):
                    if i < len(exits):
                        exit_time = exits[i].timestamp
                        if exit_time.date() > current:
                            exit_time = end_of_day
                        if exit_time > enter.timestamp:
                            pairs.append({
                                'enter': enter.timestamp,
                                'exit': exit_time,
                                'hours': round((exit_time - enter.timestamp).total_seconds() / 3600, 2)
                            })

                work_hours = sum(p['hours'] for p in pairs)

                return {
                    'work_hours': round(work_hours, 2),
                    'pairs': pairs[:self.MAX_PAIRS],
                    'attendance_status': f'کامل (خروج فردا)',
                    'has_incomplete': False
                }

            # خروج در همان روز است
            if last_exit > first_enter:
                pairs = []
                for i, enter in enumerate(enters):
                    if i < len(exits):
                        exit_time = exits[i].timestamp
                        if exit_time > enter.timestamp:
                            pairs.append({
                                'enter': enter.timestamp,
                                'exit': exit_time,
                                'hours': round((exit_time - enter.timestamp).total_seconds() / 3600, 2)
                            })

                work_hours = sum(p['hours'] for p in pairs)

                if len(enters) == len(exits):
                    if len(enters) == 1:
                        attendance_status = 'کامل'
                    else:
                        attendance_status = f'کامل{len(enters)}'
                else:
                    attendance_status = f'ناقص ({len(enters)}و/{len(exits)}خ)'

                return {
                    'work_hours': round(work_hours, 2),
                    'pairs': pairs[:self.MAX_PAIRS],
                    'attendance_status': attendance_status,
                    'has_incomplete': len(enters) != len(exits)
                }

        # حالت ۲: فقط ورود (بررسی آیا فردا خروج دارد)
        if enters and not exits:
            first_enter = min(e.timestamp for e in enters)

            next_day = current + timedelta(days=1)
            next_day_attendances = [a for a in all_attendances if a.timestamp.date() == next_day]
            next_day_exits = [a for a in next_day_attendances if a.punch == 1]

            if next_day_exits:
                end_of_day = make_aware_datetime(current, 23, 59, 59, 999999, first_enter)
                work_hours = (end_of_day - first_enter).total_seconds() / 3600

                pairs = [{
                    'enter': first_enter,
                    'exit': end_of_day,
                    'hours': round(work_hours, 2)
                }]

                return {
                    'work_hours': round(work_hours, 2),
                    'pairs': pairs,
                    'attendance_status': 'کامل (خروج فردا)',
                    'has_incomplete': False
                }
            else:
                return {
                    'work_hours': 0.0,
                    'pairs': [],
                    'attendance_status': f'ورود بدون خروج ({len(enters)} ورود)',
                    'has_incomplete': True
                }

        # حالت ۳: فقط خروج (بررسی آیا دیروز ورود داشته)
        if exits and not enters:
            last_exit = max(e.timestamp for e in exits)

            prev_day = current - timedelta(days=1)
            prev_day_attendances = [a for a in all_attendances if a.timestamp.date() == prev_day]
            prev_day_enters = [a for a in prev_day_attendances if a.punch == 0]

            if prev_day_enters:
                start_of_day = make_aware_datetime(current, 0, 0, 0, 0, last_exit)
                work_hours = (last_exit - start_of_day).total_seconds() / 3600

                pairs = [{
                    'enter': start_of_day,
                    'exit': last_exit,
                    'hours': round(work_hours, 2)
                }]

                return {
                    'work_hours': round(work_hours, 2),
                    'pairs': pairs,
                    'attendance_status': 'کامل (ورود دیروز)',
                    'has_incomplete': False
                }
            else:
                return {
                    'work_hours': 0.0,
                    'pairs': [],
                    'attendance_status': f'خروج بدون ورود ({len(exits)} خروج)',
                    'has_incomplete': True
                }

        return {
            'work_hours': 0.0,
            'pairs': [],
            'attendance_status': 'بدون تردد',
            'has_incomplete': False
        }

    def _calculate_surplus_deficit(self, work_hours: float, is_day_off: bool, person_status: Dict) -> tuple:
        """
        محاسبه اضافی و کسری بر اساس مبنای 7:20
        """
        # اگر روز تعطیل است و تردد ندارد
        if is_day_off and person_status['code'] == 'H':
            return 0.0, 0.0

        # اگر روز تعطیل است و تردد دارد (تعطیل کاری)
        if is_day_off and person_status['code'] == 'P':
            return work_hours, 0.0

        # اگر مرخصی یا استراحت است
        if person_status['code'] in ['L', 'R']:
            if work_hours > 0:
                return work_hours, 0.0
            return 0.0, 0.0

        # روز کاری عادی
        if work_hours > self.DAILY_REQUIRED_HOURS:
            surplus = work_hours - self.DAILY_REQUIRED_HOURS
            return round(surplus, 2), 0.0
        elif work_hours < self.DAILY_REQUIRED_HOURS and work_hours > 0:
            deficit = self.DAILY_REQUIRED_HOURS - work_hours
            return 0.0, round(deficit, 2)
        elif work_hours == 0:
            # روز کاری ولی بدون تردد
            return 0.0, self.DAILY_REQUIRED_HOURS

        return 0.0, 0.0

    def _has_duty(self, is_day_off: bool, person_status: Dict) -> bool:
        """تعیین اینکه آیا روز موظفی دارد"""
        if is_day_off:
            return False
        if person_status['code'] in ['L', 'R']:
            return False
        if person_status['code'] == 'A':
            return True
        return True

    def _calculate_monthly_summary(self, days: List[Dict]) -> Dict:
        """محاسبه خلاصه ماهانه"""
        # ✅ شمارش روزها با تفکیک دقیق
        # روزهای کاری عادی که حاضر بوده
        present_days = sum(1 for d in days if d['person_status'] == 'P' and not d['is_day_off'])

        # جمعه‌هایی که حاضر بوده (جمعه کاری)
        friday_work_days = sum(1 for d in days if d['is_friday'] and d['person_status'] == 'P')

        # تعطیل‌های غیر جمعه که حاضر بوده (تعطیل کاری)
        holiday_work_days = sum(1 for d in days if d['is_holiday'] and not d['is_friday'] and d['person_status'] == 'P')

        leave_days = sum(1 for d in days if d['person_status'] == 'L')
        absent_days = sum(1 for d in days if d['person_status'] == 'A')
        rest_days = sum(1 for d in days if d['person_status'] == 'R')
        holiday_days = sum(1 for d in days if d['person_status'] == 'H')

        # محاسبه موظفی
        duty_days = sum(1 for d in days if d['has_duty'])
        total_duty_hours = sum(d['daily_duty'] for d in days)

        # محاسبه کارکرد
        total_work_hours = sum(d['work_hours'] for d in days)
        total_morning = sum(d['morning_hours'] for d in days)
        total_evening = sum(d['evening_hours'] for d in days)
        total_night = sum(d['night_hours'] for d in days)

        # محاسبه اضافی و کسری بر اساس 7:20
        total_surplus = sum(d['surplus'] for d in days)
        total_deficit = sum(d['deficit'] for d in days)

        # تهاتر و وضعیت کلی
        net_balance = total_surplus - total_deficit

        if net_balance > 0:
            overall_status = 'اضافی'
            net_balance_hours = net_balance
        elif net_balance < 0:
            overall_status = 'کسری'
            net_balance_hours = abs(net_balance)
        else:
            overall_status = 'متعادل'
            net_balance_hours = 0.0

        # محاسبه اضافه کار هفتگی
        weekly_overtime = self._calculate_weekly_overtime(days)

        # جمعه کاری (ساعات)
        friday_work_hours = sum(d['work_hours'] for d in days if d['is_friday'] and d['person_status'] == 'P')

        # تعطیل کاری (ساعات)
        holiday_work_hours = sum(
            d['work_hours'] for d in days if d['is_holiday'] and not d['is_friday'] and d['person_status'] == 'P')

        return {
            'duty_days': duty_days,
            'duty_hours': round(total_duty_hours, 2),
            'present_days': present_days,
            'leave_days': leave_days,
            'absent_days': absent_days,
            'rest_days': rest_days,
            'holiday_days': holiday_days,
            'friday_work_days': friday_work_days,
            'holiday_work_days': holiday_work_days,  # ✅ اضافه شد
            'total_work_hours': round(total_work_hours, 2),
            'total_morning': round(total_morning, 2),
            'total_evening': round(total_evening, 2),
            'total_night': round(total_night, 2),
            'total_surplus': round(total_surplus, 2),
            'total_deficit': round(total_deficit, 2),
            'net_balance': round(net_balance, 2),
            'overall_status': overall_status,
            'net_balance_hours': round(net_balance_hours, 2),
            'weekly_overtime': round(weekly_overtime, 2),
            'friday_work_hours': round(friday_work_hours, 2),
            'holiday_work_hours': round(holiday_work_hours, 2)  # ✅ اضافه شد
        }

    def _calculate_weekly_overtime(self, days: List[Dict]) -> float:
        """محاسبه اضافه کار هفتگی"""
        weekly_overtime = 0.0

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
            total_hours = sum(d['work_hours'] for d in week_days)

            if total_hours > self.WEEKLY_REQUIRED_HOURS:
                weekly_overtime += total_hours - self.WEEKLY_REQUIRED_HOURS

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