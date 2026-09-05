"""Tests for the user dashboard and the admin dashboard (incl. test banner)."""
import json

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
