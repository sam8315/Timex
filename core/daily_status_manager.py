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

from database.engine import SessionLocal
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

        اولویت:
        1. تعطیلی (جمعه یا تعطیل ثبت شده)
        2. درخواست مرخصی تایید شده
        3. وضعیت دستی ثبت شده
        4. حضور (اگر تردد دارد)
        5. غیبت (اگر تردد ندارد)
        """
        # 1. بررسی تعطیلی
        if self.holiday_manager.is_holiday(target_date):
            info = self.holiday_manager.get_holiday_info(target_date)
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
            group_id: Optional[int] = None
    ) -> List[Dict]:
        """
        گزارش وضعیت روزانه همه کاربران در یک روز
        شامل: وضعیت، قرارداد، ساعات کاری
        """
        from core.employee_manager import EmployeeManager
        from core.attendance_analyzer import calculate_night_hours

        users = self.db.query(User)
        if group_id is not None:
            users = users.filter(User.group_id == str(group_id))
        users = users.all()

        emp_manager = EmployeeManager()
        report = []

        try:
            for user in users:
                status_info = self.detect_status(user.user_id, target_date)

                # ✅ دریافت نام کامل
                full_name = emp_manager.get_full_name(user.user_id)

                # ✅ دریافت اطلاعات قرارداد
                contract = self.db.query(Contract).filter(
                    and_(
                        Contract.user_id == user.user_id,
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
                    'status': '✅ فعال' if contract else '❌ بدون قرارداد'
                }

                # ✅ دریافت رکوردهای تردد روز
                attendances = self.db.query(Attendance).filter(
                    and_(
                        Attendance.user_id == user.user_id,
                        func.date(Attendance.timestamp) == target_date,
                        Attendance.is_deleted == False
                    )
                ).order_by(Attendance.timestamp).all()

                # محاسبه ساعات کاری
                enters = [a for a in attendances if a.punch == 0]
                exits = [a for a in attendances if a.punch == 1]

                work_hours = 0.0
                night_hours = 0.0
                attendance_status = '—'  # پیش‌فرض: بدون تردد

                if enters and exits:
                    first_in = min(e.timestamp for e in enters)
                    last_out = max(e.timestamp for e in exits)

                    if last_out > first_in:
                        delta = (last_out - first_in).total_seconds() / 3600
                        work_hours = round(delta, 2)
                        night_hours = round(calculate_night_hours(first_in, last_out), 2)

                        if len(enters) == 1 and len(exits) == 1:
                            attendance_status = '✅ کامل'
                        else:
                            attendance_status = f'🔄 {len(enters)}و/{len(exits)}خ'
                elif enters and not exits:
                    attendance_status = '⚠️ بدون خروج'
                    # محاسبه ساعت تا الان
                    # first_in = min(e.timestamp for e in enters)
                    # delta = (datetime.now(first_in.tzinfo) - first_in).total_seconds() / 3600
                    # work_hours = round(delta, 2)
                elif exits and not enters:
                    attendance_status = '❌ بدون ورود'
                else:
                    attendance_status = '— بدون تردد'

                report.append({
                    'user_id': user.user_id,
                    'name': user.name,
                    'full_name': full_name,
                    'group_id': user.group_id,
                    'status': status_info['status'],
                    'status_name': self.get_status_name(status_info['status']),
                    'source': status_info['source'],
                    'description': status_info['description'],
                    'attendance_count': len(attendances),
                    'attendance_status': attendance_status,
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

        return sorted(report, key=lambda x: x['full_name'])


    def get_monthly_report(self, user_id: str, year: int, month: int) -> Dict:
        """
        گزارش ماهانه یک کاربر
        """
        # محاسبه بازه ماه
        j_month_start = jdatetime.date(year, month, 1)
        if month == 12:
            j_month_end = jdatetime.date(year, 12, 29 if jdatetime.JalaliCalendar.isleap(year) else 30)
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

        # گروه‌بندی بر اساس روز
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