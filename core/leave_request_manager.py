"""
ماژول مدیریت درخواست‌های مرخصی
- ثبت درخواست
- تایید/رد درخواست
- به‌روزرسانی وضعیت روزانه
- کسر خودکار از مانده مرخصی
"""
from datetime import date, timedelta,datetime
from typing import List, Dict, Optional
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.leave_request import LeaveRequest
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.daily_status import DailyStatus
from models.holiday import Holiday
from core.leave_manager import LeaveManager
from core.holiday_manager import HolidayManager


class LeaveRequestManager:
    """مدیریت درخواست‌های مرخصی"""

    # وضعیت‌های درخواست
    STATUS_PENDING = 'P'
    STATUS_APPROVED = 'A'
    STATUS_REJECTED = 'R'

    STATUS_NAMES = {
        'P': 'در انتظار تایید',
        'A': 'تایید شده',
        'R': 'رد شده'
    }

    def __init__(self):
        self.db: Session = SessionLocal()
        self.leave_manager = LeaveManager()
        self.holiday_manager = HolidayManager()

    def close(self):
        if self.db:
            self.db.close()
        if self.leave_manager:
            self.leave_manager.close()
        if self.holiday_manager:
            self.holiday_manager.close()

    def calculate_working_days(self, from_date: date, to_date: date) -> int:
        """
        محاسبه تعداد روزهای کاری بین دو تاریخ
        (بدون احتساب جمعه‌ها و تعطیلات)
        """
        days = 0
        current = from_date

        while current <= to_date:
            # بررسی جمعه بودن
            if current.weekday() != 4:  # 4 = جمعه
                # بررسی تعطیل بودن
                if not self.holiday_manager.is_holiday(current):
                    days += 1
            current += timedelta(days=1)

        return days

    def create_request(
            self,
            user_id: str,
            leave_type: str,
            from_date: date,
            to_date: date,
            reason: str = ""
    ) -> Dict:
        """ثبت درخواست مرخصی جدید"""
        import jdatetime

        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'❌ کاربر {user_id} یافت نشد'}

        # بررسی تاریخ‌ها
        if from_date > to_date:
            return {'success': False, 'message': '❌ تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد'}

        # محاسبه تعداد روزهای کاری
        days_count = self.calculate_working_days(from_date, to_date)

        if days_count == 0:
            return {'success': False, 'message': '⚠️  تمام روزهای انتخاب شده تعطیل هستند'}

        # ✅ تبدیل تاریخ میلادی به شمسی برای دریافت سال صحیح
        try:
            j_from = jdatetime.date.fromgregorian(date=from_date)
            jalali_year = j_from.year  # ✅ سال شمسی
        except Exception as e:
            return {'success': False, 'message': f'❌ خطا در تبدیل تاریخ: {e}'}

        # بررسی مانده مرخصی (فقط برای استحقاقی)
        if leave_type == 'AL':
            balance = self.leave_manager.get_balance(user_id, jalali_year, 'AL')

            if balance < days_count:
                return {
                    'success': False,
                    'message': f'❌ مانده مرخصی استحقاقی کافی نیست. موجودی: {balance} روز، درخواست: {days_count} روز'
                }

        # بررسی تداخل با درخواست‌های قبلی
        overlapping = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status != 'R',
                LeaveRequest.from_date <= to_date,
                LeaveRequest.to_date >= from_date
            )
        ).first()

        if overlapping:
            return {
                'success': False,
                'message': f'⚠️  تداخل با درخواست قبلی (از {overlapping.from_date} تا {overlapping.to_date})'
            }

        try:
            request = LeaveRequest(
                user_id=user_id,
                leave_type=leave_type,
                from_date=from_date,
                to_date=to_date,
                days_count=days_count,
                reason=reason,
                status=self.STATUS_PENDING
            )
            self.db.add(request)
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ درخواست مرخصی ثبت شد (ID: {request.id})',
                'request_id': request.id,
                'days_count': days_count
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def approve_request(self, request_id: int, approved_by: str = "admin") -> Dict:
        """تایید درخواست مرخصی"""
        import jdatetime

        request = self.db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()

        if not request:
            return {'success': False, 'message': '❌ درخواست یافت نشد'}

        if request.status == self.STATUS_APPROVED:
            return {'success': False, 'message': '⚠️  این درخواست قبلاً تایید شده است'}

        if request.status == self.STATUS_REJECTED:
            return {'success': False, 'message': '⚠️  این درخواست قبلاً رد شده است'}

        # ✅ تبدیل تاریخ میلادی به شمسی برای دریافت سال صحیح
        try:
            j_from = jdatetime.date.fromgregorian(date=request.from_date)
            jalali_year = j_from.year  # ✅ سال شمسی
        except Exception as e:
            return {'success': False, 'message': f'❌ خطا در تبدیل تاریخ: {e}'}

        # بررسی مانده مرخصی
        balance = self.leave_manager.get_balance(request.user_id, jalali_year, request.leave_type)

        if balance < request.days_count:
            return {
                'success': False,
                'message': f'❌ مانده کافی نیست. موجودی: {balance} روز، درخواست: {request.days_count} روز'
            }

        try:
            # به‌روزرسانی وضعیت درخواست
            request.status = self.STATUS_APPROVED
            request.approved_by = approved_by
            request.approved_at = func.now()

            # به‌روزرسانی وضعیت روزانه
            current = request.from_date
            while current <= request.to_date:
                if current.weekday() != 4 and not self.holiday_manager.is_holiday(current):
                    existing = self.db.query(DailyStatus).filter(
                        and_(
                            DailyStatus.user_id == request.user_id,
                            DailyStatus.status_date == current
                        )
                    ).first()

                    if existing:
                        existing.status_code = request.leave_type
                        existing.leave_request_id = request.id
                    else:
                        status = DailyStatus(
                            user_id=request.user_id,
                            status_date=current,
                            status_code=request.leave_type,
                            leave_request_id=request.id
                        )
                        self.db.add(status)

                current += timedelta(days=1)

            # کسر از مانده مرخصی
            result = self.leave_manager.debit_leave(
                user_id=request.user_id,
                year=jalali_year,  # ✅ سال شمسی
                leave_type=request.leave_type,
                amount=request.days_count,
                description=f'تایید درخواست مرخصی شماره {request.id}',
                reference_id=request.id
            )

            if not result['success']:
                raise Exception(result['message'])

            self.db.commit()

            return {
                'success': True,
                'message': f'✅ درخواست تایید شد و {request.days_count} روز از مانده کسر شد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def reject_request(self, request_id: int, rejection_reason: str = "") -> Dict:
        """رد درخواست مرخصی"""
        request = self.db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()

        if not request:
            return {'success': False, 'message': '❌ درخواست یافت نشد'}

        if request.status == self.STATUS_APPROVED:
            return {'success': False, 'message': '⚠️  نمی‌توان درخواست تایید شده را رد کرد'}

        if request.status == self.STATUS_REJECTED:
            return {'success': False, 'message': '⚠️  این درخواست قبلاً رد شده است'}

        try:
            request.status = self.STATUS_REJECTED
            request.rejection_reason = rejection_reason

            self.db.commit()

            return {'success': True, 'message': '✅ درخواست رد شد'}

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_pending_requests(self) -> List[LeaveRequest]:
        """دریافت درخواست‌های در انتظار تایید"""
        return self.db.query(LeaveRequest).filter(
            LeaveRequest.status == self.STATUS_PENDING
        ).order_by(LeaveRequest.created_at.asc()).all()

    def get_user_requests(
            self,
            user_id: str,
            year: Optional[int] = None,
            status: Optional[str] = None
    ) -> List[LeaveRequest]:
        """
        دریافت درخواست‌های یک کاربر
        year: سال شمسی
        """
        query = self.db.query(LeaveRequest).filter(LeaveRequest.user_id == user_id)

        if year:
            # ✅ تبدیل سال شمسی به میلادی
            import jdatetime
            j_from = jdatetime.date(year, 1, 1)
            j_to = jdatetime.date(year, 12, 29)
            g_from = j_from.togregorian()
            g_to = j_to.togregorian()

            query = query.filter(
                and_(
                    LeaveRequest.from_date >= g_from,
                    LeaveRequest.from_date <= g_to
                )
            )

        if status:
            query = query.filter(LeaveRequest.status == status)

        return query.order_by(LeaveRequest.from_date.desc()).all()
    def get_all_requests(
        self,
        year: Optional[int] = None,
        status: Optional[str] = None
    ) -> List[LeaveRequest]:
        """دریافت تمام درخواست‌ها"""
        query = self.db.query(LeaveRequest)

        if year:
            query = query.filter(func.extract('year', LeaveRequest.from_date) == year)

        if status:
            query = query.filter(LeaveRequest.status == status)

        return query.order_by(LeaveRequest.created_at.desc()).all()

    def get_request_statistics(self, year: int) -> Dict:
        """آمار درخواست‌های مرخصی - year: سال شمسی"""
        import jdatetime

        # ✅ تبدیل سال شمسی به میلادی
        j_from = jdatetime.date(year, 1, 1)
        j_to = jdatetime.date(year, 12, 29)
        g_from = j_from.togregorian()
        g_to = j_to.togregorian()

        total = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to
            )
        ).count()

        pending = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to,
                LeaveRequest.status == self.STATUS_PENDING
            )
        ).count()

        approved = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to,
                LeaveRequest.status == self.STATUS_APPROVED
            )
        ).count()

        rejected = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to,
                LeaveRequest.status == self.STATUS_REJECTED
            )
        ).count()

        # آمار بر اساس نوع مرخصی
        by_type = {}
        requests = self.db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.from_date >= g_from,
                LeaveRequest.from_date <= g_to,
                LeaveRequest.status == self.STATUS_APPROVED
            )
        ).all()

        for req in requests:
            if req.leave_type not in by_type:
                by_type[req.leave_type] = {'count': 0, 'days': 0}
            by_type[req.leave_type]['count'] += 1
            by_type[req.leave_type]['days'] += req.days_count

        return {
            'total': total,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'by_type': by_type
        }

    def approve_all_pending(self) -> Dict:
        """
        تایید همه درخواست‌های مرخصی در انتظار
        """
        pending_requests = self.db.query(LeaveRequest).filter(
            LeaveRequest.status == 'P'
        ).all()

        if not pending_requests:
            return {
                'success': False,
                'message': '⚠️  هیچ درخواست در انتظاری وجود ندارد',
                'count': 0
            }

        approved_count = 0
        try:
            for request in pending_requests:
                request.status = 'A'  # Approved
                request.approved_by = 'SYSTEM'
                request.approved_at = datetime.now()
                approved_count += 1

            self.db.commit()
            return {
                'success': True,
                'message': f'✅ {approved_count} درخواست مرخصی با موفقیت تایید شد',
                'count': approved_count
            }

        except Exception as e:
            self.db.rollback()
            return {
                'success': False,
                'message': f'❌ خطا در تایید درخواست‌ها: {e}',
                'count': 0
            }

    def get_employee_name(self, user_id: str) -> str:
        """دریافت نام کارمند"""
        from models.employee import Employee
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee:
            return employee.full_name
        return f"کاربر {user_id}"