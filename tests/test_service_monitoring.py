"""
Phase 2 tests for Monitoring Runtime Core (core.service_monitoring).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from models.service_health import ServiceHealth
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
def _monitoring_uses_test_db(monkeypatch):
    """Point monitoring writer at the isolated test database."""
    import core.service_monitoring as mon

    monkeypatch.setattr(mon, "_session_factory", TestingSessionLocal)
    monkeypatch.setattr(mon, "SessionLocal", TestingSessionLocal)

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


def _get(service_name: str) -> ServiceHealth | None:
    session = TestingSessionLocal()
    try:
        return session.get(ServiceHealth, service_name)
    finally:
        session.close()


def test_record_startup_sets_running_and_timestamps():
    from core.service_monitoring import record_startup

    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert record_startup("web") is True
    after = datetime.now(timezone.utc) + timedelta(seconds=1)

    row = _get("web")
    assert row is not None
    assert row.process_state == "running"
    assert row.health_state == "unknown"
    assert row.started_at is not None
    assert row.last_heartbeat_at is not None
    assert before <= row.started_at <= after
    assert before <= row.last_heartbeat_at <= after
    assert before <= row.updated_at <= after


def test_record_heartbeat_updates_last_heartbeat_only():
    from core.service_monitoring import record_heartbeat, record_startup

    assert record_startup("adms") is True
    first = _get("adms")
    assert first is not None
    started_at = first.started_at
    first_hb = first.last_heartbeat_at

    assert record_heartbeat("adms") is True
    second = _get("adms")
    assert second is not None
    assert second.started_at == started_at
    assert second.process_state == "running"
    assert second.health_state == "unknown"
    assert second.last_heartbeat_at >= first_hb
    assert second.updated_at >= first.updated_at


def test_record_success_updates_last_success_at():
    from core.service_monitoring import record_startup, record_success

    assert record_startup("bale") is True
    assert record_success("bale") is True

    row = _get("bale")
    assert row is not None
    assert row.last_success_at is not None
    assert row.process_state == "running"
    assert row.health_state == "unknown"


def test_record_success_merges_metrics_without_wiping_other_keys():
    import json
    from core.service_monitoring import merge_metrics, record_startup, record_success

    assert record_startup("adms") is True
    assert merge_metrics("adms", {"device_connected": True}) is True
    assert record_success(
        "adms",
        metrics={"last_sync": {"fetched": 3, "inserted": 2, "duplicates": 1, "errors": 0}},
    ) is True

    row = _get("adms")
    metrics = json.loads(row.metrics)
    assert metrics["device_connected"] is True
    assert metrics["last_sync"]["fetched"] == 3


def test_merge_metrics_does_not_change_last_success_at():
    from core.service_monitoring import merge_metrics, record_startup, record_success

    assert record_startup("adms") is True
    assert record_success("adms") is True
    success_at = _get("adms").last_success_at

    assert merge_metrics("adms", {"device_connected": False}) is True
    row = _get("adms")
    assert row.last_success_at == success_at
    assert '"device_connected":false' in row.metrics.replace(" ", "")


def test_record_error_stores_safe_summary():
    from core.service_monitoring import record_error, record_startup

    assert record_startup("web") is True
    assert (
        record_error(
            "web",
            error_code="device_offline",
            error_summary="Device connection timed out",
        )
        is True
    )

    row = _get("web")
    assert row is not None
    assert row.last_error_at is not None
    assert row.last_error_code == "device_offline"
    assert row.last_error_summary == "Device connection timed out"


def test_record_error_strips_traceback_and_secrets():
    from core.service_monitoring import record_error

    messy = (
        "Sync failed\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "password=supersecret token=abc123"
    )
    assert (
        record_error(
            "adms",
            error_code="sync_failed",
            error_summary=messy,
        )
        is True
    )

    row = _get("adms")
    assert row is not None
    assert row.last_error_code == "sync_failed"
    assert "Traceback" not in (row.last_error_summary or "")
    assert "supersecret" not in (row.last_error_summary or "")
    assert "abc123" not in (row.last_error_summary or "")
    assert len(row.last_error_summary or "") <= 500


def test_invalid_service_rejected():
    from core.service_monitoring import record_startup

    with pytest.raises(ValueError, match="Unsupported service_name"):
        record_startup("nginx")


@pytest.mark.parametrize("api_name", [
    "record_startup",
    "record_heartbeat",
    "record_success",
])
def test_invalid_service_rejected_for_all_apis(api_name):
    import core.service_monitoring as mon

    api = getattr(mon, api_name)
    with pytest.raises(ValueError):
        api("not-a-service")


def test_record_error_invalid_service_rejected():
    from core.service_monitoring import record_error

    with pytest.raises(ValueError):
        record_error("not-a-service", error_code="x", error_summary="y")


def test_db_failure_does_not_crash_caller(monkeypatch):
    import core.service_monitoring as mon

    def boom():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(mon, "_session_factory", boom)

    # Must return False, not raise.
    assert mon.record_startup("web") is False
    assert mon.record_heartbeat("web") is False
    assert mon.record_success("web") is False
    assert mon.record_error("web", error_code="x", error_summary="y") is False


def test_db_commit_failure_does_not_crash_caller(monkeypatch):
    import core.service_monitoring as mon

    bad_session = MagicMock()
    bad_session.get.return_value = None
    bad_session.commit.side_effect = RuntimeError("commit path broken")

    monkeypatch.setattr(mon, "_session_factory", lambda: bad_session)

    assert mon.record_heartbeat("adms") is False
    bad_session.rollback.assert_called()
    bad_session.close.assert_called()


def test_startup_then_error_preserves_process_state():
    from core.service_monitoring import record_error, record_startup

    assert record_startup("bale") is True
    assert record_error("bale", error_code="api_timeout", error_summary="timeout") is True

    row = _get("bale")
    assert row is not None
    assert row.process_state == "running"
    assert row.health_state == "unknown"
    assert row.last_error_code == "api_timeout"


def test_ordinary_metrics_unchanged():
    import json
    from core.service_monitoring import merge_metrics, record_startup

    assert record_startup("adms") is True
    payload = {
        "device_connected": True,
        "fetched": 3,
        "inserted": 2,
        "duplicates": 1,
        "errors": 0,
        "consecutive_failures": 0,
        "loop_consecutive_failures": 1,
        "recovery": False,
    }
    assert merge_metrics("adms", payload) is True
    assert json.loads(_get("adms").metrics) == payload


def test_sensitive_metric_keys_are_redacted():
    import json
    from core.service_monitoring import merge_metrics, record_startup

    assert record_startup("web") is True
    assert merge_metrics(
        "web",
        {
            "device_connected": True,
            "token": "abc123",
            "password": "secret-pass",
            "authorization": "Bearer xyz",
            "bearer": "xyz",
            "secret": "top",
            "credential": "cred",
            "otp": "123456",
        },
    ) is True

    metrics = json.loads(_get("web").metrics)
    assert metrics["device_connected"] is True
    for key in (
        "token",
        "password",
        "authorization",
        "bearer",
        "secret",
        "credential",
        "otp",
    ):
        assert metrics[key] == "***"
    text = _get("web").metrics
    assert "abc123" not in text
    assert "secret-pass" not in text
    assert "Bearer xyz" not in text


def test_nested_sensitive_metrics_are_redacted():
    import json
    from core.service_monitoring import merge_metrics, record_startup

    assert record_startup("bale") is True
    assert merge_metrics(
        "bale",
        {
            "bot_connected": True,
            "auth": {"token": "nested-token", "ok": True},
            "last_sync": {"fetched": 1, "password": "nested-pass"},
        },
    ) is True

    metrics = json.loads(_get("bale").metrics)
    assert metrics["bot_connected"] is True
    assert metrics["auth"]["token"] == "***"
    assert metrics["auth"]["ok"] is True
    assert metrics["last_sync"]["fetched"] == 1
    assert metrics["last_sync"]["password"] == "***"
    assert "nested-token" not in _get("bale").metrics
    assert "nested-pass" not in _get("bale").metrics


def test_adms_and_bale_operational_metrics_still_store():
    import json
    from core.service_monitoring import merge_metrics, record_startup, record_success

    assert record_startup("adms") is True
    assert merge_metrics("adms", {"device_connected": True}) is True
    assert record_success(
        "adms",
        metrics={
            "last_sync": {
                "fetched": 5,
                "inserted": 4,
                "duplicates": 1,
                "errors": 0,
            }
        },
    ) is True
    adms = json.loads(_get("adms").metrics)
    assert adms["device_connected"] is True
    assert adms["last_sync"] == {
        "fetched": 5,
        "inserted": 4,
        "duplicates": 1,
        "errors": 0,
    }

    assert record_startup("bale") is True
    assert merge_metrics(
        "bale",
        {
            "bot_connected": True,
            "consecutive_failures": 0,
            "loop_consecutive_failures": 2,
            "recovery": True,
        },
    ) is True
    bale = json.loads(_get("bale").metrics)
    assert bale["bot_connected"] is True
    assert bale["consecutive_failures"] == 0
    assert bale["loop_consecutive_failures"] == 2
    assert bale["recovery"] is True


def test_metrics_size_validation_still_rejects_oversized_patch():
    from core.service_monitoring import merge_metrics, record_startup
    import core.service_monitoring as mon

    assert record_startup("adms") is True
    oversized = {"blob": "x" * (mon._MAX_METRICS_CHARS + 50)}
    assert merge_metrics("adms", oversized) is True
    row = _get("adms")
    assert row.metrics is None
