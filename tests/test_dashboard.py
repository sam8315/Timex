"""Tests for the user dashboard and the admin dashboard (incl. test banner)."""
import json
from datetime import date, timedelta

from models.contract import Contract
from models.employee import Employee

from .conftest import TEST_STATUS_PATH, login_as


def test_user_dashboard_loads(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "داشبورد" in resp.text or "مرخصی" in resp.text


def test_admin_dashboard_loads_for_admin(client, make_user):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "داشبورد مدیریت" in resp.text


def test_admin_dashboard_forbidden_for_plain_user(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 403


def test_admin_dashboard_shows_test_status_banner(client, make_user):
    """The dashboard must always display the automated-test status message."""
    creds = make_user(role="super_admin")
    login_as(client, creds["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "وضعیت تست" in resp.text


def test_admin_dashboard_banner_renders_last_run(client, make_user):
    """Banner reflects the content of log/test_status.json."""
    backup = None
    if TEST_STATUS_PATH.exists():
        backup = TEST_STATUS_PATH.read_text(encoding="utf-8")
    try:
        TEST_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEST_STATUS_PATH.write_text(
            json.dumps({
                "ran_at": "2026-01-01T10:00:00",
                "ran_at_j": "1404/10/11 10:00",
                "duration_s": 12.5,
                "total": 10,
                "passed": 9,
                "failed": 1,
                "errors": 0,
                "skipped": 0,
                "success": False,
                "failed_tests": ["tests/test_x.py::test_y"],
                "args": ["tests"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        creds = make_user(role="super_admin")
        login_as(client, creds["national_code"])
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "9" in resp.text
        assert "tests/test_x.py::test_y" in resp.text
    finally:
        if backup is None:
            if TEST_STATUS_PATH.exists():
                TEST_STATUS_PATH.unlink()
        else:
            TEST_STATUS_PATH.write_text(backup, encoding="utf-8")


def test_admin_dashboard_banner_shows_error_details(client, make_user):
    """The banner must render the captured error text when present."""
    backup = None
    if TEST_STATUS_PATH.exists():
        backup = TEST_STATUS_PATH.read_text(encoding="utf-8")
    try:
        TEST_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEST_STATUS_PATH.write_text(
            json.dumps({
                "ran_at": "2026-01-01T10:00:00",
                "ran_at_j": "1404/10/11 10:00",
                "duration_s": 3.3,
                "total": 5,
                "passed": 4,
                "failed": 0,
                "errors": 1,
                "skipped": 0,
                "success": False,
                "failed_tests": ["tests/test_x.py::test_y"],
                "error_details": ["E   RuntimeError: marker-boom"],
                "args": ["tests"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        creds = make_user(role="super_admin")
        login_as(client, creds["national_code"])
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "marker-boom" in resp.text
    finally:
        if backup is None:
            if TEST_STATUS_PATH.exists():
                TEST_STATUS_PATH.unlink()
        else:
            TEST_STATUS_PATH.write_text(backup, encoding="utf-8")


def test_admin_dashboard_contract_breakdown_shows_membership_name(client, make_user):
    """نوع عضویت در نوار تفکیک قرارداد باید نام باشد، نه دیکشنری Rule."""
    creds = make_user(role="admin", department="4")
    login_as(client, creds["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "تفکیک قرارداد" in resp.text
    assert "قراردادی:" in resp.text
    assert "annual_leave_base" not in resp.text
    assert "supports_positive_seniority" not in resp.text


def test_admin_dashboard_shows_active_employees_without_contract(client, db, make_user):
    """Active employees with no covering contract appear on the alert card and in its modal."""
    admin = make_user(role="admin")
    missing = make_user(role="user")
    covered = make_user(role="user")
    inactive = make_user(role="user")
    expired = make_user(role="user")

    db.query(Contract).filter(Contract.user_id == missing["user_id"]).delete()
    db.query(Contract).filter(Contract.user_id == inactive["user_id"]).delete()
    inactive_emp = db.query(Employee).filter(Employee.user_id == inactive["user_id"]).one()
    inactive_emp.is_active = False
    expired_contract = db.query(Contract).filter(Contract.user_id == expired["user_id"]).one()
    expired_contract.end_date = date.today() - timedelta(days=1)
    db.commit()

    missing_emp = db.query(Employee).filter(Employee.user_id == missing["user_id"]).one()
    expired_emp = db.query(Employee).filter(Employee.user_id == expired["user_id"]).one()

    login_as(client, admin["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "فعال بدون قرارداد" in resp.text
    assert f'data-missing-contract="{missing["user_id"]}"' in resp.text
    assert missing_emp.full_name in resp.text
    assert "بدون قرارداد" in resp.text
    assert f'href="/admin/profile/{missing["user_id"]}"' in resp.text
    assert f'href="/admin/contracts/user/{missing["user_id"]}"' in resp.text
    assert f'data-missing-contract="{expired["user_id"]}"' in resp.text
    assert expired_emp.full_name in resp.text
    assert "منقضی" in resp.text
    assert f'data-missing-contract="{covered["user_id"]}"' not in resp.text
    assert f'data-missing-contract="{inactive["user_id"]}"' not in resp.text
    assert f'data-missing-contract="{admin["user_id"]}"' not in resp.text
    assert f'/admin/users/{missing["user_id"]}/deactivate' not in resp.text


def test_admin_dashboard_expiring_contracts_open_in_popup(client, db, make_user):
    """Contracts ending within 30 days are listed in the expiring-contract popup."""
    admin = make_user(role="admin")
    soon = make_user(role="user")
    later = make_user(role="user")
    ended = make_user(role="user")

    soon_contract = db.query(Contract).filter(Contract.user_id == soon["user_id"]).one()
    soon_contract.end_date = date.today() + timedelta(days=10)
    later_contract = db.query(Contract).filter(Contract.user_id == later["user_id"]).one()
    later_contract.end_date = date.today() + timedelta(days=40)
    ended_contract = db.query(Contract).filter(Contract.user_id == ended["user_id"]).one()
    ended_contract.end_date = date.today() - timedelta(days=1)
    db.commit()

    soon_emp = db.query(Employee).filter(Employee.user_id == soon["user_id"]).one()
    login_as(client, admin["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "قرارداد رو به انقضا (30 روز)" in resp.text
    assert 'data-bs-target="#expiringContractModal"' in resp.text
    assert f'data-expiring-contract="{soon["user_id"]}"' in resp.text
    assert soon_emp.full_name in resp.text
    assert f'href="/admin/contracts/user/{soon["user_id"]}"' in resp.text
    assert f'data-expiring-contract="{later["user_id"]}"' not in resp.text
    assert f'data-expiring-contract="{ended["user_id"]}"' not in resp.text
    assert f'data-expiring-contract="{admin["user_id"]}"' not in resp.text


def test_dashboard_deactivate_removes_employee_without_contract(client, db, make_user):
    """Super admin can deactivate a listed employee from the missing-contract popup."""
    admin = make_user(role="super_admin")
    missing = make_user(role="user")
    db.query(Contract).filter(Contract.user_id == missing["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    page = client.get("/admin")
    assert page.status_code == 200
    assert f'action="/admin/users/{missing["user_id"]}/deactivate"' in page.text

    posted = client.post(f"/admin/users/{missing['user_id']}/deactivate")
    assert posted.status_code == 302
    assert "success=employee-deactivated" in posted.headers["location"]
    assert "open=missing-contracts" in posted.headers["location"]

    db.expire_all()
    employee = db.query(Employee).filter(Employee.user_id == missing["user_id"]).one()
    assert employee.is_active is False

    again = client.get("/admin")
    assert f'data-missing-contract="{missing["user_id"]}"' not in again.text


def test_dashboard_deactivate_requires_edit_profile(client, db, make_user):
    admin = make_user(role="admin")
    missing = make_user(role="user")
    db.query(Contract).filter(Contract.user_id == missing["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    posted = client.post(f"/admin/users/{missing['user_id']}/deactivate")
    assert posted.status_code == 403

    db.expire_all()
    employee = db.query(Employee).filter(Employee.user_id == missing["user_id"]).one()
    assert employee.is_active is True


def test_admin_dashboard_banner_empty_state(client, make_user):
    """Without any prior run the banner must say tests never ran."""
    backup = None
    if TEST_STATUS_PATH.exists():
        backup = TEST_STATUS_PATH.read_text(encoding="utf-8")
        TEST_STATUS_PATH.unlink()
    try:
        creds = make_user(role="super_admin")
        login_as(client, creds["national_code"])
        resp = client.get("/admin")
        assert resp.status_code == 200
        assert "اجرا نشده" in resp.text
    finally:
        if backup is not None:
            TEST_STATUS_PATH.write_text(backup, encoding="utf-8")
