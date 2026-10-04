"""
Phase 3: ADMS Service Monitoring instrumentation tests.
"""
import importlib
import json
from unittest.mock import MagicMock

import pytest

from models.service_health import ServiceHealth
from tests.conftest import TestingSessionLocal


def _patch_db_session_local(monkeypatch, factory):
    """Patch database.engine.SessionLocal without hitting database.engine object."""
    engine_mod = importlib.import_module("database.engine")
    monkeypatch.setattr(engine_mod, "SessionLocal", factory)


@pytest.fixture(autouse=True)
def _monitoring_uses_test_db(monkeypatch):
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


def _get_adms() -> ServiceHealth | None:
    session = TestingSessionLocal()
    try:
        return session.get(ServiceHealth, "adms")
    finally:
        session.close()


def _metrics(row: ServiceHealth | None) -> dict:
    if row is None or not row.metrics:
        return {}
    return json.loads(row.metrics)


def test_adms_startup_sets_running_and_started_at():
    from core.service_monitoring import record_startup

    assert record_startup("adms") is True
    row = _get_adms()
    assert row is not None
    assert row.process_state == "running"
    assert row.health_state == "unknown"
    assert row.started_at is not None
    assert row.last_heartbeat_at is not None


def test_monitor_loop_records_heartbeat(monkeypatch):
    import run_adms

    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise StopIteration

    fake_manager = MagicMock()
    fake_manager.connect.return_value = False
    fake_manager.disconnect.return_value = None

    monkeypatch.setattr(run_adms.time, "sleep", fake_sleep)
    monkeypatch.setattr(run_adms, "DeviceManager", lambda **kwargs: fake_manager)
    monkeypatch.setattr(run_adms, "record_startup", lambda *_a, **_k: True)

    with pytest.raises(StopIteration):
        run_adms.monitor_device_connection("127.0.0.1", 4370, check_interval=60)

    row = _get_adms()
    assert row is not None
    assert row.last_heartbeat_at is not None


def test_successful_sync_updates_last_success_and_metrics(monkeypatch):
    from core.device_manager import DeviceManager
    from core.service_monitoring import record_startup

    record_startup("adms")
    before = _get_adms().last_success_at

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.conn = MagicMock()
    manager.conn.get_attendance.return_value = []
    manager.conn.disconnect = MagicMock()

    # Avoid real DB attendance queries by short-circuiting empty-device success path
    # after last_record lookup — stub SessionLocal used inside sync.
    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    _patch_db_session_local(monkeypatch, MagicMock(return_value=fake_db))

    result = manager.sync_attendance_to_db(dry_run_first=False)
    assert "error" not in result

    row = _get_adms()
    assert row is not None
    assert row.last_success_at is not None
    if before is not None:
        assert row.last_success_at >= before

    metrics = _metrics(row)
    assert metrics["last_sync"] == {
        "fetched": 0,
        "inserted": 0,
        "duplicates": 0,
        "errors": 0,
    }


def test_sync_metrics_from_stats(monkeypatch):
    from core.device_manager import _monitor_sync_success
    from core.service_monitoring import record_startup

    record_startup("adms")
    _monitor_sync_success(
        {
            "total_fetched": 120,
            "inserted": 118,
            "skipped_duplicates": 2,
            "errors": 0,
        }
    )

    metrics = _metrics(_get_adms())
    assert metrics["last_sync"]["fetched"] == 120
    assert metrics["last_sync"]["inserted"] == 118
    assert metrics["last_sync"]["duplicates"] == 2
    assert metrics["last_sync"]["errors"] == 0
    assert "attendance" not in json.dumps(metrics).lower()


def test_device_connection_updates_metrics_not_last_success(monkeypatch):
    from core.device_manager import DeviceManager
    from core.service_monitoring import record_startup, record_success

    record_startup("adms")
    record_success("adms")
    success_at = _get_adms().last_success_at

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.zk = MagicMock()
    manager.zk.connect.return_value = MagicMock()

    assert manager.connect() is True

    row = _get_adms()
    assert row.last_success_at == success_at
    metrics = _metrics(row)
    assert metrics["device_connected"] is True
    assert metrics.get("last_device_connection_at")


