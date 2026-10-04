"""
Phase 4: BaleBot Service Monitoring instrumentation tests.
"""
import json
from unittest.mock import MagicMock

import pytest

from models.service_health import ServiceHealth
from tests.conftest import TestingSessionLocal


@pytest.fixture(autouse=True)
def _monitoring_uses_test_db(monkeypatch):
    import core.service_monitoring as mon
    import bot.bale_api as bale_api

    monkeypatch.setattr(mon, "_session_factory", TestingSessionLocal)
    monkeypatch.setattr(mon, "SessionLocal", TestingSessionLocal)

    # Isolate API failure counter between tests.
    bale_api._get_updates_fail_count = 0

    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()
    yield
    bale_api._get_updates_fail_count = 0
    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()


def _get_bale() -> ServiceHealth | None:
    session = TestingSessionLocal()
    try:
        return session.get(ServiceHealth, "bale")
    finally:
        session.close()


def _metrics(row: ServiceHealth | None) -> dict:
    if row is None or not row.metrics:
        return {}
    return json.loads(row.metrics)


def test_bale_startup_sets_running(monkeypatch):
    import bot.main as bot_main

    monkeypatch.setattr(
        bot_main.bale_api,
        "get_me",
        lambda: {"ok": True, "result": {"username": "timex_bot"}},
    )

    calls = {"n": 0}

    def stop_loop(*_a, **_k):
        calls["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(bot_main.bale_api, "get_updates", stop_loop)
    monkeypatch.setattr(bot_main, "_maybe_record_heartbeat", lambda: None)

    bot_main.main()

    row = _get_bale()
    assert row is not None
    assert row.process_state == "running"
    assert row.started_at is not None
    assert _metrics(row).get("bot_connected") is True


def test_successful_poll_updates_last_success_at(monkeypatch):
    import bot.bale_api as bale_api
    from core.service_monitoring import record_startup

    record_startup("bale")
    monkeypatch.setattr(
        bale_api,
        "_post",
        lambda method, data: {"ok": True, "result": []},
    )

    assert bale_api.get_updates(offset=0, timeout=1) == []

    row = _get_bale()
    assert row is not None
    assert row.last_success_at is not None
    assert _metrics(row)["consecutive_failures"] == 0
    assert _metrics(row)["recovery"] == "ok"


def test_api_failure_records_bale_api_failed(monkeypatch):
    import bot.bale_api as bale_api
    import requests

    def boom(method, data):
        # Simulate _post failure path via _log_api_failure
        raise requests.ConnectionError("down")

    def failing_post(method, data):
        try:
            boom(method, data)
        except Exception as exc:
            bale_api._log_api_failure(method, exc)
            return {}

    monkeypatch.setattr(bale_api, "_post", failing_post)

    assert bale_api.get_updates(offset=0, timeout=1) == []

    row = _get_bale()
    assert row is not None
    assert row.last_error_code == "BALE_API_FAILED"
    assert "token" not in (row.last_error_summary or "").lower()
    assert "traceback" not in (row.last_error_summary or "").lower()
    assert _metrics(row)["consecutive_failures"] == 1
    assert row.last_success_at is None


def test_repeated_failures_increment_consecutive_failures(monkeypatch):
    import bot.bale_api as bale_api
    import requests

    def failing_post(method, data):
        bale_api._log_api_failure(method, requests.Timeout("t"))
        return {}

    monkeypatch.setattr(bale_api, "_post", failing_post)

    bale_api.get_updates()
    bale_api.get_updates()
    bale_api.get_updates()

    assert bale_api._get_updates_fail_count == 3
    assert _metrics(_get_bale())["consecutive_failures"] == 3


def test_recovery_resets_consecutive_failures(monkeypatch):
    import bot.bale_api as bale_api
    import requests

    def failing_post(method, data):
        bale_api._log_api_failure(method, requests.Timeout("t"))
        return {}

    monkeypatch.setattr(bale_api, "_post", failing_post)
    bale_api.get_updates()
    bale_api.get_updates()
    assert _metrics(_get_bale())["consecutive_failures"] == 2

    monkeypatch.setattr(
        bale_api,
        "_post",
        lambda method, data: {"ok": True, "result": [{"update_id": 1}]},
    )
    updates = bale_api.get_updates()
    assert updates == [{"update_id": 1}]
    assert bale_api._get_updates_fail_count == 0

    row = _get_bale()
    assert row.last_success_at is not None
    assert _metrics(row)["consecutive_failures"] == 0
    assert _metrics(row)["recovery"] == "recovered"


def test_bot_connected_metric_distinct_from_last_success(monkeypatch):
    import bot.main as bot_main
    from core.service_monitoring import record_startup

    # Simulate connection metrics without a successful poll yet.
    record_startup("bale")
    bot_main.merge_metrics("bale", {"bot_connected": True})

    row = _get_bale()
    assert _metrics(row)["bot_connected"] is True
    assert row.last_success_at is None


def test_polling_loop_failure_uses_distinct_error_code(monkeypatch):
    import bot.main as bot_main
    from core.service_monitoring import record_startup

    record_startup("bale")
    bot_main._monitor_loop_failure(2, "RuntimeError")

    row = _get_bale()
    assert row.last_error_code == "POLLING_LOOP_FAILED"
    assert _metrics(row)["loop_consecutive_failures"] == 2


def test_monitoring_failure_does_not_break_get_updates(monkeypatch):
    import bot.bale_api as bale_api
    import core.service_monitoring as mon

    monkeypatch.setattr(
        mon, "record_success", MagicMock(side_effect=RuntimeError("db down"))
    )
    monkeypatch.setattr(
        bale_api,
        "_post",
        lambda method, data: {"ok": True, "result": []},
    )

    assert bale_api.get_updates() == []


def test_monitoring_failure_does_not_break_api_failure_path(monkeypatch):
    import bot.bale_api as bale_api
    import core.service_monitoring as mon
    import requests

    monkeypatch.setattr(
        mon, "record_error", MagicMock(side_effect=RuntimeError("db down"))
    )
    monkeypatch.setattr(
        mon, "merge_metrics", MagicMock(side_effect=RuntimeError("db down"))
    )

    def failing_post(method, data):
        bale_api._log_api_failure(method, requests.ConnectionError("x"))
        return {}

    monkeypatch.setattr(bale_api, "_post", failing_post)
    assert bale_api.get_updates() == []


def test_metrics_and_errors_contain_no_sensitive_data(monkeypatch):
    import bot.bale_api as bale_api
    import requests

    def failing_post(method, data):
        # Ensure token/payload-like content never reaches monitoring.
        exc = requests.ConnectionError(
            "https://tapi.bale.ai/botSECRETTOKEN/getUpdates payload={chat_id:1}"
        )
        bale_api._log_api_failure(method, exc)
        return {}

    monkeypatch.setattr(bale_api, "_post", failing_post)
    bale_api.get_updates()

    row = _get_bale()
    blob = json.dumps(_metrics(row)) + (row.last_error_summary or "")
    assert "SECRETTOKEN" not in blob
    assert "chat_id" not in blob
    assert "authorization" not in blob.lower()
    assert "payload" not in blob.lower()


def test_heartbeat_is_throttled(monkeypatch):
    import bot.main as bot_main
    from core.service_monitoring import record_startup

    record_startup("bale")
    bot_main._last_heartbeat_mono = 0.0

    times = iter([100.0, 110.0, 170.0])
    monkeypatch.setattr(bot_main.time, "monotonic", lambda: next(times))

    bot_main._maybe_record_heartbeat()  # 100 -> write
    first = _get_bale().last_heartbeat_at
    bot_main._maybe_record_heartbeat()  # 110 -> skip (< 60s)
    second = _get_bale().last_heartbeat_at
    assert second == first

    bot_main._maybe_record_heartbeat()  # 170 -> write
    third = _get_bale().last_heartbeat_at
    assert third >= first
