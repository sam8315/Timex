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
        """افزودن قرارداد جدید با شارژ خودکار مرخصی"""
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
            self.db.flush()  # برای دریافت ID

            # ✅ شارژ خودکار مرخصی
            charge_result = self._charge_leave_for_contract(contract)

            self.db.commit()

            message = f'✅ قرارداد با موفقیت ایجاد شد (ID: {contract.id})'
            if charge_result['success']:
                message += f'\n{charge_result["message"]}'

            return {
                'success': True,
                'message': message,
                'contract_id': contract.id,
                'charge_result': charge_result
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

    def initialize_yearly_balances(
            self,
            user_id: str,
            year: int,
            force_reset: bool = False
    ) -> Dict:
        """
        شارژ مرخصی استحقاقی از قراردادها با جلوگیری از شارژ مضاعف

        منطق:
        1. محاسبه کل استحقاق بر اساس همه قراردادهای بازه
        2. بررسی تراکنش‌های قبلی با نوع CONTRACT برای یافتن مقدار شارژ شده
        3. شارژ فقط مقدار تفاضل (Delta)

        Args:
            user_id: کد پرسنلی
            year: سال شمسی
            force_reset: اگر True باشد، شارژ قبلی حذف و با مقدار جدید جایگزین می‌شود
        """
        from models.leave_balance import LeaveBalance
        from models.leave_transaction import LeaveTransaction
        from sqlalchemy import and_, func

        # ۱. محاسبه کل استحقاق از همه قراردادهای بازه
        calc = self.calculate_yearly_leave(user_id, year)
        if not calc['success']:
            return calc

        total_expected = calc['total_annual']

        try:
            # ۲. بررسی مقدار شارژ شده قبلی از طریق قرارداد
            already_charged = self.db.query(func.sum(LeaveTransaction.amount)).filter(
                and_(
                    LeaveTransaction.user_id == user_id,
                    LeaveTransaction.year == year,
                    LeaveTransaction.leave_type == 'AL',
                    LeaveTransaction.transaction_type == 'INITIAL'
                )
            ).scalar() or 0

            # ۳. محاسبه مقدار باقیمانده برای شارژ
            amount_to_charge = total_expected - already_charged

            # اگر قبلاً کامل شارژ شده است
            if amount_to_charge <= 0 and not force_reset:
                current_balance = self.db.query(LeaveBalance).filter(
                    and_(
                        LeaveBalance.user_id == user_id,
                        LeaveBalance.year == year,
                        LeaveBalance.leave_type == 'AL'
                    )
                ).first()

                current_amount = current_balance.balance if current_balance else 0

                return {
                    'success': True,
                    'message': f'✅ این کاربر قبلاً به طور کامل شارژ شده است. (کل استحقاق: {total_expected}، شارژ شده: {already_charged})',
                    'already_charged': True,
                    'current_balance': current_amount,
                    'new_amount': 0
                }

            # ۴. اگر force_reset باشد، ابتدا مانده و تراکنش‌های قبلی را صفر می‌کنیم
            if force_reset and already_charged > 0:
                # حذف تراکنش‌های CONTRACT قبلی
                self.db.query(LeaveTransaction).filter(
                    and_(
                        LeaveTransaction.user_id == user_id,
                        LeaveTransaction.year == year,
                        LeaveTransaction.leave_type == 'AL',
                        LeaveTransaction.transaction_type == 'INITIAL'
                    )
                ).delete(synchronize_session=False)

                # صفر کردن مانده AL
                balance = self.db.query(LeaveBalance).filter(
                    and_(
                        LeaveBalance.user_id == user_id,
                        LeaveBalance.year == year,
                        LeaveBalance.leave_type == 'AL'
                    )
                ).first()
                if balance:
                    balance.balance = 0
                else:
                    balance = LeaveBalance(
                        user_id=user_id,
                        year=year,
                        leave_type='AL',
                        balance=0
                    )
                    self.db.add(balance)

                self.db.flush()
                already_charged = 0
                amount_to_charge = total_expected

            # ۵. شارژ مقدار باقیمانده از طریق متد اختصاصی
            if amount_to_charge > 0:
                result = self.credit_annual_leave(
                    user_id=user_id,
                    year=year,
                    amount=amount_to_charge,
                    description=f'شارژ استحقاقی از قرارداد (کل: {total_expected}، قبلاً شارژ: {already_charged})'
                )

                if not result['success']:
                    return result

                new_balance = result['new_balance']
            else:
                # اگر amount_to_charge == 0 و force_reset بود، مانده صفر است
                balance = self.db.query(LeaveBalance).filter(
                    and_(
                        LeaveBalance.user_id == user_id,
                        LeaveBalance.year == year,
                        LeaveBalance.leave_type == 'AL'
                    )
                ).first()
                new_balance = balance.balance if balance else 0

            # ۶. شارژ سایر انواع مرخصی (SL, RL) - فقط اگر force_reset باشد یا قبلاً شارژ نشده
            from core.leave_manager import LeaveManager
            lm = LeaveManager()
            try:
                for leave_type, amount in [
                    ('SL', calc['total_sick']),
                    ('RL', calc['total_reward']),
                ]:
                    if amount > 0:
                        # بررسی آیا قبلاً شارژ شده
                        existing = self.db.query(func.sum(LeaveTransaction.amount)).filter(
                            and_(
                                LeaveTransaction.user_id == user_id,
                                LeaveTransaction.year == year,
                                LeaveTransaction.leave_type == leave_type,
                                LeaveTransaction.transaction_type == 'CONTRACT'
                            )
                        ).scalar() or 0

                        remaining = amount - existing
                        if remaining > 0:
                            lm.credit_leave(
                                user_id=user_id,
                                year=year,
                                leave_type=leave_type,
                                amount=remaining,
                                transaction_type='CONTRACT',
                                description=f'شارژ {leave_type} از قرارداد (کل: {amount}، قبلاً: {existing})'
                            )
            finally:
                lm.close()

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ {amount_to_charge} روز به مانده اضافه شد. (کل استحقاق: {total_expected}، مانده جدید: {new_balance})',
                'new_amount': amount_to_charge,
                'current_balance': new_balance,
                'already_charged': False,
                'previous_charged': already_charged
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در شارژ: {e}'}


    def initialize_all_users_for_year(self, year: int, force_reset: bool = False) -> Dict:
        """شارژ همه کاربران برای یک سال"""
        from models.employee import Employee

        employees = self.db.query(Employee).filter(
            Employee.is_active == True
        ).all()

        stats = {
            'total': len(employees),
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'reset': 0
        }

        for emp in employees:
            result = self.initialize_yearly_balances(emp.user_id, year, force_reset=force_reset)

            if result.get('success'):
                if force_reset and result.get('previous_balance', 0) != 0:
                    stats['reset'] += 1
                stats['success'] += 1
            elif result.get('already_charged'):
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
        """به‌روزرسانی قرارداد با تنظیم خودکار مرخصی"""
        contract = self.db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            return {'success': False, 'message': '❌ قرارداد یافت نشد'}

        try:
            # ✅ محاسبه تفاوت مقادیر مرخصی
            old_annual = contract.annual_leave_days
            old_sick = contract.sick_leave_days
            old_reward = contract.reward_leave_days

            # به‌روزرسانی فیلدها
            for key, value in kwargs.items():
                if hasattr(contract, key) and key not in ['id', 'user_id', 'created_at']:
                    setattr(contract, key, value)

            self.db.flush()

            # ✅ محاسبه تفاوت و تنظیم مرخصی
            years = self._get_years_for_contract(contract)
            adjustments = []

            # تفاوت AL
            if 'annual_leave_days' in kwargs:
                new_annual = contract.annual_leave_days
                diff = new_annual - old_annual
                if diff != 0:
                    for year in years:
                        result = self.credit_annual_leave(
                            user_id=contract.user_id,
                            year=year,
                            amount=diff,
                            description=f'تنظیم به دلیل ویرایش قرارداد (ID: {contract.id}, تفاوت: {diff:+d})'
                        )
                        adjustments.append({'year': year, 'type': 'AL', 'diff': diff, 'result': result})

            # تفاوت SL
            if 'sick_leave_days' in kwargs:
                new_sick = contract.sick_leave_days
                diff = new_sick - old_sick
                if diff != 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        for year in years:
                            result = lm.credit_leave(
                                user_id=contract.user_id,
                                year=year,
                                leave_type='SL',
                                amount=diff,
                                transaction_type='CONTRACT',
                                description=f'تنظیم استعلاجی به دلیل ویرایش قرارداد (تفاوت: {diff:+d})'
                            )
                            adjustments.append({'year': year, 'type': 'SL', 'diff': diff, 'result': result})
                    finally:
                        lm.close()

            # تفاوت RL
            if 'reward_leave_days' in kwargs:
                new_reward = contract.reward_leave_days
                diff = new_reward - old_reward
                if diff != 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        for year in years:
                            result = lm.credit_leave(
                                user_id=contract.user_id,
                                year=year,
                                leave_type='RL',
                                amount=diff,
                                transaction_type='CONTRACT',
                                description=f'تنظیم تشویقی به دلیل ویرایش قرارداد (تفاوت: {diff:+d})'
                            )
                            adjustments.append({'year': year, 'type': 'RL', 'diff': diff, 'result': result})
                    finally:
                        lm.close()

            self.db.commit()

            message = '✅ قرارداد با موفقیت به‌روز شد'
            if adjustments:
                message += f'\n🔄 {len(adjustments)} تنظیم مرخصی انجام شد'

            return {
                'success': True,
                'message': message,
                'adjustments': adjustments
            }
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

    def get_contracts_in_year(self, user_id: str, year: int) -> List[Dict]:
        """
        دریافت تمام قراردادهای یک کاربر که در طول سال فعال بوده‌اند
        year: سال شمسی

        Returns:
            List[Dict]: لیست اطلاعات قراردادها با بازه فعال در سال
        """
        import jdatetime

        # تبدیل سال شمسی به بازه میلادی
        j_year_start = jdatetime.date(year, 1, 1)
        j_year_end = jdatetime.date(year, 12, 29)
        g_year_start = j_year_start.togregorian()
        g_year_end = j_year_end.togregorian()

        # دریافت تمام قراردادهایی که با سال همپوشانی دارند
        contracts = self.db.query(Contract).filter(
            and_(
                Contract.user_id == user_id,
                Contract.start_date <= g_year_end,
                or_(
                    Contract.end_date == None,
                    Contract.end_date >= g_year_start
                )
            )
        ).order_by(Contract.start_date).all()

        result = []
        for c in contracts:
            # محاسبه بازه فعال در سال
            effective_start = max(c.start_date, g_year_start)
            effective_end = c.end_date if c.end_date else g_year_end
            effective_end = min(effective_end, g_year_end)

            # محاسبه تعداد روزهای فعال
            total_days = (effective_end - effective_start).days + 1

            result.append({
                'contract': c,
                'effective_start': effective_start,
                'effective_end': effective_end,
                'days_in_year': total_days
            })

        return result

    def calculate_yearly_leave(self, user_id: str, year: int) -> Dict:
        """
        محاسبه مرخصی سالانه بر اساس جمع مقادیر تمام قراردادهای سال
        year: سال شمسی
        """
        import jdatetime

        contracts_info = self.get_contracts_in_year(user_id, year)

        if not contracts_info:
            return {
                'success': False,
                'message': f'❌ قراردادی برای سال شمسی {year} یافت نشد',
                'contracts': []
            }

        # ✅ جمع ساده مقادیر هر قرارداد
        total_annual = 0
        total_sick = 0
        total_reward = 0
        total_unpaid = 0

        details = []
        for info in contracts_info:
            c = info['contract']

            total_annual += c.annual_leave_days
            total_sick += c.sick_leave_days
            total_reward += c.reward_leave_days
            total_unpaid += c.unpaid_leave_days

            details.append({
                'contract_id': c.id,
                'contract_type': c.contract_type,
                'start_date': info['effective_start'],
                'end_date': info['effective_end'],
                'annual': c.annual_leave_days,
                'sick': c.sick_leave_days,
                'reward': c.reward_leave_days,
                'unpaid': c.unpaid_leave_days
            })

        return {
            'success': True,
            'year': year,
            'total_annual': total_annual,
            'total_sick': total_sick,
            'total_reward': total_reward,
            'total_unpaid': total_unpaid,
            'contracts': details,
            'contracts_count': len(details)
        }

    def credit_annual_leave(
        self,
        user_id: str,
        year: int,
        amount: int,
        description: str = ""
    ) -> Dict:
        """
        شارژ مرخصی استحقاقی (AL) از طریق قرارداد
        مانده موجود را حفظ کرده و مقدار جدید را به آن اضافه می‌کند
        """
        from models.leave_balance import LeaveBalance
        from models.leave_transaction import LeaveTransaction
        from sqlalchemy import and_

        try:
            # دریافت یا ایجاد مانده
            balance = self.db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == user_id,
                    LeaveBalance.year == year,
                    LeaveBalance.leave_type == 'AL'
                )
            ).first()

            old_balance = balance.balance if balance else 0

            if balance:
                balance.balance += amount  # ✅ جمع با مانده موجود
            else:
                balance = LeaveBalance(
                    user_id=user_id,
                    year=year,
                    leave_type='AL',
                    balance=amount
                )
                self.db.add(balance)

            # ثبت تراکنش
            transaction = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type='AL',
                amount=amount,
                transaction_type='CONTRACT',  # ✅ 8 کاراکتر
                description=description
            )
            self.db.add(transaction)
            self.db.commit()

            new_balance = balance.balance
            return {
                'success': True,
                'message': f'✅ {amount} روز استحقاقی شارژ شد. مانده قبلی: {old_balance} → مانده جدید: {new_balance}',
                'old_balance': old_balance,
                'new_balance': new_balance
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def _get_years_for_contract(self, contract: 'Contract') -> List[int]:
        """دریافت لیست سال‌های شمسی که قرارداد در آن‌ها فعال است"""
        import jdatetime
        years = []

        # سال شروع (شمسی)
        j_start = jdatetime.date.fromgregorian(date=contract.start_date)
        start_year = j_start.year

        # سال پایان (شمسی)
        if contract.end_date:
            j_end = jdatetime.date.fromgregorian(date=contract.end_date)
            end_year = j_end.year
        else:
            # اگر پایان ندارد، فقط سال شروع
            end_year = start_year

        for year in range(start_year, end_year + 1):
            years.append(year)

        return years

    def _charge_leave_for_contract(self, contract: 'Contract') -> Dict:
        """شارژ خودکار مرخصی استحقاقی هنگام ایجاد قرارداد"""
        from models.leave_balance import LeaveBalance
        from models.leave_transaction import LeaveTransaction
        from sqlalchemy import and_

        results = []
        years = self._get_years_for_contract(contract)

        try:
            for year in years:
                # شارژ AL
                if contract.annual_leave_days > 0:
                    result = self.credit_annual_leave(
                        user_id=contract.user_id,
                        year=year,
                        amount=contract.annual_leave_days,
                        description=f'شارژ خودکار از قرارداد جدید (ID: {contract.id}, نوع: {contract.contract_type})'
                    )
                    results.append({'year': year, 'type': 'AL', 'result': result})

                # شارژ SL
                if contract.sick_leave_days > 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        result = lm.credit_leave(
                            user_id=contract.user_id,
                            year=year,
                            leave_type='SL',
                            amount=contract.sick_leave_days,
                            transaction_type='CONTRACT',
                            description=f'شارژ خودکار استعلاجی از قرارداد (ID: {contract.id})'
                        )
                        results.append({'year': year, 'type': 'SL', 'result': result})
                    finally:
                        lm.close()

                # شارژ RL
                if contract.reward_leave_days > 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        result = lm.credit_leave(
                            user_id=contract.user_id,
                            year=year,
                            leave_type='RL',
                            amount=contract.reward_leave_days,
                            transaction_type='CONTRACT',
                            description=f'شارژ خودکار تشویقی از قرارداد (ID: {contract.id})'
                        )
                        results.append({'year': year, 'type': 'RL', 'result': result})
                    finally:
                        lm.close()

            return {
                'success': True,
                'message': f'✅ مرخصی برای {len(years)} سال شارژ شد',
                'details': results
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در شارژ خودکار: {e}'}

    def _deduct_leave_for_contract(self, contract: 'Contract') -> Dict:
        """کسر خودکار مرخصی استحقاقی هنگام حذف قرارداد"""
        from models.leave_balance import LeaveBalance
        from models.leave_transaction import LeaveTransaction
        from sqlalchemy import and_

        results = []
        years = self._get_years_for_contract(contract)

        try:
            for year in years:
                # کسر AL
                if contract.annual_leave_days > 0:
                    balance = self.db.query(LeaveBalance).filter(
                        and_(
                            LeaveBalance.user_id == contract.user_id,
                            LeaveBalance.year == year,
                            LeaveBalance.leave_type == 'AL'
                        )
                    ).first()

                    old_balance = balance.balance if balance else 0

                    if balance:
                        balance.balance -= contract.annual_leave_days

                    # ثبت تراکنش کسر
                    transaction = LeaveTransaction(
                        user_id=contract.user_id,
                        year=year,
                        leave_type='AL',
                        amount=-contract.annual_leave_days,  # منفی برای کسر
                        transaction_type='CONTRACT',
                        description=f'کسر به دلیل حذف قرارداد (ID: {contract.id}, نوع: {contract.contract_type})'
                    )
                    self.db.add(transaction)

                    results.append({
                        'year': year,
                        'type': 'AL',
                        'old_balance': old_balance,
                        'new_balance': balance.balance if balance else 0,
                        'amount': contract.annual_leave_days
                    })

                # کسر SL
                if contract.sick_leave_days > 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        lm.credit_leave(
                            user_id=contract.user_id,
                            year=year,
                            leave_type='SL',
                            amount=-contract.sick_leave_days,
                            transaction_type='CONTRACT',
                            description=f'کسر استعلاجی به دلیل حذف قرارداد (ID: {contract.id})'
                        )
                        results.append({'year': year, 'type': 'SL', 'amount': contract.sick_leave_days})
                    finally:
                        lm.close()

                # کسر RL
                if contract.reward_leave_days > 0:
                    from core.leave_manager import LeaveManager
                    lm = LeaveManager()
                    try:
                        lm.credit_leave(
                            user_id=contract.user_id,
                            year=year,
                            leave_type='RL',
                            amount=-contract.reward_leave_days,
                            transaction_type='CONTRACT',
                            description=f'کسر تشویقی به دلیل حذف قرارداد (ID: {contract.id})'
                        )
                        results.append({'year': year, 'type': 'RL', 'amount': contract.reward_leave_days})
                    finally:
                        lm.close()

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ مرخصی برای {len(years)} سال کسر شد',
                'details': results
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در کسر خودکار: {e}'}

    def delete_contract(self, contract_id: int) -> Dict:
        """حذف قرارداد با کسر خودکار مرخصی"""
        contract = self.db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            return {'success': False, 'message': '❌ قرارداد یافت نشد'}

        # ذخیره اطلاعات برای نمایش
        info = {
            'id': contract.id,
            'user_id': contract.user_id,
            'contract_type': contract.contract_type,
            'annual_leave_days': contract.annual_leave_days,
            'sick_leave_days': contract.sick_leave_days,
            'reward_leave_days': contract.reward_leave_days
        }

        try:
            # ✅ کسر خودکار مرخصی قبل از حذف
            deduct_result = self._deduct_leave_for_contract(contract)

            # حذف قرارداد
            self.db.delete(contract)
            self.db.commit()

            message = f'✅ قرارداد با موفقیت حذف شد'
            if deduct_result['success']:
                message += f'\n{deduct_result["message"]}'

            return {
                'success': True,
                'message': message,
                'info': info,
                'deduct_result': deduct_result
            }
        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا در حذف قرارداد: {e}'}