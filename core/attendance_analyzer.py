"""
ماژول تحلیل و بررسی ترددهای ناقص
"""
from datetime import datetime, date
from typing import List, Dict, Optional
from sqlalchemy import func, and_, case
from sqlalchemy.orm import Session
import jdatetime

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
        if not from_date:
            from_date = date(to_date.year, to_date.month, 1)

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

    def get_user_attendance_detail(self, user_id: str, target_date: date) -> Dict:
        """
        دریافت جزئیات تردد یک کاربر در یک روز خاص
        """
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'error': 'کاربر یافت نشد'}

        records = self.db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == target_date
            )
        ).order_by(Attendance.timestamp).all()

        enters = [r for r in records if r.punch == 0]
        exits = [r for r in records if r.punch == 1]

        return {
            'user': {'user_id': user.user_id, 'name': user.name},
            'date': target_date,
            'enters': [{'time': r.timestamp, 'status': r.status} for r in enters],
            'exits': [{'time': r.timestamp, 'status': r.status} for r in exits],
            'enter_count': len(enters),
            'exit_count': len(exits),
            'is_complete': len(enters) == len(exits) and len(enters) > 0
        }