def test_connection_failure_records_device_connection_failed(monkeypatch):
    from core.device_manager import DeviceManager

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.zk = MagicMock()
    manager.zk.connect.side_effect = OSError("refused")

    assert manager.connect() is False

    row = _get_adms()
    assert row is not None
    assert row.last_error_code == "DEVICE_CONNECTION_FAILED"
    assert "traceback" not in (row.last_error_summary or "").lower()
    assert _metrics(row)["device_connected"] is False
    assert row.last_success_at is None


def test_sync_failure_records_sync_failed(monkeypatch):
    from core.device_manager import DeviceManager
    from core.service_monitoring import record_startup

    record_startup("adms")

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.conn = MagicMock()
    manager.conn.get_attendance.side_effect = RuntimeError("boom")
    manager.conn.disconnect = MagicMock()

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    _patch_db_session_local(monkeypatch, MagicMock(return_value=fake_db))

    result = manager.sync_attendance_to_db(dry_run_first=False)
    assert "error" not in result  # current sync API returns stats after general failure

    row = _get_adms()
    assert row.last_error_code == "SYNC_FAILED"
    assert row.last_success_at is None


def test_monitoring_failure_does_not_break_connect(monkeypatch):
    from core.device_manager import DeviceManager
    import core.service_monitoring as mon

    def boom(*_a, **_k):
        raise RuntimeError("monitoring db down")

    monkeypatch.setattr(mon, "merge_metrics", boom)
    monkeypatch.setattr(mon, "record_error", boom)

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.zk = MagicMock()
    manager.zk.connect.return_value = MagicMock()

    assert manager.connect() is True


def test_monitoring_failure_does_not_break_successful_sync(monkeypatch):
    from core.device_manager import DeviceManager
    import core.service_monitoring as mon

    monkeypatch.setattr(
        mon, "record_success", MagicMock(side_effect=RuntimeError("db down"))
    )

    manager = DeviceManager(ip="127.0.0.1", port=4370)
    manager.conn = MagicMock()
    manager.conn.get_attendance.return_value = []
    manager.conn.disconnect = MagicMock()

    fake_db = MagicMock()
    fake_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    _patch_db_session_local(monkeypatch, MagicMock(return_value=fake_db))

    result = manager.sync_attendance_to_db(dry_run_first=False)
    assert "error" not in result
    assert result.get("total_fetched") == 0


def test_initial_sync_does_not_double_record_success(monkeypatch):
    import run_adms
    from core.service_monitoring import record_startup

    record_startup("adms")
    success_calls = {"n": 0}

    def counting_success(*_a, **_k):
        success_calls["n"] += 1
        return True

    monkeypatch.setattr(
        "core.service_monitoring.record_success",
        counting_success,
    )

    fake_manager = MagicMock()
    fake_manager.connect.return_value = True
    fake_manager.sync_attendance_to_db.return_value = {
        "total_fetched": 1,
        "inserted": 1,
        "skipped_duplicates": 0,
        "errors": 0,
        "duration_ms": 10,
    }
    monkeypatch.setattr(run_adms, "DeviceManager", lambda **kwargs: fake_manager)

    # perform_initial_sync must not call record_success itself.
    run_adms.perform_initial_sync("127.0.0.1", 4370)
    assert success_calls["n"] == 0
    fake_manager.sync_attendance_to_db.assert_called_once()


def test_sync_success_metrics_contain_no_sensitive_payload():
    from core.device_manager import _monitor_sync_success
    from core.service_monitoring import record_startup

    record_startup("adms")
    _monitor_sync_success(
        {
            "total_fetched": 2,
            "inserted": 1,
            "skipped_duplicates": 1,
            "errors": 0,
            "password": "secret",
            "rows": [{"user_id": "1", "card": "9999"}],
        }
    )
    raw = _get_adms().metrics
    assert "password" not in raw
    assert "card" not in raw
    assert "rows" not in raw
    assert "secret" not in raw
    metrics = json.loads(raw)
    assert set(metrics["last_sync"].keys()) == {
        "fetched",
        "inserted",
        "duplicates",
        "errors",
    }
