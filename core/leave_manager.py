"""
ماژول مدیریت مانده مرخصی و تراکنش‌ها
- شارژ مرخصی توسط مدیر (استعلاجی، تشویقی، بدون حقوق)
- انتقال مانده از سال قبل
- مشاهده مانده مرخصی
"""
from datetime import date
from typing import List, Dict, Optional
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_request import LeaveRequest


class LeaveManager:
    """مدیریت مانده مرخصی و تراکنش‌ها"""

    # انواع مرخصی
    LEAVE_TYPES = {
        'AL': 'استحقاقی',
        'SL': 'استعلاجی',
        'RL': 'تشویقی',
        'UL': 'بدون حقوق',
        'CW': 'ذخیره سال قبل'
    }

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def get_leave_type_name(self, code: str) -> str:
        """دریافت نام فارسی نوع مرخصی"""
        return self.LEAVE_TYPES.get(code, f'نامشخص ({code})')

    def get_balance(self, user_id: str, year: int, leave_type: str) -> int:
        """دریافت مانده مرخصی"""
        balance = self.db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        return balance.balance if balance else 0

    def get_all_balances(self, user_id: str, year: int) -> Dict:
        """دریافت تمام مانده‌های مرخصی یک کاربر - year: سال شمسی"""
        # ✅ سال شمسی و میلادی یکی هستند برای leave_balances
        # چون سال فقط یک عدد است و تبدیل نیاز ندارد
        balances = self.db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year
            )
        ).all()

        result = {}
        for b in balances:
            result[b.leave_type] = {
                'balance': b.balance,
                'name': self.get_leave_type_name(b.leave_type)
            }

        # اضافه کردن انواع مرخصی که مانده ندارند
        for code in self.LEAVE_TYPES:
            if code not in result:
                result[code] = {
                    'balance': 0,
                    'name': self.get_leave_type_name(code)
                }

        return result
    def credit_leave(
            self,
            user_id: str,
            year: int,
            leave_type: str,
            amount: int,
            transaction_type: str,
            description: str = ""
    ) -> Dict:
        """
        شارژ مرخصی

        Args:
            user_id: کد پرسنلی
            year: سال
            leave_type: نوع مرخصی (SL, RL, UL, CW)
            amount: تعداد روز
            transaction_type: نوع تراکنش (CREDIT, CARRYOVER)
            description: توضیحات
        """
        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'❌ کاربر {user_id} یافت نشد'}

        # بررسی نوع مرخصی
        if leave_type not in self.LEAVE_TYPES:
            return {'success': False, 'message': f'❌ نوع مرخصی نامعتبر: {leave_type}'}

        # استحقاقی نباید از اینجا شارژ شود
        if leave_type == 'AL':
            return {
                'success': False,
                'message': '❌ مرخصی استحقاقی باید از طریق قرارداد شارژ شود'
            }

        try:
            # به‌روزرسانی یا ایجاد مانده
            balance = self.db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year,
                    LeaveBalance.leave_type == leave_type
                )
            ).first()

            if balance:
                balance.balance += amount
            else:
                balance = LeaveBalance(
                    user_id=user_id,
                    year=year,
                    leave_type=leave_type,
                    balance=amount
                )
                self.db.add(balance)

            # ثبت تراکنش
            transaction = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=amount,
                transaction_type=transaction_type,
                description=description
            )
            self.db.add(transaction)

            self.db.commit()

            type_name = self.get_leave_type_name(leave_type)
            new_balance = balance.balance

            return {
                'success': True,
                'message': f'✅ {amount} روز مرخصی {type_name} شارژ شد. مانده جدید: {new_balance} روز'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def debit_leave(
            self,
            user_id: str,
            year: int,
            leave_type: str,
            amount: int,
            description: str = "",
            reference_id: Optional[int] = None
    ) -> Dict:
        """برداشت مرخصی (هنگام تایید درخواست)"""
        balance = self.db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        if not balance or balance.balance < amount:
            current = balance.balance if balance else 0
            return {
                'success': False,
                'message': f'❌ مانده کافی نیست. موجودی: {current} روز، درخواست: {amount} روز'
            }

        try:
            balance.balance -= amount

            transaction = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=-amount,  # منفی برای برداشت
                transaction_type='DEBIT',
                description=description,
                reference_id=reference_id
            )
            self.db.add(transaction)

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ {amount} روز مرخصی {self.get_leave_type_name(leave_type)} کسر شد. مانده: {balance.balance}'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def carryover_to_new_year(self, from_year: int, to_year: int, user_id: Optional[str] = None) -> Dict:
        """
        انتقال مانده مرخصی از سال قبل به سال جدید

        فقط مرخصی استحقاقی و ذخیره سال قبل منتقل می‌شوند
        """
        # دریافت کاربران
        if user_id:
            users = self.db.query(User).filter(User.user_id == user_id).all()
        else:
            users = self.db.query(User).all()

        stats = {'total': 0, 'success': 0, 'failed': 0, 'no_balance': 0}

        for user in users:
            stats['total'] += 1

            # دریافت مانده استحقاقی سال قبل
            al_balance = self.get_balance(user.user_id, from_year, 'AL')
            cw_balance = self.get_balance(user.user_id, from_year, 'CW')
            total_carry = al_balance + cw_balance

            if total_carry <= 0:
                stats['no_balance'] += 1
                continue

            # انتقال به سال جدید به عنوان CW (ذخیره سال قبل)
            result = self.credit_leave(
                user_id=user.user_id,
                year=to_year,
                leave_type='CW',
                amount=total_carry,
                transaction_type='CARRYOVER',
                description=f'انتقال از سال {from_year} (استحقاقی: {al_balance}، ذخیره: {cw_balance})'
            )

            if result['success']:
                stats['success'] += 1
            else:
                stats['failed'] += 1

        return stats

    def get_transactions(
            self,
            user_id: str,
            year: int,
            leave_type: Optional[str] = None
    ) -> List[LeaveTransaction]:
        """دریافت تراکنش‌های مرخصی - year: سال شمسی"""
        # ✅ سال شمسی و میلادی یکی هستند برای leave_transactions
        query = self.db.query(LeaveTransaction).filter(
            and_(
                LeaveTransaction.user_id == user_id,
                LeaveTransaction.year == year
            )
        )

        if leave_type:
            query = query.filter(LeaveTransaction.leave_type == leave_type)

        return query.order_by(LeaveTransaction.created_at.desc()).all()

    def get_summary_for_user(self, user_id: str, year: int) -> Dict:
        """خلاصه وضعیت مرخصی یک کاربر"""
        balances = self.get_all_balances(user_id, year)

        # دریافت درخواست‌های تایید شده
        approved_requests = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status == 'A',
                func.extract('year', LeaveRequest.from_date) == year
            )
        ).all()

        used_by_type = {}
        for req in approved_requests:
            if req.leave_type not in used_by_type:
                used_by_type[req.leave_type] = 0
            used_by_type[req.leave_type] += req.days_count

        return {
            'balances': balances,
            'used': used_by_type,
            'approved_requests_count': len(approved_requests)
        }