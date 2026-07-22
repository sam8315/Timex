"""
ماژول مدیریت وضعیت روزانه
- تشخیص خودکار وضعیت بر اساس داده‌های موجود
- تعیین دستی وضعیت (ماموریت، حضور کم، ویژه)
- گزارش وضعیت روزانه
"""
from datetime import date, timedelta, datetime
from typing import List, Dict, Optional
from sqlalchemy import and_, or_, func  # ✅ اضافه شدن or_
from sqlalchemy.orm import Session
import jdatetime

from core.attendance_analyzer import calculate_night_hours
from database.engine import SessionLocal
from models import Employee
from models.user import User
from models.daily_status import DailyStatus
from models.attendance import Attendance
from models.leave_request import LeaveRequest
from models.contract import Contract
from core.holiday_manager import HolidayManager
from core.leave_manager import LeaveManager



class DailyStatusManager:
    """مدیریت وضعیت روزانه"""

    # کدهای وضعیت
    STATUS_PRESENT = 'P'  # حاضر
    STATUS_ABSENT = 'A'  # غایب
    STATUS_SICK = 'SL'  # استعلاجی
    STATUS_ANNUAL = 'AL'  # استحقاقی
    STATUS_REWARD = 'RL'  # تشویقی
    STATUS_UNPAID = 'UL'  # بدون حقوق
    STATUS_CARRYOVER = 'CW'  # ذخیره سال قبل
    STATUS_MISSION = 'M'  # ماموریت
    STATUS_LATE = 'LP'  # حضور کم/تاخیر
    STATUS_HOLIDAY = 'H'  # تعطیل
    STATUS_SPECIAL = 'S'  # ویژه (کلاس، اردو)

    STATUS_NAMES = {
        'P': '✅ حاضر',
        'A': '❌ غایب',
        'SL': '🏥 استعلاجی',
        'AL': '🌴 استحقاقی',
        'RL': '🎁 تشویقی',
        'UL': '💸 بدون حقوق',
        'CW': '📦 ذخیره سال قبل',
        'M': '💼 ماموریت',
        'LP': '⏰ حضور کم',
        'H': '🏖️ تعطیل',
        'S': '🎓 ویژه'
    }

    def __init__(self):
        self.db: Session = SessionLocal()
        self.holiday_manager = HolidayManager()
        self.leave_manager = LeaveManager()

    def close(self):
        if self.db:
            self.db.close()
        if self.holiday_manager:
            self.holiday_manager.close()
        if self.leave_manager:
            self.leave_manager.close()

    def get_status_name(self, code: str) -> str:
        """دریافت نام فارسی وضعیت"""
        return self.STATUS_NAMES.get(code, f'نامشخص ({code})')

    def detect_status(self, user_id: str, target_date: date) -> Dict:
        """
        تشخیص خودکار وضعیت یک کاربر در یک روز
        """
        # ✅ دریافت گروه کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        user_group_id = user.group_id if user else None

        # 1. بررسی تعطیلی (با در نظر گرفتن گروه کاربر)
        if self.holiday_manager.is_holiday(target_date, user_group_id):
            info = self.holiday_manager.get_holiday_info(target_date, user_group_id)
            return {
                'status': self.STATUS_HOLIDAY,
                'source': 'auto',
                'description': info.get('title', 'تعطیل'),
                'leave_request_id': None
            }

        # 2. بررسی درخواست مرخصی تایید شده
        approved_leave = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.from_date <= target_date,
                LeaveRequest.to_date >= target_date,
                LeaveRequest.status == 'A'
            )
        ).first()

        if approved_leave:
            return {
                'status': approved_leave.leave_type,
                'source': 'auto',
                'description': f'مرخصی تایید شده (شماره {approved_leave.id})',
                'leave_request_id': approved_leave.id
            }

        # 3. بررسی وضعیت دستی ثبت شده
        manual_status = self.db.query(DailyStatus).filter(
            and_(
                DailyStatus.user_id == user_id,
                DailyStatus.status_date == target_date
            )
        ).first()

        if manual_status:
            return {
                'status': manual_status.status_code,
                'source': 'manual',
                'description': manual_status.description or '',
                'leave_request_id': manual_status.leave_request_id
            }

        # 4. بررسی حضور (تردد)
        has_attendance = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == target_date,
                Attendance.is_deleted == False
            )
        ).first()

        if has_attendance:
            return {
                'status': self.STATUS_PRESENT,
                'source': 'auto',
                'description': 'حاضر بر اساس تردد',
                'leave_request_id': None
            }

        # 5. در غیر این صورت غایب
        return {
            'status': self.STATUS_ABSENT,
            'source': 'auto',
            'description': 'غایب (بدون تردد و بدون مرخصی)',
            'leave_request_id': None
        }

    def set_manual_status(
            self,
            user_id: str,
            target_date: date,
            status_code: str,
            description: str = ""
    ) -> Dict:
        """
        تعیین دستی وضعیت یک کاربر
        (برای ماموریت، حضور کم، ویژه)
        """
        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'❌ کاربر {user_id} یافت نشد'}

        # بررسی معتبر بودن کد وضعیت
        if status_code not in self.STATUS_NAMES:
            return {'success': False, 'message': f'❌ کد وضعیت نامعتبر: {status_code}'}

        try:
            # بررسی وجود وضعیت قبلی
            existing = self.db.query(DailyStatus).filter(
                and_(
                    DailyStatus.user_id == user_id,
                    DailyStatus.status_date == target_date
                )
            ).first()

            if existing:
                existing.status_code = status_code
                existing.description = description
                existing.leave_request_id = None
            else:
                status = DailyStatus(
                    user_id=user_id,
                    status_date=target_date,
                    status_code=status_code,
                    description=description
                )
                self.db.add(status)

            self.db.commit()

            j_date = jdatetime.date.fromgregorian(date=target_date)
            return {
                'success': True,
                'message': f'✅ وضعیت {self.get_status_name(status_code)} برای {j_date.strftime("%Y/%m/%d")} ثبت شد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_daily_report(
            self,
            target_date: date,
            group_id: Optional[str] = None,
            active_only: bool = True
    ) -> List[Dict]:
        """گزارش وضعیت روزانه - با وضعیت روز، فرد و تردد"""
        from core.employee_manager import EmployeeManager
        from core.attendance_analyzer import calculate_night_hours
        from models.holiday import Holiday

        # دریافت کارمندان فعال
        employees_query = self.db.query(Employee)
        if active_only:
            employees_query = employees_query.filter(Employee.is_active == True)

        if group_id is not None:
            employees_query = employees_query.filter(Employee.department == str(group_id))

        employees = employees_query.all()

        # ✅ بررسی وضعیت روز (تعطیل/کاری)
        is_friday = target_date.weekday() == 4
        holiday = self.db.query(Holiday).filter(Holiday.holiday_date == target_date).first()
        is_holiday = holiday is not None
        is_day_off = is_friday or is_holiday
        day_status = 'تعطیل' if is_day_off else 'کاری'

        emp_manager = EmployeeManager()
        report = []

        try:
            for emp in employees:
                status_info = self.detect_status(emp.user_id, target_date)

                # ✅ اول: دریافت رکوردهای تردد روز
                attendances = self.db.query(Attendance).filter(
                    and_(
                        Attendance.user_id == emp.user_id,
                        func.date(Attendance.timestamp) == target_date,
                        Attendance.is_deleted == False
                    )
                ).order_by(Attendance.timestamp).all()

                enters = [a for a in attendances if a.punch == 0]
                exits = [a for a in attendances if a.punch == 1]

                # ✅ دوم: تعیین وضعیت فرد (حالا attendances در دسترس است)
                person_status_code = status_info['status']

                # اولویت ۱: وضعیت‌های دستی خاص
                if person_status_code == 'R':
                    person_status = 'استراحت'
                elif person_status_code == 'M':
                    person_status = 'ماموریت'
                elif person_status_code == 'LP':
                    person_status = 'حضور کم'
                elif person_status_code in ['AL', 'SL', 'RL', 'UL']:
                    person_status = 'مرخصی'

                # اولویت ۲: بررسی روز تعطیل
                elif is_day_off:
                    has_attendance = len(attendances) > 0
                    if has_attendance:
                        person_status = 'حاضر'
                    else:
                        person_status = 'تعطیل'

                # اولویت ۳: روز کاری عادی
                elif person_status_code == 'P':
                    person_status = 'حاضر'
                elif person_status_code == 'A':
                    person_status = 'غایب'
                else:
                    person_status = 'نامشخص'

                # ✅ سوم: دریافت اطلاعات قرارداد
                contract = self.db.query(Contract).filter(
                    and_(
                        Contract.user_id == emp.user_id,
                        Contract.start_date <= target_date,
                        or_(
                            Contract.end_date == None,
                            Contract.end_date >= target_date
                        )
                    )
                ).order_by(Contract.start_date.desc()).first()

                contract_info = {
                    'has_contract': contract is not None,
                    'type': contract.contract_type if contract else None,
                    'status': 'فعال' if contract else 'بدون قرارداد'
                }

                # ✅ چهارم: محاسبه ساعات کاری با مدیریت تردد شبانه
                work_hours = 0.0
                night_hours = 0.0

                if not enters and not exits:
                    attendance_status = 'بدون تردد'
                elif enters and exits:
                    first_in = min(e.timestamp for e in enters)
                    last_out = max(e.timestamp for e in exits)

                    # ✅ بررسی تردد شبانه (خروج فردا)
                    if last_out.date() > target_date:
                        # خروج فردا است، کارکرد امروز تا 23:59
                        from datetime import datetime as dt
                        end_of_day = dt.combine(target_date, dt.max.time())
                        if first_in.tzinfo is not None:
                            end_of_day = end_of_day.replace(tzinfo=first_in.tzinfo)
                        work_hours = (end_of_day - first_in).total_seconds() / 3600
                        attendance_status = f'کامل (خروج فردا)'
                    elif last_out > first_in:
                        # محاسبه کارکرد عادی
                        if len(enters) == len(exits):
                            if len(enters) == 1:
                                attendance_status = 'کامل'
                            else:
                                attendance_status = f'کامل{len(enters)}'
                        else:
                            attendance_status = f'ناقص ({len(enters)}و/{len(exits)}خ)'

                        delta = (last_out - first_in).total_seconds() / 3600
                        work_hours = round(delta, 2)
                        night_hours = round(calculate_night_hours(first_in, last_out), 2)
                    else:
                        attendance_status = 'خطا در تردد'

                elif enters and not exits:
                    # ✅ بررسی آیا فردا خروج دارد
                    next_day = target_date + timedelta(days=1)
                    next_day_attendances = self.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == emp.user_id,
                            func.date(Attendance.timestamp) == next_day,
                            Attendance.is_deleted == False
                        )
                    ).all()
                    next_day_exits = [a for a in next_day_attendances if a.punch == 1]

                    if next_day_exits:
                        # فردا خروج دارد
                        first_in = min(e.timestamp for e in enters)
                        from datetime import datetime as dt
                        end_of_day = dt.combine(target_date, dt.max.time())
                        if first_in.tzinfo is not None:
                            end_of_day = end_of_day.replace(tzinfo=first_in.tzinfo)
                        work_hours = (end_of_day - first_in).total_seconds() / 3600
                        attendance_status = 'کامل (خروج فردا)'
                    else:
                        attendance_status = f'ورود بدون خروج ({len(enters)} ورود)'

                elif exits and not enters:
                    # ✅ بررسی آیا دیروز ورود داشته
                    prev_day = target_date - timedelta(days=1)
                    prev_day_attendances = self.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == emp.user_id,
                            func.date(Attendance.timestamp) == prev_day,
                            Attendance.is_deleted == False
                        )
                    ).all()
                    prev_day_enters = [a for a in prev_day_attendances if a.punch == 0]

                    if prev_day_enters:
                        # دیروز ورود داشته، کارکرد امروز از 00:00
                        last_out = max(e.timestamp for e in exits)
                        from datetime import datetime as dt
                        start_of_day = dt.combine(target_date, dt.min.time())
                        if last_out.tzinfo is not None:
                            start_of_day = start_of_day.replace(tzinfo=last_out.tzinfo)
                        work_hours = (last_out - start_of_day).total_seconds() / 3600
                        attendance_status = 'کامل (ورود دیروز)'
                    else:
                        attendance_status = f'خروج بدون ورود ({len(exits)} خروج)'

                report.append({
                    'user_id': emp.user_id,
                    'full_name': emp.full_name,
                    'department': emp.department or 'بدون گروه',
                    'hire_date': emp.hire_date,  # ✅ اضافه شد
                    'day_status': day_status,
                    'person_status': person_status,
                    'attendance_status': attendance_status,
                    'status': status_info['status'],
                    'status_name': self.get_status_name(status_info['status']),
                    'source': status_info['source'],
                    'description': status_info['description'],
                    'attendance_count': len(attendances),
                    'work_hours': work_hours,
                    'night_hours': night_hours,
                    'enters_count': len(enters),
                    'exits_count': len(exits),
                    'first_enter': min(e.timestamp for e in enters).time() if enters else None,
                    'last_exit': max(e.timestamp for e in exits).time() if exits else None,
                    'contract': contract_info
                })
        finally:
            emp_manager.close()

            # ✅ مرتب‌سازی بر اساس تاریخ استخدام

        def sort_key(r):
            hire_date = r.get('hire_date')
            if hire_date is None:
                # اگر تاریخ استخدام ندارد، آخر قرار بگیرد
                return (date.max, r.get('full_name', ''))
            return (hire_date, r.get('full_name', ''))

        return sorted(report, key=sort_key)



    def get_monthly_report(self, user_id: str, year: int, month: int) -> Dict:
        """گزارش ماهانه یک کاربر"""
        # ✅ دریافت گروه کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        user_group_id = user.group_id if user else None

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

        # شمارش وضعیت‌ها
        status_counts = {}
        current = g_start
        while current <= g_end:
            status_info = self.detect_status(user_id, current)
            code = status_info['status']
            status_counts[code] = status_counts.get(code, 0) + 1
            current += timedelta(days=1)

        # محاسبه ساعات کاری
        total_work_hours = 0.0
        total_night_hours = 0.0

        attendances = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= g_start,
                func.date(Attendance.timestamp) <= g_end,
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).all()

        from core.attendance_analyzer import calculate_night_hours
        days_dict = {}
        for att in attendances:
            day = att.timestamp.date()
            if day not in days_dict:
                days_dict[day] = []
            days_dict[day].append(att)

        for day, records in days_dict.items():
            enters = [r for r in records if r.punch == 0]
            exits = [r for r in records if r.punch == 1]
            if enters and exits:
                first_in = min(e.timestamp for e in enters)
                last_out = max(e.timestamp for e in exits)
                delta = (last_out - first_in).total_seconds() / 3600
                total_work_hours += delta
                total_night_hours += calculate_night_hours(first_in, last_out)

        return {
            'user_id': user_id,
            'year': year,
            'month': month,
            'from_date': g_start,
            'to_date': g_end,
            'status_counts': status_counts,
            'total_work_hours': round(total_work_hours, 2),
            'total_night_hours': round(total_night_hours, 2),
            'total_days': (g_end - g_start).days + 1
        }

    def get_bulk_absent_report(self, target_date: date) -> List[Dict]:
        """گزارش غایبین یک روز"""
        report = self.get_daily_report(target_date)
        return [r for r in report if r['status'] == self.STATUS_ABSENT]

    def get_daily_details_for_month(self, user_id: str, year: int, month: int) -> Dict:
        """
        دریافت جزئیات روز به روز یک کاربر در یک ماه شمسی

        Returns:
            Dict: شامل لیست روزها و خلاصه
        """
        import jdatetime
        from core.attendance_analyzer import calculate_night_hours
        from core.employee_manager import EmployeeManager

        # محاسبه بازه ماه شمسی
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

        # دریافت تمام وضعیت‌های روزانه ماه
        daily_statuses = self.db.query(DailyStatus).filter(
            and_(
                DailyStatus.user_id == user_id,
                DailyStatus.status_date >= g_start,
                DailyStatus.status_date <= g_end
            )
        ).all()

        statuses_by_day = {ds.status_date: ds for ds in daily_statuses}

        # دریافت درخواست‌های مرخصی تایید شده
        from models.leave_request import LeaveRequest
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
            status_info = self.detect_status(user_id, current)

            # محاسبه ساعات کاری
            day_attendances = attendances_by_day.get(current, [])
            enters = [a for a in day_attendances if a.punch == 0]
            exits = [a for a in day_attendances if a.punch == 1]

            work_hours = 0.0
            night_hours = 0.0
            first_enter = None
            last_exit = None
            attendance_status = '—'

            if enters and exits:
                first_enter = min(e.timestamp for e in enters)
                last_exit = max(e.timestamp for e in exits)

                if last_exit > first_enter:
                    delta = (last_exit - first_enter).total_seconds() / 3600
                    work_hours = round(delta, 2)
                    night_hours = round(calculate_night_hours(first_enter, last_exit), 2)

                    if len(enters) == 1 and len(exits) == 1:
                        attendance_status = '✅ کامل'
                    else:
                        attendance_status = f'🔄 {len(enters)}و/{len(exits)}خ'
            elif enters and not exits:
                attendance_status = '⚠️ بدون خروج'
                first_enter = min(e.timestamp for e in enters)
            elif exits and not enters:
                attendance_status = '❌ بدون ورود'
                last_exit = max(e.timestamp for e in exits)

            days.append({
                'date': current,
                'jalali_date': j_date.strftime('%Y/%m/%d'),
                'day_of_month': j_date.day,
                'day_name': day_name,
                'is_friday': current.weekday() == 4,
                'status': status_info['status'],
                'status_name': self.get_status_name(status_info['status']),
                'status_source': status_info['source'],
                'work_hours': work_hours,
                'night_hours': night_hours,
                'first_enter': first_enter,
                'last_exit': last_exit,
                'enters_count': len(enters),
                'exits_count': len(exits),
                'attendance_status': attendance_status,
                'has_attendance': len(day_attendances) > 0
            })

            current += timedelta(days=1)

        # محاسبه خلاصه
        status_counts = {}
        total_work = 0.0
        total_night = 0.0
        working_days = 0
        present_days = 0

        for day in days:
            code = day['status']
            status_counts[code] = status_counts.get(code, 0) + 1

            if not day['is_friday']:
                working_days += 1
                if code == 'P':
                    present_days += 1

            total_work += day['work_hours']
            total_night += day['night_hours']

        return {
            'user_id': user_id,
            'year': year,
            'month': month,
            'month_name': self._get_jalali_month_name(month),
            'from_date': g_start,
            'to_date': g_end,
            'days': days,
            'summary': {
                'total_days': len(days),
                'working_days': working_days,
                'present_days': present_days,
                'status_counts': status_counts,
                'total_work_hours': round(total_work, 2),
                'total_night_hours': round(total_night, 2)
            }
        }

    def _get_day_name(self, d: date) -> str:
        """دریافت نام روز هفته به فارسی"""
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