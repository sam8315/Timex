"""
Phase 6: Admin Service Monitoring UI tests.
"""
import re

import pytest

from web.permissions import set_user_permission
from tests.conftest import login_as


def _login_admin(client, make_user, role="admin"):
    creds = make_user(role=role)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def test_page_loads_for_admin_with_permission(client, make_user):
    _login_admin(client, make_user)
    resp = client.get("/admin/system")
    assert resp.status_code == 200
    text = resp.text
    assert "وضعیت سرویس‌ها" in text
    assert "/admin/system/services" in text
    assert "بروزرسانی" in text
    assert "در حال دریافت وضعیت سرویس‌ها" in text
    assert "خطا در دریافت وضعیت سرویس‌ها" in text


def test_page_forbidden_without_permission(client, db, make_user):
    creds = make_user(role="admin")
    set_user_permission(
        db, creds["user_id"], "view_system_monitoring", False, created_by="SYS"
    )
    db.commit()
    login_as(client, creds["national_code"])
    assert client.get("/admin/system").status_code == 403


def test_page_forbidden_for_regular_user(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    assert client.get("/admin/system").status_code == 403


def test_health_state_labels_present_in_ui_script(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    for label in ("Healthy", "Degraded", "Offline", "Failed", "Unknown"):
        assert label in text
    for process in ("Running", "Stopped"):
        assert process in text


def test_adms_metric_fields_wired_in_ui(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert "device_connected" in text
    assert "last_device_connection_at" in text
    assert "last_sync.fetched" in text
    assert "last_sync.inserted" in text
    assert "last_sync.duplicates" in text
    assert "last_sync.errors" in text
    assert "Fetched" in text
    assert "Inserted" in text
    assert "Duplicates" in text


def test_bale_metric_fields_wired_in_ui(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert "bot_connected" in text
    assert "consecutive_failures" in text
    assert "loop_consecutive_failures" in text
    assert "recovery" in text
    assert "Last poll" in text
    assert "Consecutive failures" in text


def test_missing_value_placeholder_and_safe_helpers(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert 'const EMPTY = "—"' in text or "const EMPTY = '—'" in text
    assert "function displayValue" in text
    assert "function metric" in text
    # Missing metrics must not throw — guarded access exists.
    assert '!(parts[i] in cur)' in text or "parts[i] in cur" in text


def test_api_failure_message_is_friendly(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert "خطا در دریافت وضعیت سرویس‌ها" in text
    # Error UI must stay operator-safe (no backend dump in the monitoring block).
    error_block = text.split('id="svcError"', 1)[1].split("</div>", 2)[0]
    assert "traceback" not in error_block.lower()
    assert "exception" not in error_block.lower()
    assert "sql" not in error_block.lower()


def test_auto_refresh_interval_and_no_duplicate_timer_pattern(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert "const REFRESH_MS = 30000" in text
    assert "setInterval(loadServices, REFRESH_MS)" in text
    assert "clearInterval(refreshTimer)" in text
    # startAutoRefresh clears previous timer before creating a new one
    assert re.search(
        r"function startAutoRefresh\(\)\s*\{[^}]*clearInterval\(refreshTimer\)",
        text,
        re.S,
    )


def test_sidebar_link_present_for_admin(client, make_user):
    _login_admin(client, make_user)
    text = client.get("/admin/system").text
    assert 'href="/admin/system"' in text
    assert "وضعیت سرویس‌ها" in text


def _assert_sidebar_monitoring_link_visible(text: str):
    assert 'href="/admin/system"' in text
    assert "bi-heart-pulse" in text
    assert "وضعیت سرویس‌ها" in text


def test_sidebar_monitoring_link_shown_when_permission_present(client, make_user):
    """Permission granted → sidebar link visible on multiple admin pages."""
    _login_admin(client, make_user)
    for path in ("/admin", "/admin/users", "/admin/system"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        _assert_sidebar_monitoring_link_visible(resp.text)


def test_sidebar_monitoring_link_hidden_when_permission_absent(client, db, make_user):
    """Permission denied → sidebar link hidden on admin pages that still render."""
    creds = make_user(role="admin")
    set_user_permission(
        db, creds["user_id"], "view_system_monitoring", False, created_by="SYS"
    )
    db.commit()
    login_as(client, creds["national_code"])
    resp = client.get("/admin")
    assert resp.status_code == 200
    text = resp.text
    assert "bi-heart-pulse" not in text
    assert 'href="/admin/system"' not in text
