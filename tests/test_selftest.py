"""Tests for POST /admin/tests/run (background pytest trigger)."""
import json
from pathlib import Path
from types import SimpleNamespace

from web.routes import admin as admin_routes

from .conftest import TEST_RUNNING_MARKER, login_as


def _clear_marker():
    if TEST_RUNNING_MARKER.exists():
        TEST_RUNNING_MARKER.unlink()


def test_run_tests_requires_login(client):
    _clear_marker()
    resp = client.post("/admin/tests/run", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "/login" in resp.headers["location"]


def test_run_tests_forbidden_for_plain_admin(client, make_user):
    _clear_marker()
    creds = make_user(role="admin", balance_al=None)
    login_as(client, creds["national_code"])
    resp = client.post("/admin/tests/run", follow_redirects=False)
    assert resp.status_code == 403


def test_run_tests_starts_background_job(client, make_user, monkeypatch):
    started = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            started["target"] = target

        def start(self):
            started["started"] = True

    monkeypatch.setattr("threading.Thread", FakeThread)
    _clear_marker()
    try:
        creds = make_user(role="super_admin", balance_al=None)
        login_as(client, creds["national_code"])
        resp = client.post("/admin/tests/run", follow_redirects=False)
        assert resp.status_code == 302
        assert "success=tests-started" in resp.headers["location"]
        assert started.get("started") is True
        assert callable(started.get("target"))
    finally:
        _clear_marker()


def test_run_tests_refuses_concurrent_run(client, make_user):
    _clear_marker()
    try:
        TEST_RUNNING_MARKER.parent.mkdir(parents=True, exist_ok=True)
        TEST_RUNNING_MARKER.write_text("running", encoding="utf-8")
        creds = make_user(role="super_admin", balance_al=None)
        login_as(client, creds["national_code"])
        resp = client.post("/admin/tests/run", follow_redirects=False)
        assert resp.status_code == 302
        assert "error=tests-running" in resp.headers["location"]
    finally:
        _clear_marker()


def test_finalize_records_error_when_hook_never_ran(tmp_path):
    """Simulates pytest missing/crashing: marker remains -> visible error JSON."""
    marker = tmp_path / "log" / "test_status.running"
    marker.parent.mkdir(parents=True)
    marker.write_text("running", encoding="utf-8")
    proc = SimpleNamespace(returncode=1, stdout="", stderr="No module named pytest")
    admin_routes._finalize_test_run(tmp_path, proc)
    assert not marker.exists()
    payload = json.loads(
        (tmp_path / "log" / "test_status.json").read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert payload["errors"] == 1
    assert any("pytest" in line for line in payload["failed_tests"])


def test_finalize_keeps_hook_result_when_present(tmp_path):
    """When the hook already wrote the result, finalize must not overwrite it."""
    status = tmp_path / "log" / "test_status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"success": True, "total": 5}),
                      encoding="utf-8")
    # no marker file at all -> nothing to do
    admin_routes._finalize_test_run(tmp_path, None)
    payload = json.loads(status.read_text(encoding="utf-8"))
    assert payload == {"success": True, "total": 5}


def test_write_test_error_produces_banner_payload(tmp_path):
    admin_routes._write_test_error(tmp_path, "boom")
    payload = json.loads(
        (tmp_path / "log" / "test_status.json").read_text(encoding="utf-8"))
    assert payload["success"] is False
    assert payload["failed_tests"] == ["boom"]


def test_read_test_status_never_raises():
    # read_test_status always points at the real project log dir; here we only
    # assert it never raises and returns dict-or-None.
    result = admin_routes.read_test_status()
    assert result is None or isinstance(result, dict)
