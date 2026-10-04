"""
Best-effort runtime writer for service_health.

Public API:
    record_startup(service_name)
    record_heartbeat(service_name)
    record_success(service_name, *, metrics=None)
    record_error(service_name, *, error_code=None, error_summary=None)
    merge_metrics(service_name, metrics)

Writes last-known state only. No health calculation, no history, no secrets.
Failures are logged and swallowed so callers keep running.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import sessionmaker

from database.engine import SessionLocal
from models.service_health import SERVICE_NAMES, ServiceHealth

try:
    from core.logging_config import redact_text as _redact_text
except Exception:  # pragma: no cover - logging_config always present in app
    def _redact_text(text: str) -> str:
        return text

logger = logging.getLogger(__name__)

_MAX_ERROR_CODE = 64
_MAX_ERROR_SUMMARY = 500
_MAX_METRICS_CHARS = 4000
_SECRETISH = re.compile(
    r"(?i)\b(password|passwd|token|otp|authorization|bearer|cookie|secret|credential)s?\b"
)
_SENSITIVE_METRIC_KEYS = (
    "token",
    "password",
    "authorization",
    "bearer",
    "secret",
    "credential",
    "otp",
)
_REDACTED = "***"

# Overridable in tests; production uses database.engine.SessionLocal.
_session_factory: sessionmaker = SessionLocal


def _now() -> datetime:
    """Timezone-aware UTC — matches DateTime(timezone=True) columns."""
    return datetime.now(timezone.utc)


def _validate_service(service_name: str) -> str:
    if service_name not in SERVICE_NAMES:
        raise ValueError(
            f"Unsupported service_name {service_name!r}; "
            f"expected one of {SERVICE_NAMES}"
        )
    return service_name


def _sanitize_error_code(error_code: str | None) -> str | None:
    if error_code is None:
        return None
    text = str(error_code).strip().splitlines()[0].strip()
    if not text:
        return None
    text = _redact_text(text)
    return text[:_MAX_ERROR_CODE] or None


def _sanitize_error_summary(error_summary: str | None) -> str | None:
    """Short operator-safe summary — never store traceback / secrets / payloads."""
    if error_summary is None:
        return None
    text = str(error_summary).strip()
    if not text:
        return None

    # Drop traceback bodies / multi-line dumps; keep a single short line.
    if "Traceback (most recent call last)" in text:
        text = text.split("Traceback (most recent call last)", 1)[0].strip()
        if not text:
            text = "unhandled exception"
    text = text.splitlines()[0].strip()
    text = " ".join(text.split())
    text = _redact_text(text)

    # Extra guard when redact patterns miss free-form secret mentions.
    if _SECRETISH.search(text):
        text = _SECRETISH.sub("***", text)

    return text[:_MAX_ERROR_SUMMARY] or None


def _parse_metrics(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _is_sensitive_metric_key(key: Any) -> bool:
    name = str(key).lower()
    return any(part in name for part in _SENSITIVE_METRIC_KEYS)


def _redact_metrics(data: Any) -> Any:
    """Replace values under common private key names; leave operational fields intact."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if _is_sensitive_metric_key(key):
                out[key] = _REDACTED
            else:
                out[key] = _redact_metrics(value)
        return out
    if isinstance(data, list):
        return [_redact_metrics(item) for item in data]
    return data


