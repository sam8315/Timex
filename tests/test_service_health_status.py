"""
Phase 5A: Service health aggregation + Windows SCM provider tests.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from models.service_health import SERVICE_NAMES, ServiceHealth
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
def _health_status_uses_test_db(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "_session_factory", TestingSessionLocal)
    # Force provider through injectable runner (no real SCM dependency in tests).
    monkeypatch.setattr(status, "_scm_query_runner", None)

    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()


def _seed_runtime(
    service_name: str,
    *,
    last_heartbeat_at=None,
    last_success_at=None,
    last_error_at=None,
    last_error_code=None,
    last_error_summary=None,
    metrics=None,
    started_at=None,
):
    session = TestingSessionLocal()
    try:
        row = ServiceHealth(
            service_name=service_name,
            process_state="running",
            health_state="unknown",
            started_at=started_at or datetime.now(timezone.utc),
            last_heartbeat_at=last_heartbeat_at,
            last_success_at=last_success_at,
            last_error_at=last_error_at,
            last_error_code=last_error_code,
            last_error_summary=last_error_summary,
            metrics=metrics,
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


def _sc_result(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["sc", "query", "x"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_windows_service_name_mapping():
    from core.service_health_status import WINDOWS_SERVICE_NAME_BY_APP, windows_service_name

    assert WINDOWS_SERVICE_NAME_BY_APP == {
        "web": "web",
        "adms": "ADMS",
        "bale": "BaleBot",
    }
    assert windows_service_name("web") == "web"
    assert windows_service_name("adms") == "ADMS"
    assert windows_service_name("bale") == "BaleBot"


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("SERVICE_NAME: web\n        STATE              : 4  RUNNING\n", "running"),
        ("SERVICE_NAME: ADMS\n        STATE              : 1  STOPPED\n", "stopped"),
        ("SERVICE_NAME: BaleBot\n        STATE              : 2  START_PENDING\n", "unknown"),
        ("", "unknown"),
    ],
)
def test_parse_sc_query_state(stdout, expected):
    from core.service_health_status import _parse_sc_query_state

    assert _parse_sc_query_state(stdout) == expected


def test_get_windows_service_state_running(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(
        status,
        "_scm_query_runner",
        lambda name: _sc_result(
            f"SERVICE_NAME: {name}\n        STATE              : 4  RUNNING\n"
        ),
    )
    assert status.get_windows_service_state("adms") == "running"


def test_get_windows_service_state_stopped(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(
        status,
        "_scm_query_runner",
        lambda name: _sc_result(
            f"SERVICE_NAME: {name}\n        STATE              : 1  STOPPED\n"
        ),
    )
    assert status.get_windows_service_state("web") == "stopped"


def test_get_windows_service_state_query_failure(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(
        status,
        "_scm_query_runner",
        lambda name: _sc_result("The specified service does not exist.", returncode=1060),
    )
    assert status.get_windows_service_state("bale") == "unknown"


def test_get_windows_service_state_exception_returns_unknown(monkeypatch):
    import core.service_health_status as status

    def boom(_name):
        raise OSError("scm unavailable")

    monkeypatch.setattr(status, "_scm_query_runner", boom)
    assert status.get_windows_service_state("web") == "unknown"


def test_stopped_maps_to_offline(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "stopped")
    _seed_runtime("adms", last_heartbeat_at=datetime.now(timezone.utc))

    result = status.get_service_health_status("adms")
    assert result.process_state == "stopped"
    assert result.health_state == "offline"


def test_unknown_scm_maps_to_unknown(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "unknown")
    result = status.get_service_health_status("web")
    assert result.process_state == "unknown"
    assert result.health_state == "unknown"


def test_running_fresh_heartbeat_healthy(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    _seed_runtime("bale", last_heartbeat_at=now - timedelta(seconds=30))

    result = status.get_service_health_status("bale")
    assert result.process_state == "running"
    assert result.health_state == "healthy"


def test_running_stale_heartbeat_degraded(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    stale = datetime.now(timezone.utc) - timedelta(
        seconds=status.HEARTBEAT_TIMEOUT_SECONDS + 30
    )
    _seed_runtime("adms", last_heartbeat_at=stale)

    result = status.get_service_health_status("adms")
    assert result.process_state == "running"
    assert result.health_state == "degraded"


def test_web_stale_startup_heartbeat_not_degraded(monkeypatch):
    """Web has no periodic heartbeat; stale startup heartbeat alone must not degrade."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=status.HEARTBEAT_TIMEOUT_SECONDS + 30)
    _seed_runtime(
        "web",
        started_at=stale,
        last_heartbeat_at=stale,
        last_success_at=stale,
    )

    result = status.get_service_health_status("web")
    assert result.process_state == "running"
    assert result.health_state == "healthy"
    assert result.health_state != "degraded"


