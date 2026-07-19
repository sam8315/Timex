"""
ماژول تولید گزارش‌های جامع
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.attendance import Attendance
from core.daily_status_manager import DailyStatusManager


class ReportGenerator:
    """تولید گزارش‌های جامع"""

    def __init__(self):
        self.db: Session = SessionLocal()
        self.status_manager = DailyStatusManager()

    def close(self):
        if self.db:
            self.db.close()
        if self.status_manager:
            self.status_manager.close()

    def generate_monthly_report_for_all(
        self,
        year: int,
        month: int,
        group_id: Optional[int] = None
    ) -> List[Dict]:
        """
        گزارش ماهانه برای همه کاربران
        """
        users = self.db.query(User)
        if group_id is not None:
            users = users.filter(User.group_id == str(group_id))
        users = users.all()

        reports = []
        for user in users:
            monthly = self.status_manager.get_monthly_report(user.user_id, year, month)
            reports.append({
                'user_id': user.user_id,
                'name': user.name,
                'group_id': user.group_id,
                'present_days': monthly['status_counts'].get('P', 0),
                'absent_days': monthly['status_counts'].get('A', 0),
                'holiday_days': monthly['status_counts'].get('H', 0),
                'annual_leave': monthly['status_counts'].get('AL', 0),
                'sick_leave': monthly['status_counts'].get('SL', 0),
                'reward_leave': monthly['status_counts'].get('RL', 0),
                'unpaid_leave': monthly['status_counts'].get('UL', 0),
                'mission_days': monthly['status_counts'].get('M', 0),
                'late_days': monthly['status_counts'].get('LP', 0),
                'special_days': monthly['status_counts'].get('S', 0),
                'work_hours': monthly['total_work_hours'],
                'night_hours': monthly['total_night_hours']
            })

        return sorted(reports, key=lambda x: x['name'])

    def generate_absent_report(
        self,
        from_date: date,
        to_date: date,
        group_id: Optional[int] = None
    ) -> List[Dict]:
        """
        گزارش غیبت‌ها در یک بازه زمانی
        """
        users = self.db.query(User)
        if group_id is not None:
            users = users.filter(User.group_id == str(group_id))
        users = users.all()

        report = []
        for user in users:
            absent_dates = []
            current = from_date
            while current <= to_date:
                status_info = self.status_manager.detect_status(user.user_id, current)
                if status_info['status'] == 'A':
                    absent_dates.append(current)
                current += timedelta(days=1)

            if absent_dates:
                report.append({
                    'user_id': user.user_id,
                    'name': user.name,
                    'group_id': user.group_id,
                    'absent_count': len(absent_dates),
                    'absent_dates': absent_dates
                })

        return sorted(report, key=lambda x: x['absent_count'], reverse=True)

    def generate_leave_report(
            self,
            year: int,
            month: Optional[int] = None
    ) -> List[Dict]:
        """
        گزارش مرخصی‌ها - year: سال شمسی
        """
        from models.leave_request import LeaveRequest
        import jdatetime

        # ✅ تبدیل سال شمسی به میلادی
        j_from = jdatetime.date(year, 1, 1)
        j_to = jdatetime.date(year, 12, 29)
        g_from = j_from.togregorian()
        g_to = j_to.togregorian()

        query = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.status == 'A',
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to
            )
        )

        if month:
            # ✅ تبدیل ماه شمسی به بازه میلادی
            j_month_from = jdatetime.date(year, month, 1)
            if month == 12:
                j_month_to = jdatetime.date(year, 12, 29)
            else:
                j_month_to = jdatetime.date(year, month + 1, 1) - timedelta(days=1)

            g_month_from = j_month_from.togregorian()
            g_month_to = j_month_to.togregorian()

            query = query.filter(
                and_(
                    LeaveRequest.from_date >= g_month_from,
                    LeaveRequest.from_date <= g_month_to
                )
            )

        requests = query.all()

        # گروه‌بندی بر اساس کاربر
        user_leaves = {}
        for req in requests:
            if req.user_id not in user_leaves:
                user_leaves[req.user_id] = {
                    'AL': 0, 'SL': 0, 'RL': 0, 'UL': 0,
                    'total_days': 0, 'total_requests': 0
                }
            user_leaves[req.user_id][req.leave_type] += req.days_count
            user_leaves[req.user_id]['total_days'] += req.days_count
            user_leaves[req.user_id]['total_requests'] += 1

        report = []
        for user_id, data in user_leaves.items():
            user = self.db.query(User).filter(User.user_id == user_id).first()
            report.append({
                'user_id': user_id,
                'name': user.name if user else user_id,
                'annual_leave': data['AL'],
                'sick_leave': data['SL'],
                'reward_leave': data['RL'],
                'unpaid_leave': data['UL'],
                'total_days': data['total_days'],
                'total_requests': data['total_requests']
            })

        return sorted(report, key=lambda x: x['total_days'], reverse=True)