def _sanitize_metrics_patch(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept only compact JSON-serializable operational dicts."""
    if metrics is None:
        return None
    if not isinstance(metrics, dict) or not metrics:
        return None
    try:
        text = json.dumps(metrics, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return None
    if len(text) > _MAX_METRICS_CHARS:
        logger.warning(
            "Service monitoring metrics patch too large; ignored",
            extra={"event": "database.operation_failed"},
        )
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return _redact_metrics(parsed)


def _metrics_to_text(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _mutate(
    service_name: str,
    *,
    fields: dict[str, Any],
    metrics_patch: dict[str, Any] | None = None,
    insert_defaults: dict[str, Any] | None = None,
) -> bool:
    """
    Best-effort per-service update with optional metrics merge.
    Never raises to the caller (except invalid service_name).
    """
    try:
        service_name = _validate_service(service_name)
    except ValueError:
        raise
    except Exception:
        logger.exception(
            "Service monitoring validation failed service=%s",
            service_name,
            extra={"event": "database.operation_failed"},
        )
        return False

    patch = _sanitize_metrics_patch(metrics_patch)
    session = None
    try:
        session = _session_factory()
        row = session.get(ServiceHealth, service_name)
        if row is None:
            defaults = {
                "service_name": service_name,
                "process_state": "unknown",
                "health_state": "unknown",
            }
            if insert_defaults:
                defaults.update(insert_defaults)
            defaults.update(fields)
            row = ServiceHealth(**{
                key: value
                for key, value in defaults.items()
                if key in ServiceHealth.__table__.columns
            })
            session.add(row)
        else:
            for key, value in fields.items():
                if key == "service_name":
                    continue
                setattr(row, key, value)

        if patch is not None:
            row.metrics = _metrics_to_text(_deep_merge(_parse_metrics(row.metrics), patch))

        session.commit()
        return True
    except Exception:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        logger.exception(
            "Service monitoring write failed service=%s",
            service_name,
            extra={"event": "database.operation_failed"},
        )
        return False
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def record_startup(service_name: str) -> bool:
    """Mark service process as running; health stays unknown (no calculation)."""
    now = _now()
    values = {
        "service_name": service_name,
        "process_state": "running",
        "health_state": "unknown",
        "started_at": now,
        "last_heartbeat_at": now,
        "updated_at": now,
    }
    return _mutate(
        service_name,
        fields=values,
        insert_defaults=values,
    )


def record_heartbeat(service_name: str) -> bool:
    """Touch last_heartbeat_at only — no health decision."""
    now = _now()
    return _mutate(
        service_name,
        fields={
            "last_heartbeat_at": now,
            "updated_at": now,
        },
        insert_defaults={
            "service_name": service_name,
            "process_state": "unknown",
            "health_state": "unknown",
            "last_heartbeat_at": now,
            "updated_at": now,
        },
    )


def record_success(service_name: str, *, metrics: dict[str, Any] | None = None) -> bool:
    """
    Touch last_success_at. Optionally merge a compact operational metrics patch.

    metrics is merged into existing service_health.metrics (does not wipe other keys).
    """
    now = _now()
    return _mutate(
        service_name,
        fields={
            "last_success_at": now,
            "updated_at": now,
        },
        metrics_patch=metrics,
        insert_defaults={
            "service_name": service_name,
            "process_state": "unknown",
            "health_state": "unknown",
            "last_success_at": now,
            "updated_at": now,
        },
    )


def merge_metrics(service_name: str, metrics: dict[str, Any]) -> bool:
    """
    Merge operational metrics without changing last_success_at / error fields.
    Used for device connection state and similar non-success signals.
    """
    now = _now()
    return _mutate(
        service_name,
        fields={"updated_at": now},
        metrics_patch=metrics,
        insert_defaults={
            "service_name": service_name,
            "process_state": "unknown",
            "health_state": "unknown",
            "updated_at": now,
        },
    )


def record_error(
    service_name: str,
    *,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> bool:
    """Store a short safe error snapshot. Never stores traceback/secrets/payloads."""
    now = _now()
    code = _sanitize_error_code(error_code)
    summary = _sanitize_error_summary(error_summary)
    return _mutate(
        service_name,
        fields={
            "last_error_at": now,
            "last_error_code": code,
            "last_error_summary": summary,
            "updated_at": now,
        },
        insert_defaults={
            "service_name": service_name,
            "process_state": "unknown",
            "health_state": "unknown",
            "last_error_at": now,
            "last_error_code": code,
            "last_error_summary": summary,
            "updated_at": now,
        },
    )
