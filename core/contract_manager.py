"""
ماژول مدیریت قراردادها و محاسبه مرخصی استحقاقی
"""
from datetime import date
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
        """دریافت قرارداد فعال یک کاربر در تاریخ مشخص"""
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

        این تابع باید در ابتدای هر سال یا هنگام ایجاد قرارداد جدید اجرا شود
        """
        # دریافت قرارداد فعال در ابتدای سال
        year_start = date(year, 1, 1)
        contract = self.get_active_contract(user_id, year_start)

        if not contract:
            return {'success': False, 'message': f'❌ قراردادی برای سال {year} یافت نشد'}

        # بررسی اینکه آیا قبلاً شارژ شده یا نه
        existing = self.db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == 'AL'
            )
        ).first()

        if existing:
            return {
                'success': False,
                'message': f'⚠️ مرخصی استحقاقی سال {year} قبلاً شارژ شده ({existing.balance} روز)'
            }

        try:
            # ایجاد مانده مرخصی استحقاقی
            balance = LeaveBalance(
                user_id=user_id,
                year=year,
                leave_type='AL',
                balance=contract.annual_leave_days
            )
            self.db.add(balance)

            # ثبت تراکنش
            transaction = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type='AL',
                amount=contract.annual_leave_days,
                transaction_type='INITIAL',
                description=f'شارژ اولیه استحقاقی بر اساس قرارداد ({contract.contract_type})'
            )
            self.db.add(transaction)

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ مرخصی استحقاقی سال {year} شارژ شد: {contract.annual_leave_days} روز'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def initialize_all_users_for_year(self, year: int) -> Dict:
        """شارژ مرخصی استحقاقی همه کاربران برای یک سال"""
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