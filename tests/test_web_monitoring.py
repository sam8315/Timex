"""
Phase 5B: Web Service Monitoring instrumentation tests.
"""
import json
from unittest.mock import MagicMock

import pytest

from models.service_health import ServiceHealth
from tests.conftest import TestingSessionLocal


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


def _get_web() -> ServiceHealth | None:
    session = TestingSessionLocal()
    try:
        return session.get(ServiceHealth, "web")
    finally:
        session.close()


def _metrics(row: ServiceHealth | None) -> dict:
    if row is None or not row.metrics:
        return {}
    return json.loads(row.metrics)


def test_web_startup_sets_running_and_started_at(monkeypatch):
    import run_web

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_web, "ensure_database_tables", lambda: None)
    monkeypatch.setattr(run_web, "ensure_test_access", lambda: None)
    monkeypatch.setattr(run_web.uvicorn, "run", MagicMock())

    run_web.main()

    row = _get_web()
    assert row is not None
    assert row.process_state == "running"
    assert row.started_at is not None
    assert row.last_heartbeat_at is not None


def test_db_readiness_success_sets_last_success_at(monkeypatch):
    import run_web

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_web, "ensure_database_tables", lambda: None)
    monkeypatch.setattr(run_web, "ensure_test_access", lambda: None)
    monkeypatch.setattr(run_web.uvicorn, "run", MagicMock())

    run_web.main()

    row = _get_web()
    assert row is not None
    assert row.last_success_at is not None
    assert _metrics(row).get("last_success_kind") == "db_ready"


def test_db_startup_failure_records_db_startup_failed(monkeypatch):
    import run_web

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(
        run_web,
        "ensure_database_tables",
        MagicMock(side_effect=RuntimeError("connection refused password=secret")),
    )
    monkeypatch.setattr(run_web, "ensure_test_access", MagicMock())
    monkeypatch.setattr(run_web.uvicorn, "run", MagicMock())

    with pytest.raises(RuntimeError, match="connection refused"):
        run_web.main()

    row = _get_web()
    assert row is not None
    assert row.last_error_code == "DB_STARTUP_FAILED"
    assert row.last_error_summary == "Database startup failed"
    assert "password" not in (row.last_error_summary or "").lower()
    assert "secret" not in (row.last_error_summary or "")
    assert "traceback" not in (row.last_error_summary or "").lower()
    assert row.last_success_at is None
    run_web.ensure_test_access.assert_not_called()
    run_web.uvicorn.run.assert_not_called()


def test_monitoring_failure_does_not_break_web_startup(monkeypatch):
    import run_web
    import core.service_monitoring as mon

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(run_web, "ensure_database_tables", lambda: None)
    monkeypatch.setattr(run_web, "ensure_test_access", lambda: None)
    uvicorn_run = MagicMock()
    monkeypatch.setattr(run_web.uvicorn, "run", uvicorn_run)

    monkeypatch.setattr(
        mon,
        "_session_factory",
        MagicMock(side_effect=RuntimeError("mon db down")),
    )
    monkeypatch.setattr(
        run_web,
        "record_success",
        MagicMock(side_effect=RuntimeError("mon raise")),
    )
    monkeypatch.setattr(
        run_web,
        "record_startup",
        MagicMock(side_effect=RuntimeError("mon raise")),
    )

    run_web.main()
    uvicorn_run.assert_called_once()


def test_monitoring_failure_does_not_hide_db_startup_error(monkeypatch):
    import run_web

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(
        run_web,
        "ensure_database_tables",
        MagicMock(side_effect=RuntimeError("db init exploded")),
    )
    monkeypatch.setattr(
        run_web,
        "record_error",
        MagicMock(side_effect=RuntimeError("mon raise")),
    )
    uvicorn_run = MagicMock()
    monkeypatch.setattr(run_web.uvicorn, "run", uvicorn_run)

    with pytest.raises(RuntimeError, match="db init exploded"):
        run_web.main()

    uvicorn_run.assert_not_called()


def test_error_summary_contains_no_credentials_or_traceback(monkeypatch):
    import run_web

    monkeypatch.setattr(run_web, "_configure_stdio_utf8", lambda: None)
    monkeypatch.setattr(run_web, "configure_logging", lambda *_a, **_k: None)
    monkeypatch.setattr(
        run_web,
        "ensure_database_tables",
        MagicMock(
            side_effect=RuntimeError(
                "postgresql://user:hunter2@localhost/timex\n"
                "Traceback (most recent call last):\n"
                "  File 'x.py', line 1"
            )
        ),
    )
    monkeypatch.setattr(run_web.uvicorn, "run", MagicMock())

    with pytest.raises(RuntimeError):
        run_web.main()

    row = _get_web()
    summary = row.last_error_summary or ""
    assert summary == "Database startup failed"
    assert "hunter2" not in summary
    assert "postgresql://" not in summary
    assert "Traceback" not in summary
