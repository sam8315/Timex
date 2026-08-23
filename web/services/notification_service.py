"""
سرویس نوتیفیکیشن (پیامک) برای پنل وب
- ارسال پیامک تایید مرخصی
- ارسال پیامک رد مرخصی
- مدیریت خطا بدون تأثیر بر فرآیند اصلی
"""
import logging
from sqlalchemy.orm import Session
from models.employee_phone import EmployeePhone
from models.leave_request import LeaveRequest
from core.sms_service import SmsService

logger = logging.getLogger(__name__)


def send_leave_sms_notification(
        db: Session,
        leave_request: LeaveRequest,
        action: str = 'approved',
        rejection_reason: str = ""
) -> dict:
    """
    ارسال پیامک نوتیفیکیشن برای کاربر

    Args:
        db: سشن دیتابیس
        leave_request: درخواست مرخصی
        action: 'approved' یا 'rejected'
        rejection_reason: دلیل رد (فقط برای rejected)

    Returns:
        dict: نتیجه ارسال
    """
    try:
        # ۱. دریافت شماره‌های کاربر
        phones = db.query(EmployeePhone).filter(
            EmployeePhone.user_id == leave_request.user_id
        ).all()

        if not phones:
            logger.info(
                f"ℹ️ کاربر {leave_request.user_id} شماره‌ای ندارد - پیامک ارسال نشد"
            )
            return {
                'sent': False,
                'reason': 'no_phone',
                'message': 'کاربر شماره‌ای ثبت نکرده است'
            }

        # ۲. اولویت با شماره پیش‌فرض، در غیر این صورت همه شماره‌ها
        default_phone = next((p for p in phones if p.is_default), None)
        if default_phone:
            phone_numbers = [default_phone.phone_number]
        else:
            phone_numbers = [p.phone_number for p in phones]

        # ۳. ارسال پیامک
        sms_service = SmsService()

        if action == 'approved':
            result = sms_service.send_leave_approval_sms(
                phones=phone_numbers,
                leave_type=leave_request.leave_type,
                from_date=leave_request.from_date,
                to_date=leave_request.to_date,
                days_count=leave_request.days_count
            )
        elif action == 'rejected':
            result = sms_service.send_leave_rejection_sms(
                phones=phone_numbers,
                leave_type=leave_request.leave_type,
                from_date=leave_request.from_date,
                to_date=leave_request.to_date,
                reason=rejection_reason
            )
        else:
            return {'sent': False, 'reason': 'invalid_action'}

        # ۴. لاگ نتیجه
        if result.get('success'):
            logger.info(
                f"✅ پیامک {action} برای {leave_request.user_id} ارسال شد "
                f"به {phone_numbers}"
            )
        else:
            logger.warning(
                f"⚠️ ارسال پیامک ناموفق بود: {result.get('message')}"
            )

        return {
            'sent': result.get('success', False),
            'phones': phone_numbers,
            'message': result.get('message', '')
        }

    except Exception as e:
        logger.error(f"❌ خطا در ارسال پیامک: {e}", exc_info=True)
        return {
            'sent': False,
            'reason': 'error',
            'message': str(e)
        }