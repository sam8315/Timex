"""
Phase 5A: Service health aggregation.

Combines:
  - Windows Service Control Manager (process state)
  - service_health runtime row (heartbeat / success / error)

Does not write health_state back to DB. Does not read log files.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy.orm import sessionmaker

from database.engine import SessionLocal
from models.service_health import SERVICE_NAMES, ServiceHealth

logger = logging.getLogger(__name__)

# Application name → Windows SCM service name (single mapping location).
WINDOWS_SERVICE_NAME_BY_APP: dict[str, str] = {
    "web": "web",
    "adms": "ADMS",
    "bale": "BaleBot",
}

# Single shared thresholds (do not scatter service-specific values).
HEARTBEAT_TIMEOUT_SECONDS = 120
RECENT_ERROR_WINDOW_SECONDS = 300

_SCM_QUERY_TIMEOUT_SECONDS = 5

# Overridable in tests.
_session_factory: sessionmaker = SessionLocal
_scm_query_runner: Callable[[str], subprocess.CompletedProcess[str]] | None = None


@dataclass(frozen=True)
class ServiceHealthStatus:
    """Operator-safe aggregated status for one Timex service."""

    service_name: str
    process_state: str
    health_state: str
    started_at: datetime | None
    last_heartbeat_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error_code: str | None
    last_error_summary: str | None
    metrics: dict[str, Any] | None
    checked_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_service(service_name: str) -> str:
    if service_name not in SERVICE_NAMES:
        raise ValueError(
            f"Unsupported service_name {service_name!r}; "
            f"expected one of {SERVICE_NAMES}"
        )
    return service_name


def windows_service_name(service_name: str) -> str:
    """Return the Windows SCM name for an application service key."""
    service_name = _validate_service(service_name)
    return WINDOWS_SERVICE_NAME_BY_APP[service_name]


def _run_sc_query(windows_name: str) -> subprocess.CompletedProcess[str]:
    if _scm_query_runner is not None:
        return _scm_query_runner(windows_name)
    return subprocess.run(
        ["sc", "query", windows_name],
        capture_output=True,
        text=True,
        timeout=_SCM_QUERY_TIMEOUT_SECONDS,
        check=False,
    )


def _parse_sc_query_state(stdout: str) -> str:
    """Map `sc query` STATE line to running / stopped / unknown."""
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip().upper()
        if not line.startswith("STATE"):
            continue
        # Example: STATE : 4  RUNNING
        if "RUNNING" in line:
            return "running"
        if "STOPPED" in line:
            return "stopped"
        return "unknown"
    return "unknown"


def get_windows_service_state(service_name: str) -> str:
    """
    Read process state from Windows SCM.

    Returns: running | stopped | unknown
    Never raises to the caller.
    """
    try:
        service_name = _validate_service(service_name)
    except ValueError:
        raise
    except Exception:
        return "unknown"

    if sys.platform != "win32" and _scm_query_runner is None:
        return "unknown"

    try:
        windows_name = WINDOWS_SERVICE_NAME_BY_APP[service_name]
        completed = _run_sc_query(windows_name)
        if completed.returncode != 0:
            return "unknown"
        return _parse_sc_query_state(completed.stdout or "")
    except Exception:
        logger.exception(
            "Windows service query failed service=%s",
            service_name,
            extra={"event": "database.operation_failed"},
        )
        return "unknown"


def _parse_metrics(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_runtime_row(service_name: str) -> tuple[Any | None, bool]:
    """
    Load service_health row.

    Returns (snapshot_or_none, db_ok).
    db_ok=False means the query failed (not merely a missing row).
    """
    session = None
    try:
        session = _session_factory()
        row = session.get(ServiceHealth, service_name)
        if row is None:
            return None, True
        # Copy scalar fields before closing the session.
        snapshot = SimpleNamespace(
            service_name=row.service_name,
            started_at=row.started_at,
            last_heartbeat_at=row.last_heartbeat_at,
            last_success_at=row.last_success_at,
            last_error_at=row.last_error_at,
            last_error_code=row.last_error_code,
            last_error_summary=row.last_error_summary,
            metrics=row.metrics,
        )
        return snapshot, True
    except Exception:
        logger.exception(
            "service_health read failed service=%s",
            service_name,
            extra={"event": "database.operation_failed"},
        )
        return None, False
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def _has_recent_error(last_error_at: datetime | None, checked_at: datetime) -> bool:
    error_at = _as_utc(last_error_at)
    if error_at is None:
        return False
    age = (checked_at - error_at).total_seconds()
    return 0 <= age <= RECENT_ERROR_WINDOW_SECONDS


def _compute_running_health(
    *,
    service_name: str,
    last_heartbeat_at: datetime | None,
    last_error_at: datetime | None,
    last_success_at: datetime | None,
    started_at: datetime | None,
    checked_at: datetime,
    db_ok: bool,
) -> str:
    """
    Generic rules while Windows SCM reports running.

    - DB unavailable → unknown
    - missing heartbeat → unknown (insufficient runtime evidence)
    - stale heartbeat → degraded
      (exception: web with startup evidence — startup-only heartbeat is expected)
    - fresh/allowed heartbeat + recent error → degraded
      (exception: a newer success supersedes the previous error)
    - otherwise → healthy
    """
    if not db_ok:
        return "unknown"

    heartbeat = _as_utc(last_heartbeat_at)
    if heartbeat is None:
        return "unknown"

    age = (checked_at - heartbeat).total_seconds()
    stale = age > HEARTBEAT_TIMEOUT_SECONDS
    web_startup_only = (
        service_name == "web" and _as_utc(started_at) is not None
    )
    if stale and not web_startup_only:
        return "degraded"
    if _has_recent_error(last_error_at, checked_at):
        success = _as_utc(last_success_at)
        error = _as_utc(last_error_at)
        if success is not None and error is not None and success > error:
            return "healthy"
        return "degraded"
    return "healthy"


def get_service_health_status(service_name: str) -> ServiceHealthStatus:
    """
    Aggregate Windows SCM + service_health into an in-memory status.

    Never raises for SCM/DB failures (invalid service_name still raises ValueError).
    """
    service_name = _validate_service(service_name)
    checked_at = _now()

    process_state = get_windows_service_state(service_name)
    row, db_ok = _load_runtime_row(service_name)

    started_at = _as_utc(getattr(row, "started_at", None)) if row else None
    last_heartbeat_at = _as_utc(getattr(row, "last_heartbeat_at", None)) if row else None
    last_success_at = _as_utc(getattr(row, "last_success_at", None)) if row else None
    last_error_at = _as_utc(getattr(row, "last_error_at", None)) if row else None
    last_error_code = getattr(row, "last_error_code", None) if row else None
    last_error_summary = getattr(row, "last_error_summary", None) if row else None
    metrics = _parse_metrics(getattr(row, "metrics", None)) if row else None

    if process_state == "stopped":
        health_state = "offline"
    elif process_state == "unknown":
        health_state = "unknown"
    else:
        health_state = _compute_running_health(
            service_name=service_name,
            last_heartbeat_at=last_heartbeat_at,
            last_error_at=last_error_at,
            last_success_at=last_success_at,
            started_at=started_at,
            checked_at=checked_at,
            db_ok=db_ok,
        )

    return ServiceHealthStatus(
        service_name=service_name,
        process_state=process_state,
        health_state=health_state,
        started_at=started_at,
        last_heartbeat_at=last_heartbeat_at,
        last_success_at=last_success_at,
        last_error_at=last_error_at,
        last_error_code=last_error_code,
        last_error_summary=last_error_summary,
        metrics=metrics,
        checked_at=checked_at,
    )


def list_service_health_statuses() -> list[ServiceHealthStatus]:
    """Aggregate status for all known Timex services."""
    return [get_service_health_status(name) for name in SERVICE_NAMES]
