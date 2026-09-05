"""Tests for POST /admin/tests/run (background pytest trigger)."""
from pathlib import Path

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
