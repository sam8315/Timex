import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone
from models.password_reset import PasswordResetRequest
from web.services.password_reset_service import PasswordResetService


@pytest.fixture
def mock_sms_service():
    """Mock SmsService to prevent actual SMS sends"""
    with patch('web.services.password_reset_service.SmsService') as MockSmsService:
        instance = MockSmsService.return_value
        instance.send_sms.return_value = {"success": True}
        yield instance


@pytest.fixture
def create_user_with_phone(db):
    def _create(user_id, national_code, phone_number, is_default=True):
        user = User(
            user_id=user_id,
            name="Test User",
            password_hash="test_hash",
            web_enabled=True
        )
        db.add(user)
        employee = Employee(
            user_id=user_id,
            national_code=national_code,
            first_name="Test",
            last_name="User"
        )
        db.add(employee)
        phone = EmployeePhone(
            user_id=user_id,
            phone_number=phone_number,
            is_default=is_default
        )
        db.add(phone)
        db.commit()
        db.refresh(user)
        db.refresh(employee)
        db.refresh(phone)
        return user, employee, phone
    return _create


class TestPasswordResetFixes:
    """Test all three password reset fixes"""

    def test_fix1_masked_phone_direction_uses_ltr(self, db, create_user_with_phone, mock_sms_service):
        """Test that masked phone number renders with dir='ltr'"""
        user, _, _ = create_user_with_phone("test_user", "1234567890", "09123456789")
        
        svc = PasswordResetService(db)
        success, message = svc.create_password_reset_request("1234567890")
        assert success is True
        
        request = db.query(PasswordResetRequest).filter_by(user_id="test_user").first()
        assert request is not None
        
        # Get the masked phone
        from web.routes.auth import _mask_phone
        masked_phone = _mask_phone(request.phone_number)
        assert "09123456789" not in masked_phone
        assert masked_phone.startswith("0912")
        assert "***" in masked_phone
        assert masked_phone.endswith("6789")

    def test_fix2_resend_cooldown_is_120_seconds(self):
        """Test that RESEND_COOLDOWN_SECONDS is 120"""
        assert PasswordResetService.RESEND_COOLDOWN_SECONDS == 120

    def test_fix2_resend_rejected_before_120_seconds(self, db, create_user_with_phone, mock_sms_service):
        """Test that immediate resend is rejected with new 120s cooldown"""
        user, _, _ = create_user_with_phone("test_user2", "1111111111", "09111111111")
        
        svc = PasswordResetService(db)
        success1, _ = svc.create_password_reset_request("1111111111")
        assert success1 is True
        
        # Try to resend immediately (should be rejected)
        mock_sms_service.send_sms.reset_mock()
        success2, message2 = svc.create_password_reset_request("1111111111")
        assert success2 is False
        assert "ثانیه صبر کنید" in message2
        mock_sms_service.send_sms.assert_not_called()
        
        # Verify it would work after 120 seconds
        last_request = db.query(PasswordResetRequest).filter_by(user_id="test_user2").order_by(
            PasswordResetRequest.created_at.desc()).first()
        
        if last_request:
            last_request.created_at = datetime.now(timezone.utc) - timedelta(seconds=PasswordResetService.RESEND_COOLDOWN_SECONDS + 1)
            db.commit()
        
        success3, _ = svc.create_password_reset_request("1111111111")
        assert success3 is True
        mock_sms_service.send_sms.assert_called_once()

    def test_fix3_login_page_displays_success_message(self, client):
        """Test that login page displays success message from query parameter"""
        # Test without message (normal login page)
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "بازیابی رمز عبور" not in resp.text  # Success message should not appear
        
        # Test with success message (from password reset redirect)
        resp = client.get("/login?msg=رمز عبور با موفقیت تغییر کرد. لطفاً وارد شوید.")
        assert resp.status_code == 200
        assert "رمز عبور با موفقیت تغییر کرد. لطفاً وارد شوید." in resp.text
        assert "alert-success" in resp.text