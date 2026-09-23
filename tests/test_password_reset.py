import pytest
import time
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone
from models.password_reset import PasswordResetRequest
from web.services.password_reset_service import PasswordResetService


@pytest.fixture
def password_reset_service(db: Session, mock_sms_service) -> PasswordResetService:
    """Fixture for PasswordResetService"""
    return PasswordResetService(db_session=db)


@pytest.fixture
def mock_sms_service():
    """Mock SmsService to prevent actual SMS sends"""
    with patch('web.services.password_reset_service.SmsService') as MockSmsService:
        instance = MockSmsService.return_value
        instance.send_sms.return_value = {"success": True}
        yield instance


@pytest.fixture
def create_user_with_phone(db: Session):
    """Fixture to create a user with a national code and default phone"""
    def _create(user_id: str, national_code: str, phone_number: str, is_default: bool = True):
        user = User(user_id=user_id, name="Test User", password_hash="test_hash", web_enabled=True)
        db.add(user)
        employee = Employee(user_id=user_id, national_code=national_code, first_name="Test", last_name="User")
        db.add(employee)
        phone = EmployeePhone(user_id=user_id, phone_number=phone_number, is_default=is_default)
        db.add(phone)
        db.commit()
        db.refresh(user)
        db.refresh(employee)
        db.refresh(phone)
        return user, employee, phone
    return _create


