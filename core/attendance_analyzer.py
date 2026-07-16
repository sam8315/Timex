"""
ماژول تحلیل و بررسی ترددهای ناقص
"""
from datetime import datetime, date
from typing import List, Dict, Optional
from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session
from jdatetime import date as jdate

from database.engine import SessionLocal
from models.user import User
from models.attendance import Attendance


class AttendanceAnalyzer:
    """تحلیل‌گر ترددها برای شناسایی موارد ناقص"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        """بستن اتصال دیتابیس"""
        if self.db:
            self.db.close()

    def get_incomplete_attendances(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None
    ) -> List[Dict]:
        """
        شناسایی ترددهای ناقص (ورود بدون خروج یا خروج بدون ورود)

        Returns:
            List[Dict]: لیست ترددهای ناقص با اطلاعات کاربر و تاریخ
        """
        # اگر تاریخ مشخص نشده، 30 روز اخیر
        if not to_date:
            to_date = date.today()
        if not from_date:
            from_date = date(to_date.year, to_date.month, 1)

        # کوئری: برای هر کاربر در هر روز، تعداد ورود و خروج را بشمار
        query = self.db.query(
            User.user_id,
            User.name,
            func.date(Attendance.timestamp).label('attendance_date'),
            func.sum(case((Attendance.punch == 0, 1), else_=0)).label('enter_count'),
            func.sum(case((Attendance.punch == 1, 1), else_=0)).label('exit_count'),
            func.min(case((Attendance.punch == 0, Attendance.timestamp))).label('first_enter'),
            func.max(case((Attendance.punch == 1, Attendance.timestamp))).label('last_exit')
        ).join(
            User, Attendance.user_id == User.user_id
        ).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).group_by(
            User.user_id,
            User.name,
            func.date(Attendance.timestamp)
        ).order_by(
            func.date(Attendance.timestamp).desc(),
            User.name
        )

        results = []
        for row in query:
            # شناسایی موارد ناقص
            if row.enter_count == 0 and row.exit_count > 0:
                # فقط خروج دارد (ورود فراموش شده)
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '❌ خروج بدون ورود',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': None,
                    'last_exit': row.last_exit,
                    'issue': 'missing_enter'
                })
            elif row.enter_count > 0 and row.exit_count == 0:
                # فقط ورود دارد (خروج فراموش شده)
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '⚠️  ورود بدون خروج',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': row.first_enter,
                    'last_exit': None,
                    'issue': 'missing_exit'
                })
            elif row.enter_count != row.exit_count:
                # عدم تعادل بین ورود و خروج
                results.append({
                    'user_id': row.user_id,
                    'name': row.name,
                    'date': row.attendance_date,
                    'type': '🔄 عدم تعادل ورود/خروج',
                    'enter_count': row.enter_count,
                    'exit_count': row.exit_count,
                    'first_enter': row.first_enter,
                    'last_exit': row.last_exit,
                    'issue': 'imbalance'
                })

        return results

    def get_summary_statistics(self, from_date: Optional[date] = None, to_date: Optional[date] = None) -> Dict:
        """
        دریافت آمار کلی ترددها در بازه زمانی
        """
        if not to_date:
            to_date = date.today()

        today_jalali = jdate.fromgregorian(date=to_date)
        first_day_jalali = jdate(today_jalali.year, today_jalali.month, 1)
        if not from_date:
            # from_date = date(to_date.year, to_date.month, 1)
            from_date = first_day_jalali.togregorian()

        # کل رکوردها
        total_records = self.db.query(Attendance).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).count()

        # تعداد ورود و خروج
        enter_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 0,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).count()

        exit_count = self.db.query(Attendance).filter(
            and_(
                Attendance.punch == 1,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).count()

        # تعداد کاربران منحصر به فرد
        unique_users = self.db.query(func.count(func.distinct(Attendance.user_id))).filter(
            and_(
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).scalar()

        # تعداد ترددهای ناقص
        incomplete = self.get_incomplete_attendances(from_date, to_date)

        return {
            'total_records': total_records,
            'enter_count': enter_count,
            'exit_count': exit_count,
            'unique_users': unique_users,
            'incomplete_count': len(incomplete),
            'from_date': from_date,
            'to_date': to_date
        }

    def get_user_attendance_range(
            self,
            user_id: str,
            from_date: date,
            to_date: date
    ) -> Dict:
        """
        دریافت جزئیات تردد یک کاربر در یک بازه زمانی

        Returns:
            Dict: شامل اطلاعات کاربر و لیست روزانه
        """
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'error': 'کاربر یافت نشد'}

        # کوئری: گروه‌بندی بر اساس روز
        query = self.db.query(
            func.date(Attendance.timestamp).label('attendance_date'),
            func.sum(case((Attendance.punch == 0, 1), else_=0)).label('enter_count'),
            func.sum(case((Attendance.punch == 1, 1), else_=0)).label('exit_count'),
            func.min(case((Attendance.punch == 0, Attendance.timestamp))).label('first_enter'),
            func.max(case((Attendance.punch == 1, Attendance.timestamp))).label('last_exit')
        ).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) >= from_date,
                func.date(Attendance.timestamp) <= to_date
            )
        ).group_by(
            func.date(Attendance.timestamp)
        ).order_by(
            func.date(Attendance.timestamp).desc()
        )

        days = []
        for row in query:
            is_complete = row.enter_count > 0 and row.exit_count > 0 and row.enter_count == row.exit_count

            # محاسبه ساعات کاری (اگر کامل باشد)
            work_hours = None
            if row.first_enter and row.last_exit:
                delta = row.last_exit - row.first_enter
                work_hours = delta.total_seconds() / 3600

            days.append({
                'date': row.attendance_date,
                'first_enter': row.first_enter,
                'last_exit': row.last_exit,
                'enter_count': row.enter_count,
                'exit_count': row.exit_count,
                'is_complete': is_complete,
                'work_hours': work_hours
            })

        # محاسبه آمار کلی
        total_days = len(days)
        complete_days = sum(1 for d in days if d['is_complete'])
        incomplete_days = total_days - complete_days
        total_work_hours = sum(d['work_hours'] or 0 for d in days)

        return {
            'user': {'user_id': user.user_id, 'name': user.name},
            'from_date': from_date,
            'to_date': to_date,
            'days': days,
            'summary': {
                'total_days': total_days,
                'complete_days': complete_days,
                'incomplete_days': incomplete_days,
                'total_work_hours': total_work_hours
            }
        }