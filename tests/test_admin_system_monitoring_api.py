"""
Phase 5C: Admin Service Monitoring API tests.

Windows SCM and aggregation internals are mocked — no real sc query.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.service_health_status import ServiceHealthStatus
from web.permissions import set_user_permission
from tests.conftest import login_as


def _status(
    service_name: str,
    *,
    process_state: str = "running",
    health_state: str = "healthy",
) -> ServiceHealthStatus:
    now = datetime(2026, 10, 4, 6, 30, 0, tzinfo=timezone.utc)
    return ServiceHealthStatus(
        service_name=service_name,
        process_state=process_state,
        health_state=health_state,
        started_at=now,
        last_heartbeat_at=now,
        last_success_at=now,
        last_error_at=None,
        last_error_code=None,
        last_error_summary=None,
        metrics={"sample": True},
        checked_at=now,
    )


@pytest.fixture
def mock_health(monkeypatch):
    import core.service_health_status as status_mod
    import web.routes.admin_system as route_mod

    statuses = {
        "web": _status("web", process_state="running", health_state="unknown"),
        "adms": _status("adms", process_state="running", health_state="healthy"),
        "bale": _status("bale", process_state="stopped", health_state="offline"),
    }

    def fake_list():
        return [statuses[name] for name in ("web", "adms", "bale")]

    def fake_get(name: str):
        if name not in statuses:
            raise ValueError(name)
        return statuses[name]

    monkeypatch.setattr(status_mod, "list_service_health_statuses", fake_list)
    monkeypatch.setattr(status_mod, "get_service_health_status", fake_get)
    monkeypatch.setattr(route_mod, "list_service_health_statuses", fake_list)
    monkeypatch.setattr(route_mod, "get_service_health_status", fake_get)
    return statuses


def _login_admin(client, make_user, role="admin"):
    creds = make_user(role=role)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def test_list_services_returns_all_three(client, make_user, mock_health):
    _login_admin(client, make_user)
    resp = client.get("/admin/system/services")
    assert resp.status_code == 200
    body = resp.json()
    assert "services" in body
    names = [item["service_name"] for item in body["services"]]
    assert names == ["web", "adms", "bale"]
    by_name = {item["service_name"]: item for item in body["services"]}
    assert by_name["web"]["health_state"] == "unknown"
    assert by_name["adms"]["health_state"] == "healthy"
    assert by_name["bale"]["process_state"] == "stopped"
    assert by_name["bale"]["health_state"] == "offline"


@pytest.mark.parametrize("service_name", ["web", "adms", "bale"])
def test_detail_service_ok(client, make_user, mock_health, service_name):
    _login_admin(client, make_user)
    resp = client.get(f"/admin/system/services/{service_name}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service_name"] == service_name
    assert set(body.keys()) == {
        "service_name",
        "process_state",
        "health_state",
        "started_at",
        "last_heartbeat_at",
        "last_success_at",
        "last_error_at",
        "last_error_code",
        "last_error_summary",
        "metrics",
        "checked_at",
    }
    assert body["started_at"].endswith("+00:00") or body["started_at"].endswith("Z")


def test_invalid_service_returns_404(client, make_user, mock_health):
    _login_admin(client, make_user)
    resp = client.get("/admin/system/services/invalid")
    assert resp.status_code == 404
    assert "traceback" not in resp.text.lower()


def test_permission_denied_for_revoked_admin(client, db, make_user, mock_health):
    creds = make_user(role="admin")
    set_user_permission(
        db, creds["user_id"], "view_system_monitoring", False, created_by="SYS"
    )
    db.commit()
    login_as(client, creds["national_code"])

    resp = client.get("/admin/system/services")
    assert resp.status_code == 403


def test_permission_allowed_for_admin(client, make_user, mock_health):
    _login_admin(client, make_user)
    assert client.get("/admin/system/services").status_code == 200


def test_regular_user_forbidden(client, make_user, mock_health):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.get("/admin/system/services")
    # require_admin → 403 for non-admin
    assert resp.status_code == 403


def test_mocked_scm_states_surface_in_api(client, make_user, monkeypatch):
    import web.routes.admin_system as route_mod

    _login_admin(client, make_user)

    def fake_get(name: str):
        mapping = {
            "web": ("running", "healthy"),
            "adms": ("stopped", "offline"),
            "bale": ("unknown", "unknown"),
        }
        process_state, health_state = mapping[name]
        return _status(name, process_state=process_state, health_state=health_state)

    monkeypatch.setattr(route_mod, "get_service_health_status", fake_get)
    monkeypatch.setattr(
        route_mod,
        "list_service_health_statuses",
        lambda: [fake_get(n) for n in ("web", "adms", "bale")],
    )

    resp = client.get("/admin/system/services")
    assert resp.status_code == 200
    by_name = {item["service_name"]: item for item in resp.json()["services"]}
    assert by_name["web"]["process_state"] == "running"
    assert by_name["adms"]["process_state"] == "stopped"
    assert by_name["bale"]["process_state"] == "unknown"

    detail = client.get("/admin/system/services/adms").json()
    assert detail["health_state"] == "offline"


def test_backend_failure_returns_safe_error(client, make_user, monkeypatch):
    import web.routes.admin_system as route_mod

    _login_admin(client, make_user)
    monkeypatch.setattr(
        route_mod,
        "list_service_health_statuses",
        MagicMock(side_effect=RuntimeError("sc query boom password=secret")),
    )

    resp = client.get("/admin/system/services")
    assert resp.status_code == 500
    text = resp.text.lower()
    assert "password" not in text
    assert "secret" not in text
    assert "traceback" not in text
    assert "sc query" not in text
