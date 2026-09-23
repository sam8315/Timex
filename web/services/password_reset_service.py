"""
سرویس بازنشانی رمز عبور
"""
import secrets
import bcrypt
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple

from sqlalchemy.orm import Session
from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone
from models.password_reset import PasswordResetRequest
from core.sms_service import SmsService

logger = logging.getLogger(__name__)


class PasswordResetService:
    OTP_LIFETIME_MINUTES = 5
    MAX_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 60
    OTP_LENGTH = 6

    def __init__(self, db_session: Session):
        self.db = db_session
        self.sms_service = SmsService()

    def _hash_otp(self, otp_plaintext: str) -> str:
        """هش کردن OTP با bcrypt"""
        # bcrypt برای رشته‌های طولانی‌تر از 72 بایت مناسب نیست، اما برای OTP 6 رقمی کافی است.
        # برای ثابت نگه داشتن زمان هش، از یک salt ثابت استفاده نمی‌کنیم و به bcrypt اجازه می‌دهیم salt را تولید کند.
        # مقایسه باید از checkpw استفاده کند که constant-time است.
        otp_bytes = otp_plaintext.encode('utf-8')
        hashed = bcrypt.hashpw(otp_bytes, bcrypt.gensalt())
        return hashed.decode('utf-8')

    def _verify_otp(self, otp_plaintext: str, otp_hash: str) -> bool:
        """بررسی صحت OTP با هش ذخیره شده (مقایسه constant-time)"""
        try:
            otp_bytes = otp_plaintext.encode('utf-8')
            hash_bytes = otp_hash.encode('utf-8')
            return bcrypt.checkpw(otp_bytes, hash_bytes)
        except Exception as e:
            logger.error(f"Error verifying OTP: {e}")
            return False

    def _generate_secure_otp(self) -> str:
        """تولید یک OTP 6 رقمی امن"""
        return ''.join(secrets.choice('0123456789') for _ in range(self.OTP_LENGTH))

    def _get_user_default_phone(self, user_id: str) -> Optional[str]:
        """شماره تلفن پیش‌فرض کاربر را پیدا می‌کند"""
        phone = self.db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user_id,
            EmployeePhone.is_default == True
        ).first()
        return phone.phone_number if phone else None

    def create_password_reset_request(
        self, national_code: str
    ) -> Tuple[bool, str]:
        """درخواست بازنشانی رمز عبور را ایجاد و OTP را ارسال می‌کند.

        بازگشت: (success, message)
        """
        employee = self.db.query(Employee).filter(
            Employee.national_code == national_code.strip()
        ).first()
        if not employee:
            logger.warning(f"Password reset request for unknown national code: {national_code[:3]}...")
            return False, "کد ملی نامعتبر است."

        user = self.db.query(User).filter(User.user_id == employee.user_id).first()
        if not user:
            logger.warning(f"Password reset request for user_id not found: {employee.user_id}")
            return False, "کد ملی نامعتبر است."

        phone_number = self._get_user_default_phone(user.user_id)
        if not phone_number:
            logger.warning(f"User {user.user_id} has no default phone for password reset.")
            return False, "کاربر شماره تماس پیش‌فرض ندارد."

        # بررسی cooldown ارسال مجدد
        last_request = self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user.user_id
        ).order_by(PasswordResetRequest.created_at.desc()).first()

        if last_request and (datetime.now(timezone.utc) - last_request.created_at).total_seconds() < self.RESEND_COOLDOWN_SECONDS:
            remaining = int(self.RESEND_COOLDOWN_SECONDS - (datetime.now(timezone.utc) - last_request.created_at).total_seconds())
            return False, f"لطفاً {remaining} ثانیه صبر کنید تا کد جدید ارسال شود."

        # باطل کردن درخواست‌های قبلی فعال برای این کاربر
        self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user.user_id,
            PasswordResetRequest.consumed_at.is_(None),
            PasswordResetRequest.expires_at > datetime.now(timezone.utc)
        ).update({'consumed_at': datetime.now(timezone.utc)}, synchronize_session=False)
        self.db.commit()

        otp_plaintext = self._generate_secure_otp()
        otp_hash = self._hash_otp(otp_plaintext)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.OTP_LIFETIME_MINUTES)

        new_request = PasswordResetRequest(
            user_id=user.user_id,
            phone_number=phone_number,
            otp_hash=otp_hash,
            expires_at=expires_at,
            attempts=0,
            consumed_at=None
        )
        self.db.add(new_request)
        self.db.commit()
        self.db.refresh(new_request)

        # ارسال SMS
        message = (
            f"کد بازیابی رمز عبور Timex: {otp_plaintext}\n"
            f"این کد تا {self.OTP_LIFETIME_MINUTES} دقیقه معتبر است."
        )
        sms_result = self.sms_service.send_sms([phone_number], message)

        if not sms_result.get("success"):
            logger.error(f"Failed to send password reset OTP via SMS for user {user.user_id}")
            self.db.delete(new_request) # Rollback the request creation if SMS fails
            self.db.commit()
            return False, "خطا در ارسال پیامک. لطفاً دوباره تلاش کنید."

        return True, "کد بازیابی رمز عبور با موفقیت ارسال شد."

    def validate_otp(
        self, user_id: str, phone_number: str, otp_plaintext: str
    ) -> Tuple[bool, str, Optional[PasswordResetRequest]]:
        """OTP را اعتبارسنجی می‌کند.

        بازگشت: (is_valid, message, password_reset_request)
        """
        request = self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.phone_number == phone_number,
            PasswordResetRequest.consumed_at.is_(None)
        ).order_by(PasswordResetRequest.created_at.desc()).first()

        if not request:
            return False, "درخواست بازنشانی یافت نشد یا منقضی شده است.", None

        if request.expires_at < datetime.now(timezone.utc):
            request.consumed_at = datetime.now(timezone.utc) # Mark as consumed if expired
            self.db.commit()
            return False, "کد بازیابی منقضی شده است.", None

        if request.attempts >= self.MAX_ATTEMPTS:
            return False, "تعداد تلاش‌ها بیش از حد مجاز است.", None

        if not self._verify_otp(otp_plaintext, request.otp_hash):
            request.attempts += 1
            self.db.commit()
            if request.attempts >= self.MAX_ATTEMPTS:
                return False, "تعداد تلاش‌ها بیش از حد مجاز است.", None
            return False, f"کد بازیابی نادرست است. {self.MAX_ATTEMPTS - request.attempts} تلاش باقی مانده است.", None

        # OTP معتبر است
        return True, "کد بازیابی معتبر است.", request

    def consume_request(self, reset_request: PasswordResetRequest) -> None:
        """یک درخواست بازنشانی را مصرف شده علامت‌گذاری می‌کند.

        این متد باید پس از استفاده موفقیت‌آمیز OTP فراخوانی شود.
        """
        if not reset_request.consumed_at:
            reset_request.consumed_at = datetime.now(timezone.utc)
            self.db.commit()

    def invalidate_all_user_requests(self, user_id: str) -> None:
        """تمام درخواست‌های بازنشانی فعال یک کاربر را باطل می‌کند.

        این متد برای زمانی است که یک رویداد امنیتی (مانند تغییر رمز عبور مستقیم) رخ می‌دهد.
        """
        self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.consumed_at.is_(None)
        ).update({'consumed_at': datetime.now(timezone.utc)}, synchronize_session=False)
        self.db.commit()

    def get_latest_active_request(self, user_id: str) -> Optional[PasswordResetRequest]:
        """جدیدترین درخواست بازنشانی فعال برای یک کاربر را برمی‌گرداند."""
        return self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.consumed_at.is_(None),
            PasswordResetRequest.expires_at > datetime.now(timezone.utc)
        ).order_by(PasswordResetRequest.created_at.desc()).first()

    def check_resend_eligibility(self, user_id: str) -> Tuple[bool, Optional[int]]:
        """وضعیت امکان ارسال مجدد کد را بررسی می‌کند.

        بازگشت: (is_eligible, remaining_cooldown_seconds_or_none)
        """
        last_request = self.db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == user_id
        ).order_by(PasswordResetRequest.created_at.desc()).first()

        if not last_request:
            return True, None  # هیچ درخواستی قبلاً ارسال نشده

        time_since_last_send = (datetime.now(timezone.utc) - last_request.created_at).total_seconds()
        if time_since_last_send >= self.RESEND_COOLDOWN_SECONDS:
            return True, None
        else:
            remaining = int(self.RESEND_COOLDOWN_SECONDS - time_since_last_send)
            return False, remaining
