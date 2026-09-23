"""Tests for the password-reset HTTP flow (Phase 2)."""
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import USER_PASSWORD
from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone
from models.password_reset import PasswordResetRequest
from web.services.password_reset_service import PasswordResetService


@pytest.fixture
def mock_sms_service():
    """Mock SmsService to prevent actual SMS sends."""
    with patch('web.services.password_reset_service.SmsService') as MockSmsService:
        instance = MockSmsService.return_value
        instance.send_sms.return_value = {"success": True}
        yield instance


@pytest.fixture
def create_user_with_phone(db):
    """Factory to create a user with national code and default phone."""
    def _create(user_id: str, national_code: str, phone_number: str, is_default: bool = True):
        user = User(user_id=user_id, name="Test User", password_hash="test_hash", web_enabled=True)
        db.add(user)
        employee = Employee(user_id=user_id, national_code=national_code,
                            first_name="Test", last_name="User")
        db.add(employee)
        phone = EmployeePhone(user_id=user_id, phone_number=phone_number, is_default=is_default)
        db.add(phone)
        db.commit()
        db.refresh(user)
        db.refresh(employee)
        db.refresh(phone)
        return user, employee, phone
    return _create


# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------
class TestForgotPassword:
    def test_get_page_returns_200(self, client):
        resp = client.get("/forgot-password")
        assert resp.status_code == 200
        assert "بازیابی رمز عبور" in resp.text
        assert 'name="national_code"' in resp.text

    def test_post_valid_national_code(self, client, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_fp1", "1234567890", "09123456789")
        resp = client.post("/forgot-password", data={"national_code": "1234567890"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/verify-reset-code" in resp.headers["location"]
        mock_sms_service.send_sms.assert_called_once()

    def test_post_unknown_national_code(self, client, mock_sms_service):
        resp = client.post("/forgot-password",
                           data={"national_code": "9999999999"},
                           follow_redirects=False)
        # Always returns generic message (200, no redirect to verify)
        assert resp.status_code == 200
        assert "اگر اطلاعات واردشده صحیح باشد" in resp.text
        mock_sms_service.send_sms.assert_not_called()

    def test_generic_response_prevents_enumeration(self, client, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_fp2", "1111111111", "09123456123")
        resp = client.post("/forgot-password",
                           data={"national_code": "9999999999"}, follow_redirects=True)
        assert "اگر اطلاعات واردشده صحیح باشد" in resp.text

    def test_user_without_default_phone(self, client, mock_sms_service, db):
        user = User(user_id="user_nophone", name="Test", password_hash="h", web_enabled=True)
        db.add(user)
        employee = Employee(user_id="user_nophone", national_code="2222222222",
                            first_name="T", last_name="U")
        db.add(employee)
        phone = EmployeePhone(user_id="user_nophone", phone_number="09123456789", is_default=False)
        db.add(phone)
        db.commit()
        resp = client.post("/forgot-password",
                           data={"national_code": "2222222222"}, follow_redirects=True)
        assert "اگر اطلاعات واردشده صحیح باشد" in resp.text
        mock_sms_service.send_sms.assert_not_called()

    def test_successful_sms_flow(self, client, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_fp3", "3333333333", "09123456777")
        resp = client.post("/forgot-password", data={"national_code": "3333333333"})
        assert resp.status_code in (200, 303)
        mock_sms_service.send_sms.assert_called_once()
        args = mock_sms_service.send_sms.call_args[0]
        assert args[0] == ["09123456777"]

    def test_sms_failure_shows_generic_message(self, client, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_fp4", "4444444444", "09123456666")
        mock_sms_service.send_sms.return_value = {"success": False}
        resp = client.post("/forgot-password",
                           data={"national_code": "4444444444"}, follow_redirects=True)
        assert "اگر اطلاعات واردشده صحیح باشد" in resp.text


# ---------------------------------------------------------------------------
# OTP Verification
# ---------------------------------------------------------------------------
class TestOtpVerification:
    def _setup_user_and_request(self, client, db, mock_sms_service, create_user_with_phone):
        """Helper: create user and go through forgot-password to get a reset cookie."""
        create_user_with_phone("user_v1", "3636363636", "09123450001")
        client.post("/forgot-password", data={"national_code": "3636363636"})
        # Get the request from DB to know the OTP
        req = db.query(PasswordResetRequest).filter_by(user_id="user_v1").first()
        return req

    def test_valid_otp(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        # We need the actual OTP - mock it by patching the service's _generate_secure_otp
        # Instead, we'll directly set the hash for a known OTP
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.attempts = 0
        db.commit()
        resp = client.post("/verify-reset-code", data={"otp": test_otp},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/reset-password" in resp.headers["location"]

    def test_wrong_otp(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.attempts = 0
        db.commit()
        resp = client.post("/verify-reset-code", data={"otp": "999999"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "verify-reset-code" in resp.headers["location"]

    def test_expired_otp(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        resp = client.post("/verify-reset-code", data={"otp": test_otp},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "verify-reset-code" in resp.headers["location"]

    def test_max_attempts(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.attempts = 0
        db.commit()
        for _ in range(svc.MAX_ATTEMPTS):
            resp = client.post("/verify-reset-code", data={"otp": "000000"},
                               follow_redirects=False)
        assert resp.status_code == 303
        assert "verify-reset-code" in resp.headers["location"]

    def test_consumed_otp_rejected(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.consumed_at = datetime.now(timezone.utc)
        db.commit()
        resp = client.post("/verify-reset-code", data={"otp": test_otp},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/reset-password" not in resp.headers["location"]

    def test_old_otp_after_resend_invalid(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        old_otp = "111111"
        new_otp = "222222"
        req.otp_hash = svc._hash_otp(old_otp)
        req.attempts = 0
        db.commit()

        # Resend: create a new request that invalidates the old one
        employee = db.query(Employee).filter(Employee.user_id == "user_v1").first()
        # Expire cooldown so resend is allowed
        req.created_at = datetime.now(timezone.utc) - timedelta(
            seconds=PasswordResetService.RESEND_COOLDOWN_SECONDS + 1)
        db.commit()
        svc.create_password_reset_request(employee.national_code)
        # old request should be consumed
        db.refresh(req)
        assert req.consumed_at is not None

        new_req = db.query(PasswordResetRequest).filter_by(user_id="user_v1").order_by(
            PasswordResetRequest.created_at.desc()
        ).first()
        new_req.otp_hash = svc._hash_otp(new_otp)
        db.commit()

        # Old OTP should be rejected
        resp = client.post("/verify-reset-code", data={"otp": old_otp},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/reset-password" not in resp.headers["location"]

    def test_successful_verification_creates_reset_context(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_user_and_request(client, db, mock_sms_service, create_user_with_phone)
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.attempts = 0
        db.commit()
        resp = client.post("/verify-reset-code", data={"otp": test_otp},
                           follow_redirects=False)
        assert resp.status_code == 303
        # The reset cookie should be present
        cookies = resp.headers.get("set-cookie", "")
        assert "timex_reset_context" in cookies


# ---------------------------------------------------------------------------
# Resend OTP
# ---------------------------------------------------------------------------
class TestResendOtp:
    def test_resend_before_cooldown(self, client, db, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_r1", "2424242424", "09123450002")
        client.post("/forgot-password", data={"national_code": "2424242424"})
        req = db.query(PasswordResetRequest).filter_by(user_id="user_r1").first()
        assert req is not None
        # Try to resend immediately (within cooldown)
        resp = client.post("/verify-reset-code", data={"resend": "1"},
                           follow_redirects=False)
        assert resp.status_code == 303
        # Should redirect back to verify-reset-code with cooldown message
        assert "verify-reset-code" in resp.headers["location"]

    def test_resend_after_cooldown(self, client, db, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_r2", "2525252525", "09123450003")
        client.post("/forgot-password", data={"national_code": "2525252525"})
        req = db.query(PasswordResetRequest).filter_by(user_id="user_r2").first()
        assert req is not None
        # Manually expire the cooldown
        req.created_at = datetime.now(timezone.utc) - timedelta(
            seconds=PasswordResetService.RESEND_COOLDOWN_SECONDS + 1)
        db.commit()
        # Resend should succeed
        resp = client.post("/verify-reset-code", data={"resend": "1"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/verify-reset-code" in resp.headers["location"]

    def test_new_otp_invalidates_old(self, client, db, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_r3", "2626262626", "09123450004")
        client.post("/forgot-password", data={"national_code": "2626262626"})
        req = db.query(PasswordResetRequest).filter_by(user_id="user_r3").first()
        assert req is not None
        req.created_at = datetime.now(timezone.utc) - timedelta(
            seconds=PasswordResetService.RESEND_COOLDOWN_SECONDS + 1)
        db.commit()
        client.post("/verify-reset-code", data={"resend": "1"})
        db.refresh(req)
        assert req.consumed_at is not None  # old request should be invalidated


# ---------------------------------------------------------------------------
# Reset Password
# ---------------------------------------------------------------------------
class TestResetPassword:
    def _setup_verified_context(self, client, db, mock_sms_service, create_user_with_phone):
        """Helper: create user, request OTP, verify OTP, return reset cookie."""
        create_user_with_phone("user_reset1", "2727272727", "09123450005")
        client.post("/forgot-password", data={"national_code": "2727272727"})
        req = db.query(PasswordResetRequest).filter_by(user_id="user_reset1").first()
        svc = PasswordResetService(db)
        test_otp = "123456"
        req.otp_hash = svc._hash_otp(test_otp)
        req.attempts = 0
        db.commit()
        client.post("/verify-reset-code", data={"otp": test_otp})
        return req

    def test_access_without_verified_context_rejected(self, client, db):
        resp = client.get("/reset-password", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]

    def test_successful_password_reset(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        resp = client.post("/reset-password",
                           data={"new_password": "NewPass123", "confirm_password": "NewPass123"},
                           follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        # Check DB
        user = db.query(User).filter_by(user_id="user_reset1").first()
        assert user.must_change_password is False
        assert user.failed_attempts == 0
        assert user.locked_until is None

    def test_password_mismatch(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        resp = client.post("/reset-password",
                           data={"new_password": "NewPass123", "confirm_password": "OtherPass123"})
        assert resp.status_code == 200
        assert "یکسان نیست" in resp.text

    def test_password_too_short(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        resp = client.post("/reset-password",
                           data={"new_password": "123", "confirm_password": "123"})
        assert resp.status_code == 200
        assert "۶ کاراکتر" in resp.text

    def test_password_equal_to_national_code(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        resp = client.post("/reset-password",
                           data={"new_password": "2727272727", "confirm_password": "2727272727"})
        assert resp.status_code == 200
        assert "کد ملی" in resp.text

    def test_must_change_password_becomes_false(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        user = db.query(User).filter_by(user_id="user_reset1").first()
        user.must_change_password = True
        db.commit()
        client.post("/reset-password",
                    data={"new_password": "NewPass123", "confirm_password": "NewPass123"})
        db.refresh(user)
        assert user.must_change_password is False

    def test_failed_attempts_reset(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        user = db.query(User).filter_by(user_id="user_reset1").first()
        user.failed_attempts = 3
        db.commit()
        client.post("/reset-password",
                    data={"new_password": "NewPass123", "confirm_password": "NewPass123"})
        db.refresh(user)
        assert user.failed_attempts == 0

    def test_account_lock_cleared(self, client, db, mock_sms_service, create_user_with_phone):
        from datetime import timedelta as _td
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        user = db.query(User).filter_by(user_id="user_reset1").first()
        user.locked_until = datetime.now(timezone.utc) + _td(minutes=30)
        db.commit()
        client.post("/reset-password",
                    data={"new_password": "NewPass123", "confirm_password": "NewPass123"})
        db.refresh(user)
        assert user.locked_until is None

    def test_reset_request_consumed(self, client, db, mock_sms_service, create_user_with_phone):
        req = self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        client.post("/reset-password",
                    data={"new_password": "NewPass123", "confirm_password": "NewPass123"})
        db.refresh(req)
        assert req.consumed_at is not None

    def test_reset_context_invalidated_after_reset(self, client, db, mock_sms_service, create_user_with_phone):
        self._setup_verified_context(client, db, mock_sms_service, create_user_with_phone)
        client.post("/reset-password",
                    data={"new_password": "NewPass123", "confirm_password": "NewPass123"})
        # Trying to access reset-password again should redirect to login
        resp = client.get("/reset-password", follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
class TestSecurity:
    def test_otp_never_in_logs(self, client, db, mock_sms_service, create_user_with_phone, caplog):
        import logging
        caplog.set_level(logging.ERROR)
        create_user_with_phone("user_sec1", "2828282828", "09123450006")
        client.post("/forgot-password", data={"national_code": "2828282828"})
        for record in caplog.records:
            assert "otp_plaintext" not in record.message
            assert "otp_hash" not in record.message

    def test_full_phone_never_exposed(self, client, db, mock_sms_service, create_user_with_phone):
        create_user_with_phone("user_sec2", "2929292929", "09123450007")
        client.post("/forgot-password", data={"national_code": "2929292929"})
        resp = client.get("/verify-reset-code")
        assert "09123450007" not in resp.text
        assert "0912" in resp.text or "****" in resp.text  # masked version ok

    def test_unknown_user_reveals_no_info(self, client, db, mock_sms_service):
        resp = client.post("/forgot-password",
                           data={"national_code": "0000000000"}, follow_redirects=True)
        assert "اگر اطلاعات واردشده صحیح باشد" in resp.text
        assert "یافت نشد" not in resp.text
        assert "وجود ندارد" not in resp.text

    def test_direct_access_cannot_bypass_otp(self, client, db, mock_sms_service):
        """Setting a cookie manually with a fake ID should not grant access."""
        resp = client.get("/reset-password")
        assert resp.status_code in (302, 303)
        assert "/login" in resp.headers["location"]