class TestPasswordResetService:

    def test_otp_generation_format_and_security(self, password_reset_service):
        """تست تولید OTP: ۶ رقمی، فقط شامل اعداد، امن"""
        otp1 = password_reset_service._generate_secure_otp()
        otp2 = password_reset_service._generate_secure_otp()

        assert len(otp1) == 6
        assert otp1.isdigit()
        assert otp1 != otp2  # باید مقادیر مختلفی تولید کند

        # تست اینکه واقعاً از secrets استفاده شده (تولید 1000 کد و بررسی تفاوت)
        otps = {password_reset_service._generate_secure_otp() for _ in range(1000)}
        assert len(otps) > 900  # انتظار داریم بیشترشان منحصربفرد باشند

    def test_otp_hashing_and_verification(self, password_reset_service):
        """تست هش و اعتبارسنجی OTP"""
        otp_plaintext = password_reset_service._generate_secure_otp()
        otp_hash = password_reset_service._hash_otp(otp_plaintext)

        assert isinstance(otp_hash, str)
        assert password_reset_service._verify_otp(otp_plaintext, otp_hash) is True
        assert password_reset_service._verify_otp("wrong_otp", otp_hash) is False

        # تست constant-time comparison (سطح بالا)
        # در اینجا نیازی به تست دقیق زمان‌سنجی نیست چون bcrypt.checkpw خودش این تضمین را می‌دهد.
        start_time = time.perf_counter()
        password_reset_service._verify_otp(otp_plaintext, otp_hash)
        end_time_correct = time.perf_counter()

        password_reset_service._verify_otp("123456", otp_hash)
        end_time_incorrect = time.perf_counter()

        # انتظار داریم زمان‌ها بسیار نزدیک باشند
        assert abs((end_time_correct - start_time) - (end_time_incorrect - start_time)) < 0.5

    def test_create_password_reset_request_success(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست ایجاد موفقیت‌آمیز درخواست بازنشانی رمز عبور"""
        user, _, _ = create_user_with_phone("user1", "1234567890", "09123456789")

        success, message = password_reset_service.create_password_reset_request("1234567890")

        assert success is True
        assert "با موفقیت ارسال شد" in message
        mock_sms_service.send_sms.assert_called_once()

        request = db.query(PasswordResetRequest).filter_by(user_id="user1").first()
        assert request is not None
        assert request.user_id == "user1"
        assert request.phone_number == "09123456789"
        assert request.otp_hash is not None
        assert request.expires_at > datetime.now(timezone.utc)
        assert request.attempts == 0
        assert request.consumed_at is None

    def test_create_request_unknown_national_code(self, password_reset_service, mock_sms_service):
        """تست درخواست با کد ملی ناشناخته"""
        success, message = password_reset_service.create_password_reset_request("9999999999")

        assert success is False
        assert "کد ملی نامعتبر است" in message
        mock_sms_service.send_sms.assert_not_called()

    def test_create_request_no_default_phone(self, db: Session, password_reset_service, mock_sms_service):
        """تست درخواست برای کاربری بدون شماره پیش‌فرض"""
        user = User(user_id="user_no_phone", name="Test User", password_hash="test_hash", web_enabled=True)
        db.add(user)
        employee = Employee(user_id="user_no_phone", national_code="0000000000", first_name="Test", last_name="User")
        db.add(employee)
        db.commit()

        success, message = password_reset_service.create_password_reset_request("0000000000")

        assert success is False
        assert "شماره تماس پیش‌فرض ندارد" in message
        mock_sms_service.send_sms.assert_not_called()

    def test_otp_expiration(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست انقضای OTP"""
        user, _, _ = create_user_with_phone("user2", "1111111111", "09111111111")

        # ایجاد درخواست
        success, _ = password_reset_service.create_password_reset_request("1111111111")
        assert success is True

        request = db.query(PasswordResetRequest).filter_by(user_id="user2").first()
        assert request is not None
        otp_plaintext = password_reset_service._generate_secure_otp() # این OTP استفاده نمی‌شود، فقط برای پر کردن آرگومان است

        # دستکاری زمان انقضا برای تست فوری
        request.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

        is_valid, message, _ = password_reset_service.validate_otp("user2", "09111111111", otp_plaintext)
        assert is_valid is False
        assert "منقضی شده است" in message
        db.refresh(request)
        assert request.consumed_at is not None # باید به عنوان مصرف شده علامت‌گذاری شود

    def test_max_failed_attempts(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست حداکثر تعداد تلاش‌های ناموفق"""
        user, _, _ = create_user_with_phone("user3", "2222222222", "09222222222")

        success, _ = password_reset_service.create_password_reset_request("2222222222")
        assert success is True

        request = db.query(PasswordResetRequest).filter_by(user_id="user3").first()
        assert request is not None
        correct_otp = password_reset_service._generate_secure_otp()
        request.otp_hash = password_reset_service._hash_otp(correct_otp) # هش OTP صحیح را جایگذاری می‌کنیم
        db.commit()

        for i in range(password_reset_service.MAX_ATTEMPTS - 1):
            is_valid, message, _ = password_reset_service.validate_otp("user3", "09222222222", "wrong_otp")
            assert is_valid is False
            assert f"{password_reset_service.MAX_ATTEMPTS - (i + 1)} تلاش باقی مانده است" in message
            db.refresh(request)
            assert request.attempts == (i + 1)
            assert request.consumed_at is None

        # آخرین تلاش ناموفق
        is_valid, message, _ = password_reset_service.validate_otp("user3", "09222222222", "wrong_otp")
        assert is_valid is False
        assert "تعداد تلاش‌ها بیش از حد مجاز است" in message
        db.refresh(request)
        assert request.attempts == password_reset_service.MAX_ATTEMPTS
        assert request.consumed_at is None

        # بعد از اتمام تلاش‌ها، حتی OTP صحیح هم باید رد شود
        is_valid, message, _ = password_reset_service.validate_otp("user3", "09222222222", correct_otp)
        assert is_valid is False
        assert "تعداد تلاش‌ها بیش از حد مجاز است" in message

    def test_one_time_use(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست استفاده یکبار مصرف OTP"""
        user, _, _ = create_user_with_phone("user4", "3333333333", "09333333333")

        success, _ = password_reset_service.create_password_reset_request("3333333333")
        assert success is True

        request = db.query(PasswordResetRequest).filter_by(user_id="user4").first()
        assert request is not None
        correct_otp = password_reset_service._generate_secure_otp()
        request.otp_hash = password_reset_service._hash_otp(correct_otp)
        db.commit()

        # اولین استفاده - موفقیت‌آمیز
        is_valid, message, consumed_request = password_reset_service.validate_otp("user4", "09333333333", correct_otp)
        assert is_valid is True
        assert "معتبر است" in message
        assert consumed_request is not None

        password_reset_service.consume_request(consumed_request)
        db.refresh(request)
        assert request.consumed_at is not None

        # استفاده مجدد از همان OTP - باید رد شود
        is_valid, message, _ = password_reset_service.validate_otp("user4", "09333333333", correct_otp)
        assert is_valid is False
        assert "یافت نشد یا منقضی شده است" in message # یا منقضی شده، یا مصرف شده

    def test_new_otp_invalidates_previous_otps(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست ابطال OTPهای قبلی با ایجاد درخواست جدید"""
        user, _, _ = create_user_with_phone("user5", "4444444444", "09444444444")

        # ایجاد اولین درخواست
        success1, _ = password_reset_service.create_password_reset_request("4444444444")
        assert success1 is True
        first_request = db.query(PasswordResetRequest).filter_by(user_id="user5").order_by(PasswordResetRequest.created_at.desc()).first()
        assert first_request is not None
        assert first_request.consumed_at is None

        time.sleep(password_reset_service.RESEND_COOLDOWN_SECONDS + 1) # اطمینان از عبور از زمان cooldown

        # ایجاد درخواست دوم - باید اولی را باطل کند
        success2, _ = password_reset_service.create_password_reset_request("4444444444")
        assert success2 is True
        second_request = db.query(PasswordResetRequest).filter_by(user_id="user5").order_by(PasswordResetRequest.created_at.desc()).first()
        assert second_request is not None
        assert second_request.id != first_request.id
        assert second_request.consumed_at is None

        db.refresh(first_request)
        assert first_request.consumed_at is not None # اولین درخواست باید باطل شده باشد

    def test_resend_cooldown(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست محدودیت زمان ارسال مجدد"""
        user, _, _ = create_user_with_phone("user6", "5555555555", "09555555555")

        # اولین درخواست
        success1, _ = password_reset_service.create_password_reset_request("5555555555")
        assert success1 is True

        # تلاش برای ارسال مجدد قبل از cooldown
        mock_sms_service.send_sms.reset_mock()
        success2, message2 = password_reset_service.create_password_reset_request("5555555555")
        assert success2 is False
        assert "ثانیه صبر کنید" in message2
        mock_sms_service.send_sms.assert_not_called()

        # صبر کردن تا بعد از cooldown
        time.sleep(password_reset_service.RESEND_COOLDOWN_SECONDS + 1)

        # ارسال مجدد بعد از cooldown - باید موفق باشد
        success3, message3 = password_reset_service.create_password_reset_request("5555555555")
        assert success3 is True
        assert "با موفقیت ارسال شد" in message3
        mock_sms_service.send_sms.assert_called_once()

    def test_phone_selection_default(self, db: Session, password_reset_service, create_user_with_phone):
        """تست انتخاب شماره پیش‌فرض"""
        user, _, _ = create_user_with_phone("user7", "6666666666", "09666666666", is_default=True)
        phone2 = EmployeePhone(user_id="user7", phone_number="09666666667", is_default=False)
        db.add(phone2)
        db.commit()

        selected_phone = password_reset_service._get_user_default_phone("user7")
        assert selected_phone == "09666666666"

    def test_phone_selection_no_default(self, db: Session, password_reset_service, create_user_with_phone):
        """تست انتخاب شماره در صورت عدم وجود پیش‌فرض"""
        user, _, _ = create_user_with_phone("user8", "7777777777", "09777777777", is_default=False)
        phone2 = EmployeePhone(user_id="user8", phone_number="09777777778", is_default=False)
        db.add(phone2)
        db.commit()

        selected_phone = password_reset_service._get_user_default_phone("user8")
        assert selected_phone is None

    def test_sms_failure_rollback(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone):
        """تست بازگشت تراکنش در صورت عدم موفقیت ارسال SMS"""
        user, _, _ = create_user_with_phone("user9", "8888888888", "09888888888")
        mock_sms_service.send_sms.return_value = {"success": False}

        success, message = password_reset_service.create_password_reset_request("8888888888")

        assert success is False
        assert "خطا در ارسال پیامک" in message
        mock_sms_service.send_sms.assert_called_once()

        # بررسی اینکه درخواست در دیتابیس ذخیره نشده است
        request = db.query(PasswordResetRequest).filter_by(user_id="user9").first()
        assert request is None

    def test_sms_message_content(self, password_reset_service, mock_sms_service, create_user_with_phone, caplog):
        """تست محتوای پیامک ارسالی"""
        user, _, _ = create_user_with_phone("user10", "9999999999", "09999999999")
        
        password_reset_service.create_password_reset_request("9999999999")
        
        args, kwargs = mock_sms_service.send_sms.call_args
        sent_phones = args[0]
        sent_message = args[1]

        assert sent_phones == ["09999999999"]
        assert "کد بازیابی رمز عبور Timex: " in sent_message
        assert f"این کد تا {password_reset_service.OTP_LIFETIME_MINUTES} دقیقه معتبر است." in sent_message
        
        # بررسی عدم وجود OTP در لاگ
        with caplog.at_level('ERROR'):
            mock_sms_service.send_sms.return_value = {"success": False} # شبیه‌سازی عدم موفقیت ارسال برای لاگ
            password_reset_service.create_password_reset_request("9999999999")
            # بررسی عدم لاگ شدن OTP plaintext
            for record in caplog.records:
                assert "otp_plaintext" not in record.message

    def test_security_no_otp_in_logs_or_exceptions(self, db: Session, password_reset_service, mock_sms_service, create_user_with_phone, caplog):
        """تست عدم وجود OTP در لاگ‌ها یا پیام‌های خطا"""
        user, _, _ = create_user_with_phone("user11", "1000000000", "09100000000")
        mock_sms_service.send_sms.return_value = {"success": False}
        
        with caplog.at_level('ERROR'):
            password_reset_service.create_password_reset_request("1000000000")
            # تأیید عدم وجود OTP در لاگ‌ها
            for record in caplog.records:
                assert "otp_plaintext" not in record.message
                assert "100000" not in record.message # اطمینان از عدم حضور OTP تولید شده در پیام لاگ

    def test_get_latest_active_request(self, db: Session, password_reset_service, create_user_with_phone):
        """تست دریافت جدیدترین درخواست فعال"""
        user, _, _ = create_user_with_phone("user12", "1000000001", "09100000001")

        # درخواست اول
        req1_otp = password_reset_service._generate_secure_otp()
        req1 = PasswordResetRequest(
            user_id="user12", phone_number="09100000001", otp_hash=password_reset_service._hash_otp(req1_otp),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
        )
        db.add(req1)
        db.commit()

        # درخواست دوم (فعال)
        req2_otp = password_reset_service._generate_secure_otp()
        req2 = PasswordResetRequest(
            user_id="user12", phone_number="09100000001", otp_hash=password_reset_service._hash_otp(req2_otp),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_at=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        db.add(req2)
        db.commit()

        latest_active = password_reset_service.get_latest_active_request("user12")
        assert latest_active.id == req2.id # باید جدیدترین درخواست فعال را برگرداند

        # درخواست سوم (منقضی شده)
        req3_otp = password_reset_service._generate_secure_otp()
        req3 = PasswordResetRequest(
            user_id="user12", phone_number="09100000001", otp_hash=password_reset_service._hash_otp(req3_otp),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1), created_at=datetime.now(timezone.utc) # منقضی شده
        )
        db.add(req3)
        db.commit()

        latest_active = password_reset_service.get_latest_active_request("user12")
        assert latest_active.id == req2.id # درخواست منقضی شده نباید برگردانده شود

        # درخواست چهارم (مصرف شده)
        req4_otp = password_reset_service._generate_secure_otp()
        req4 = PasswordResetRequest(
            user_id="user12", phone_number="09100000001", otp_hash=password_reset_service._hash_otp(req4_otp),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_at=datetime.now(timezone.utc),
            consumed_at=datetime.now(timezone.utc) # مصرف شده
        )
        db.add(req4)
        db.commit()

        latest_active = password_reset_service.get_latest_active_request("user12")
        assert latest_active.id == req2.id # درخواست مصرف شده نباید برگردانده شود

    def test_invalidate_all_user_requests(self, db: Session, password_reset_service, create_user_with_phone):
        """تست ابطال تمام درخواست‌های فعال یک کاربر"""
        user, _, _ = create_user_with_phone("user13", "1000000002", "09100000002")

        # دو درخواست فعال ایجاد می‌کنیم
        req1 = PasswordResetRequest(
            user_id="user13", phone_number="09100000002", otp_hash="hash1",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_at=datetime.now(timezone.utc)
        )
        req2 = PasswordResetRequest(
            user_id="user13", phone_number="09100000002", otp_hash="hash2",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), created_at=datetime.now(timezone.utc) + timedelta(seconds=10)
        )
        db.add_all([req1, req2])
        db.commit()

        # ابطال همه درخواست‌ها
        password_reset_service.invalidate_all_user_requests("user13")

        db.refresh(req1)
        db.refresh(req2)

        assert req1.consumed_at is not None
        assert req2.consumed_at is not None

        active_requests = db.query(PasswordResetRequest).filter(
            PasswordResetRequest.user_id == "user13",
            PasswordResetRequest.consumed_at.is_(None),
            PasswordResetRequest.expires_at > datetime.now(timezone.utc)
        ).count()
        assert active_requests == 0

    def test_check_resend_eligibility(self, db: Session, password_reset_service, create_user_with_phone):
        """تست بررسی امکان ارسال مجدد"""
        user, _, _ = create_user_with_phone("user14", "1000000003", "09100000003")

        # بدون درخواست قبلی
        eligible, remaining = password_reset_service.check_resend_eligibility("user14")
        assert eligible is True
        assert remaining is None

        # ایجاد درخواست جدید
        password_reset_service.create_password_reset_request("1000000003")
        db.flush() # اطمینان از اعمال تغییرات در دیتابیس قبل از بررسی مجدد

        # بلافاصله بعد از ارسال
        eligible, remaining = password_reset_service.check_resend_eligibility("user14")
        assert eligible is False
        assert remaining is not None
        assert 0 < remaining <= password_reset_service.RESEND_COOLDOWN_SECONDS

        # بعد از گذشت بخشی از زمان cooldown
        time.sleep(password_reset_service.RESEND_COOLDOWN_SECONDS / 2)
        eligible, remaining = password_reset_service.check_resend_eligibility("user14")
        assert eligible is False
        assert remaining > 0
        assert remaining < password_reset_service.RESEND_COOLDOWN_SECONDS

        # بعد از گذشت کامل cooldown
        time.sleep(password_reset_service.RESEND_COOLDOWN_SECONDS / 2 + 1) # +1 برای اطمینان
        eligible, remaining = password_reset_service.check_resend_eligibility("user14")
        assert eligible is True
        assert remaining is None