def test_web_stale_heartbeat_still_degraded_on_recent_error(monkeypatch):
    """Web exception is only for stale startup heartbeat — recent errors still degrade."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=status.HEARTBEAT_TIMEOUT_SECONDS + 30)
    _seed_runtime(
        "web",
        started_at=stale,
        last_heartbeat_at=stale,
        last_error_at=now - timedelta(seconds=30),
        last_error_code="DB_STARTUP_FAILED",
        last_error_summary="Database startup failed",
    )

    result = status.get_service_health_status("web")
    assert result.process_state == "running"
    assert result.health_state == "degraded"


def test_running_missing_heartbeat_unknown(monkeypatch):
    """Web (and any service) without runtime heartbeat → insufficient evidence."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    _seed_runtime("web", last_heartbeat_at=None)

    result = status.get_service_health_status("web")
    assert result.process_state == "running"
    assert result.health_state == "unknown"


def test_running_missing_row_unknown(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    result = status.get_service_health_status("web")
    assert result.process_state == "running"
    assert result.health_state == "unknown"


def test_running_recent_error_degraded(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    _seed_runtime(
        "bale",
        last_heartbeat_at=now - timedelta(seconds=10),
        last_error_at=now - timedelta(seconds=20),
        last_error_code="BALE_API_FAILED",
        last_error_summary="Bale API getUpdates failed (timeout)",
    )

    result = status.get_service_health_status("bale")
    assert result.health_state == "degraded"
    assert result.last_error_code == "BALE_API_FAILED"


def test_recent_error_without_newer_success_still_degraded(monkeypatch):
    """Recent error with no success after it must keep the service degraded."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    error_at = now - timedelta(seconds=60)
    _seed_runtime(
        "adms",
        last_heartbeat_at=now - timedelta(seconds=10),
        last_error_at=error_at,
        last_success_at=error_at - timedelta(seconds=30),
        last_error_code="DEVICE_SYNC_FAILED",
        last_error_summary="sync failed",
    )

    result = status.get_service_health_status("adms")
    assert result.health_state == "degraded"


def test_recent_error_cleared_by_newer_success(monkeypatch):
    """A success newer than the recent error must not leave health_state degraded."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    _seed_runtime(
        "bale",
        last_heartbeat_at=now - timedelta(seconds=10),
        last_error_at=now - timedelta(seconds=60),
        last_success_at=now - timedelta(seconds=30),
        last_error_code="BALE_API_FAILED",
        last_error_summary="Bale API getUpdates failed (timeout)",
    )

    result = status.get_service_health_status("bale")
    assert result.health_state == "healthy"


def test_web_recent_error_cleared_by_newer_success(monkeypatch):
    """Web recovery: newer success supersedes a recent error (startup heartbeat OK)."""
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    started = now - timedelta(seconds=status.HEARTBEAT_TIMEOUT_SECONDS + 30)
    _seed_runtime(
        "web",
        started_at=started,
        last_heartbeat_at=started,
        last_error_at=now - timedelta(seconds=60),
        last_success_at=now - timedelta(seconds=30),
        last_error_code="DB_STARTUP_FAILED",
        last_error_summary="Database startup failed",
    )

    result = status.get_service_health_status("web")
    assert result.health_state == "healthy"


def test_running_old_error_still_healthy(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    _seed_runtime(
        "bale",
        last_heartbeat_at=now - timedelta(seconds=10),
        last_error_at=now - timedelta(seconds=status.RECENT_ERROR_WINDOW_SECONDS + 60),
        last_error_code="BALE_API_FAILED",
        last_error_summary="old",
    )

    result = status.get_service_health_status("bale")
    assert result.health_state == "healthy"


def test_db_failure_returns_safe_unknown(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(status, "_session_factory", boom)

    result = status.get_service_health_status("adms")
    assert result.process_state == "running"
    assert result.health_state == "unknown"
    assert result.last_heartbeat_at is None


def test_list_service_health_statuses(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "stopped")
    results = status.list_service_health_statuses()
    assert [r.service_name for r in results] == list(SERVICE_NAMES)
    assert all(r.health_state == "offline" for r in results)


def test_result_contract_and_no_secrets(monkeypatch):
    import core.service_health_status as status

    monkeypatch.setattr(status, "get_windows_service_state", lambda _n: "running")
    now = datetime.now(timezone.utc)
    _seed_runtime(
        "adms",
        last_heartbeat_at=now,
        last_success_at=now,
        last_error_code="SYNC_FAILED",
        last_error_summary="Attendance synchronization failed",
        metrics=json.dumps(
            {
                "last_sync": {"fetched": 1, "inserted": 1, "duplicates": 0, "errors": 0},
                "device_connected": True,
            }
        ),
    )

    result = status.get_service_health_status("adms")
    payload = {
        "service_name": result.service_name,
        "process_state": result.process_state,
        "health_state": result.health_state,
        "started_at": result.started_at,
        "last_heartbeat_at": result.last_heartbeat_at,
        "last_success_at": result.last_success_at,
        "last_error_at": result.last_error_at,
        "last_error_code": result.last_error_code,
        "last_error_summary": result.last_error_summary,
        "metrics": result.metrics,
        "checked_at": result.checked_at,
    }
    blob = json.dumps(payload, default=str).lower()
    assert "token" not in blob
    assert "password" not in blob
    assert "traceback" not in blob
    assert "authorization" not in blob
    assert result.metrics["last_sync"]["fetched"] == 1


def test_invalid_service_rejected():
    from core.service_health_status import get_service_health_status

    with pytest.raises(ValueError):
        get_service_health_status("nginx")
