"""
ماژول تولید گزارش‌های جامع
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models import Employee, LeaveRequest
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
            department: Optional[str] = None
    ) -> List[Dict]:
        """گزارش ماهانه برای همه کاربران"""
        # ✅ دریافت فقط کارمندان فعال از employee
        employees_query = self.db.query(Employee).filter(Employee.is_active == True)

        if department is not None:
            employees_query = employees_query.filter(Employee.department == department)

        employees = employees_query.all()

        reports = []

        for emp in employees:
            monthly = self.status_manager.get_monthly_report(emp.user_id, year, month)

            reports.append({
                'user_id': emp.user_id,
                'full_name': emp.full_name,
                'department': emp.department or 'بدون گروه',  # ✅ اطمینان از وجود
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

        return sorted(reports, key=lambda x: (x['department'], x['full_name']))

    def generate_leave_report(self, year: int, month: int = None) -> List[Dict]:
        """تولید گزارش مرخصی‌ها با ساختار جدید (کل، استفاده شده، مانده)"""
        from models.leave_request import LeaveRequest
        from models.leave_balance import LeaveBalance
        from models.employee import Employee
        from models.contract import Contract
        from sqlalchemy import and_
        import jdatetime

        # تبدیل سال شمسی به میلادی
        j_from = jdatetime.date(year, month or 1, 1)
        if month:
            if month == 12:
                try:
                    j_to = jdatetime.date(year, 12, 30)
                except ValueError:
                    j_to = jdatetime.date(year, 12, 29)
            else:
                j_to = jdatetime.date(year, month + 1, 1) - timedelta(days=1)
        else:
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

        g_from = j_from.togregorian()
        g_to = j_to.togregorian()

        # دریافت همه کارمندان فعال
        employees = self.db.query(Employee).filter(Employee.is_active == True).all()

        reports = []
        for emp in employees:
            user_id = emp.user_id

            # ✅ دریافت مانده‌های مرخصی
            balances = self.db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year
                )
            ).all()

            balance_map = {b.leave_type: b.balance for b in balances}

            # ✅ دریافت استفاده شده در بازه
            used_requests = self.db.query(LeaveRequest).filter(
                and_(
                    LeaveRequest.user_id == user_id,
                    LeaveRequest.status == 'A',
                    LeaveRequest.from_date >= g_from,
                    LeaveRequest.from_date <= g_to
                )
            ).all()

            used_map = {'AL': 0, 'SL': 0, 'RL': 0, 'UL': 0, 'CW': 0}
            for req in used_requests:
                if req.leave_type in used_map:
                    used_map[req.leave_type] += req.days_count

            # ✅ محاسبه "کل" برای هر نوع
            # برای AL: اگر قرارداد فعال است، از قرارداد بخوان؛ در غیر این صورت از مانده + استفاده
            al_total = 0
            contract = self.db.query(Contract).filter(
                and_(
                    Contract.user_id == user_id,
                    Contract.start_date <= g_to,
                    or_(
                        Contract.end_date == None,
                        Contract.end_date >= g_from
                    )
                )
            ).order_by(Contract.start_date.desc()).first()

            if contract and contract.annual_leave_days:
                al_total = contract.annual_leave_days
            else:
                # کل = مانده + استفاده شده
                al_total = balance_map.get('AL', 0) + used_map.get('AL', 0)

            # برای سایر انواع: کل = مانده + استفاده شده
            sl_total = balance_map.get('SL', 0) + used_map.get('SL', 0)
            rl_total = balance_map.get('RL', 0) + used_map.get('RL', 0)
            ul_total = balance_map.get('UL', 0) + used_map.get('UL', 0)
            cw_total = balance_map.get('CW', 0) + used_map.get('CW', 0)

            # ✅ محاسبه کل کل
            tot_total = al_total + sl_total + rl_total + ul_total + cw_total
            tot_used = sum(used_map.values())
            tot_balance = tot_total - tot_used

            reports.append({
                'user_id': user_id,
                'full_name': emp.full_name,
                'department': emp.department or '',
                # AL
                'al_total': al_total,
                'al_used': used_map.get('AL', 0),
                'al_balance': balance_map.get('AL', 0),
                # SL
                'sl_total': sl_total,
                'sl_used': used_map.get('SL', 0),
                'sl_balance': balance_map.get('SL', 0),
                # RL
                'rl_total': rl_total,
                'rl_used': used_map.get('RL', 0),
                'rl_balance': balance_map.get('RL', 0),
                # UL
                'ul_total': ul_total,
                'ul_used': used_map.get('UL', 0),
                'ul_balance': balance_map.get('UL', 0),
                # CW
                'cw_total': cw_total,
                'cw_used': used_map.get('CW', 0),
                'cw_balance': balance_map.get('CW', 0),
                # TOT
                'tot_total': tot_total,
                'tot_used': tot_used,
                'tot_balance': tot_balance,
            })

        return sorted(reports, key=lambda x: x['full_name'])


    def generate_absent_report(
            self,
            from_date: date,
            to_date: date,
            department: Optional[str] = None
    ) -> List[Dict]:
        """
        گزارش غیبت‌ها - فقط از employee
        """
        # ✅ دریافت فقط کارمندان فعال از employee
        employees_query = self.db.query(Employee).filter(Employee.is_active == True)

        if department is not None:
            employees_query = employees_query.filter(Employee.department == department)

        employees = employees_query.all()

        report = []
        for emp in employees:
            absent_dates = []
            current = from_date
            while current <= to_date:
                status_info = self.status_manager.detect_status(emp.user_id, current)
                if status_info['status'] == 'A':
                    absent_dates.append(current)
                current += timedelta(days=1)

            if absent_dates:
                report.append({
                    'user_id': emp.user_id,
                    'full_name': emp.full_name,  # ✅ از employee
                    'department': emp.department or 'بدون گروه',  # ✅ از employee
                    'absent_count': len(absent_dates),
                    'absent_dates': absent_dates
                })

        return sorted(report, key=lambda x: x['absent_count'], reverse=True)