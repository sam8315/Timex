"""Tests for the SMS notification toggle (leave approve/reject only)."""
from urllib.parse import unquote

from models.employee_phone import EmployeePhone
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.policy import Policy, PolicyValue
from web.services.notification_service import (
    SMS_ENABLED_KEY,
    SMS_POLICY_CATEGORY,
    is_sms_enabled,
    set_sms_enabled,
)
from .conftest import jalali_range, login_as

import jdatetime


def _reset_sms_policy(db):
    """Remove notification-policy rows so each test starts from the default."""
    policy_ids = [p.id for p in db.query(Policy).filter(
        Policy.category == SMS_POLICY_CATEGORY).all()]
    if policy_ids:
        db.query(PolicyValue).filter(
            PolicyValue.policy_id.in_(policy_ids)).delete(
                synchronize_session=False)
        db.query(Policy).filter(
            Policy.category == SMS_POLICY_CATEGORY).delete(
                synchronize_session=False)
        db.commit()


def _add_phone(db, user_id):
    db.add(EmployeePhone(user_id=user_id, phone_number="09120000000",
                         is_default=True))
    db.commit()


def test_sms_enabled_by_default(db):
    _reset_sms_policy(db)
    assert is_sms_enabled(db) is True


def test_set_sms_enabled_roundtrip(db):
    _reset_sms_policy(db)
    try:
        assert set_sms_enabled(db, False, changed_by="TEST") is False
        db.expire_all()
        assert is_sms_enabled(db) is False
        assert set_sms_enabled(db, True, changed_by="TEST") is True
        db.expire_all()
        assert is_sms_enabled(db) is True
    finally:
        _reset_sms_policy(db)


def _submit_and_get_request(client, db, user, start_offset):
    from_str, to_str = jalali_range(start_offset, 2)
    resp = client.post(
        "/leave/request",
        data={"leave_type": "AL", "from_date_str": from_str,
              "to_date_str": to_str, "reason": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    return db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()


def test_approve_skips_sms_when_disabled(client, db, make_user, monkeypatch):
    from web.routes import admin_leave

    _reset_sms_policy(db)
    try:
        set_sms_enabled(db, False, changed_by="TEST")
        user = make_user(role="user", balance_al=30)
        admin = make_user(role="super_admin", balance_al=None)
        _add_phone(db, user["user_id"])

        login_as(client, user["national_code"])
        row = _submit_and_get_request(client, db, user, 50)
        days = row.days_count

        calls = []
        monkeypatch.setattr(
            admin_leave, "_send_sms_async",
            lambda phones, message, user_id: calls.append(
                (phones, message, user_id)),
        )
        client.get("/logout", follow_redirects=False)
        login_as(client, admin["national_code"])
        resp = client.post(f"/admin/leave-requests/{row.id}/approve",
                           follow_redirects=False)
        assert resp.status_code == 302
        assert calls == []
        assert "پیامک" not in unquote(resp.headers["location"])
        db.expire_all()
        assert db.query(LeaveRequest).filter(
            LeaveRequest.id == row.id).first().status == "A"
        year_j = jdatetime.date.today().year
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.year == year_j,
            LeaveBalance.leave_type == "AL").first().balance
        assert balance == 30 - days
    finally:
        _reset_sms_policy(db)


def test_approve_sends_sms_when_enabled(client, db, make_user, monkeypatch):
    from web.routes import admin_leave

    _reset_sms_policy(db)
    try:
        set_sms_enabled(db, True, changed_by="TEST")
        user = make_user(role="user", balance_al=30)
        admin = make_user(role="super_admin", balance_al=None)
        _add_phone(db, user["user_id"])

        login_as(client, user["national_code"])
        row = _submit_and_get_request(client, db, user, 55)

        calls = []
        monkeypatch.setattr(
            admin_leave, "_send_sms_async",
            lambda phones, message, user_id: calls.append(
                (phones, message, user_id)),
        )
        client.get("/logout", follow_redirects=False)
        login_as(client, admin["national_code"])
        resp = client.post(f"/admin/leave-requests/{row.id}/approve",
                           follow_redirects=False)
        assert resp.status_code == 302
        assert len(calls) == 1
        assert calls[0][0] == ["09120000000"]
        assert calls[0][2] == user["user_id"]
        assert "پیامک" in unquote(resp.headers["location"])
    finally:
        _reset_sms_policy(db)


def test_reject_skips_sms_when_disabled(client, db, make_user, monkeypatch):
    from web.routes import admin_leave

    _reset_sms_policy(db)
    try:
        set_sms_enabled(db, False, changed_by="TEST")
        user = make_user(role="user", balance_al=30)
        admin = make_user(role="super_admin", balance_al=None)
        _add_phone(db, user["user_id"])

        login_as(client, user["national_code"])
        row = _submit_and_get_request(client, db, user, 60)

        calls = []
        monkeypatch.setattr(
            admin_leave, "_send_sms_async",
            lambda phones, message, user_id: calls.append(True),
        )
        client.get("/logout", follow_redirects=False)
        login_as(client, admin["national_code"])
        resp = client.post(
            f"/admin/leave-requests/{row.id}/reject",
            data={"rejection_reason": "تست"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert calls == []
    finally:
        _reset_sms_policy(db)


def test_sms_settings_page_and_save(client, db, make_user):
    _reset_sms_policy(db)
    try:
        creds = make_user(role="super_admin", balance_al=None)
        login_as(client, creds["national_code"])
        page = client.get("/admin/policies/sms")
        assert page.status_code == 200
        assert "پیامک" in page.text

        resp = client.post("/admin/policies/sms/save",
                           data={"enabled": "false"},
                           follow_redirects=False)
        assert resp.status_code == 302
        db.expire_all()
        assert is_sms_enabled(db) is False

        resp = client.post("/admin/policies/sms/save",
                           data={"enabled": "true"},
                           follow_redirects=False)
        assert resp.status_code == 302
        db.expire_all()
        assert is_sms_enabled(db) is True
    finally:
        _reset_sms_policy(db)


def test_sms_settings_forbidden_for_plain_admin(client, make_user):
    creds = make_user(role="admin", balance_al=None)
    login_as(client, creds["national_code"])
    assert client.get("/admin/policies/sms",
                      follow_redirects=False).status_code == 403
    assert client.post("/admin/policies/sms/save",
                       data={"enabled": "false"},
                       follow_redirects=False).status_code == 403


def test_policies_dashboard_shows_sms_state(client, db, make_user):
    _reset_sms_policy(db)
    try:
        set_sms_enabled(db, False, changed_by="TEST")
        creds = make_user(role="super_admin", balance_al=None)
        login_as(client, creds["national_code"])
        resp = client.get("/admin/policies")
        assert resp.status_code == 200
        assert "غیرفعال" in resp.text
    finally:
        _reset_sms_policy(db)
