"""
ماژول مدیریت قراردادها و محاسبه مرخصی استحقاقی
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction


class ContractManager:
    """مدیریت قراردادها و محاسبه مرخصی"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def add_contract(
            self,
            user_id: str,
            contract_type: str,
            start_date: date,
            end_date: Optional[date],
            annual_leave: int,
            sick_leave: int,
            reward_leave: int,
            unpaid_leave: int,
            description: str = ""
    ) -> Dict:
        """افزودن قرارداد جدید"""
        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'❌ کاربر {user_id} یافت نشد'}

        # بررسی تداخل زمانی با قراردادهای قبلی
        overlapping = self.db.query(Contract).filter(
            and_(
                Contract.user_id == user_id,
                or_(
                    and_(
                        Contract.start_date <= start_date,
                        or_(Contract.end_date == None, Contract.end_date >= start_date)
                    ),
                    and_(
                        end_date != None,
                        Contract.start_date <= end_date,
                        or_(Contract.end_date == None, Contract.end_date >= end_date)
                    )
                )
            )
        ).first()

        if overlapping:
            return {
                'success': False,
                'message': f'❌ تداخل زمانی با قرارداد موجود (شروع: {overlapping.start_date})'
            }

        try:
            contract = Contract(
                user_id=user_id,
                contract_type=contract_type,
                start_date=start_date,
                end_date=end_date,
                annual_leave_days=annual_leave,
                sick_leave_days=sick_leave,
                reward_leave_days=reward_leave,
                unpaid_leave_days=unpaid_leave,
                description=description
            )
            self.db.add(contract)
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ قرارداد با موفقیت ایجاد شد (ID: {contract.id})',
                'contract_id': contract.id
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_active_contract(self, user_id: str, target_date: Optional[date] = None) -> Optional[Contract]:
        """
        دریافت قرارداد فعال یک کاربر در تاریخ مشخص
        target_date: تاریخ میلادی
        """
        if not target_date:
            target_date = date.today()

        contract = self.db.query(Contract).filter(
            and_(
                Contract.user_id == user_id,
                Contract.start_date <= target_date,
                or_(
                    Contract.end_date == None,
                    Contract.end_date >= target_date
                )
            )
        ).order_by(Contract.start_date.desc()).first()

        return contract
    def get_user_contracts(self, user_id: str) -> List[Contract]:
        """دریافت تمام قراردادهای یک کاربر"""
        return self.db.query(Contract).filter(
            Contract.user_id == user_id
        ).order_by(Contract.start_date.desc()).all()

    def initialize_yearly_balances(self, user_id: str, year: int) -> Dict:
        """
        شارژ اولیه مرخصی استحقاقی بر اساس قرارداد برای یک سال
        year: سال شمسی
        """
        import jdatetime

        # ✅ تبدیل سال شمسی به تاریخ میلادی ابتدای سال
        try:
            j_year_start = jdatetime.date(year, 1, 1)
            g_year_start = j_year_start.togregorian()
        except Exception as e:
            return {'success': False, 'message': f'❌ خطا در تبدیل تاریخ: {e}'}

        # دریافت قرارداد فعال در ابتدای سال شمسی
        contract = self.get_active_contract(user_id, g_year_start)

        if not contract:
            return {'success': False, 'message': f'❌ قراردادی برای سال شمسی {year} یافت نشد'}

        # بررسی اینکه آیا قبلاً شارژ شده یا نه
        existing = self.db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,  # ✅ سال شمسی در leave_balances
                LeaveBalance.leave_type == 'AL'
            )
        ).first()

        if existing:
            return {
                'success': False,
                'message': f'⚠️ مرخصی استحقاقی سال شمسی {year} قبلاً شارژ شده ({existing.balance} روز)'
            }

        try:
            # ایجاد مانده مرخصی استحقاقی
            balance = LeaveBalance(
                user_id=user_id,
                year=year,  # ✅ سال شمسی
                leave_type='AL',
                balance=contract.annual_leave_days
            )
            self.db.add(balance)

            # ثبت تراکنش
            transaction = LeaveTransaction(
                user_id=user_id,
                year=year,  # ✅ سال شمسی
                leave_type='AL',
                amount=contract.annual_leave_days,
                transaction_type='INITIAL',
                description=f'شارژ اولیه استحقاقی بر اساس قرارداد ({contract.contract_type})'
            )
            self.db.add(transaction)

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ مرخصی استحقاقی سال شمسی {year} شارژ شد: {contract.annual_leave_days} روز'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}
    def initialize_all_users_for_year(self, year: int) -> Dict:
        """
        شارژ مرخصی استحقاقی همه کاربران برای یک سال
        year: سال شمسی
        """
        users = self.db.query(User).all()
        stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}

        for user in users:
            stats['total'] += 1
            result = self.initialize_yearly_balances(user.user_id, year)
            if result['success']:
                stats['success'] += 1
            elif 'قبلاً شارژ شده' in result['message']:
                stats['skipped'] += 1
            else:
                stats['failed'] += 1

        return stats
    def get_contract_summary(self) -> Dict:
        """خلاصه آماری قراردادها"""
        total_contracts = self.db.query(Contract).count()
        active_contracts = self.db.query(Contract).filter(
            and_(
                Contract.start_date <= date.today(),
                or_(
                    Contract.end_date == None,
                    Contract.end_date >= date.today()
                )
            )
        ).count()

        users_with_contract = self.db.query(Contract.user_id).distinct().count()
        users_without_contract = self.db.query(User).filter(
            ~User.user_id.in_(self.db.query(Contract.user_id))
        ).count()

        return {
            'total_contracts': total_contracts,
            'active_contracts': active_contracts,
            'users_with_contract': users_with_contract,
            'users_without_contract': users_without_contract
        }

    def get_all_contracts(self) -> List[Dict]:
        """دریافت تمام قراردادها با اطلاعات کاربر"""
        from core.employee_manager import EmployeeManager

        contracts = self.db.query(Contract).order_by(
            Contract.start_date.desc()
        ).all()

        emp_manager = EmployeeManager()
        result = []

        try:
            for c in contracts:
                user = self.db.query(User).filter(User.user_id == c.user_id).first()
                full_name = emp_manager.get_full_name(c.user_id)

                # بررسی فعال بودن
                is_active = (
                        c.start_date <= date.today() and
                        (c.end_date is None or c.end_date >= date.today())
                )

                # محاسبه روزهای باقی‌مانده
                days_remaining = None
                if c.end_date:
                    delta = c.end_date - date.today()
                    days_remaining = delta.days if delta.days >= 0 else 0

                result.append({
                    'contract': c,
                    'user_id': c.user_id,
                    'full_name': full_name,
                    'user_name': user.name if user else c.user_id,
                    'is_active': is_active,
                    'days_remaining': days_remaining
                })
        finally:
            emp_manager.close()

        return result

    def update_contract(self, contract_id: int, **kwargs) -> Dict:
        """به‌روزرسانی قرارداد"""
        contract = self.db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            return {'success': False, 'message': '❌ قرارداد یافت نشد'}

        try:
            for key, value in kwargs.items():
                if hasattr(contract, key) and key not in ['id', 'user_id', 'created_at']:
                    setattr(contract, key, value)

            self.db.commit()
            return {'success': True, 'message': '✅ قرارداد با موفقیت به‌روز شد'}

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_expiring_contracts(self, days_threshold: int = 30) -> List[Dict]:
        """
        دریافت قراردادهای نزدیک به پایان

        Args:
            days_threshold: تعداد روز برای هشدار (پیش‌فرض: 30 روز)
        """
        from core.employee_manager import EmployeeManager

        today = date.today()
        threshold_date = today + timedelta(days=days_threshold)

        contracts = self.db.query(Contract).filter(
            and_(
                Contract.end_date != None,
                Contract.end_date >= today,
                Contract.end_date <= threshold_date
            )
        ).order_by(Contract.end_date.asc()).all()

        emp_manager = EmployeeManager()
        result = []

        try:
            for c in contracts:
                full_name = emp_manager.get_full_name(c.user_id)
                delta = c.end_date - today

                result.append({
                    'contract': c,
                    'user_id': c.user_id,
                    'full_name': full_name,
                    'end_date': c.end_date,
                    'days_remaining': delta.days
                })
        finally:
            emp_manager.close()

        return result