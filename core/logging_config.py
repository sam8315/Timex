"""
Shared logging infrastructure for Timex Windows Services (web / adms / bale).

Public API:
    configure_logging(service: Literal["web", "adms", "bale"]) -> None
    get_logger(name: str | None = None) -> logging.Logger
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal

ServiceName = Literal["web", "adms", "bale"]
ALLOWED_SERVICES: frozenset[str] = frozenset(("web", "adms", "bale"))

REDACTED = "***REDACTED***"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_HANDLER_STDOUT = "timex.stdout"
_HANDLER_APP_FILE = "timex.app.file"
_HANDLER_ACCESS_FILE = "timex.access.file"

_OPTIONAL_FIELDS = ("event", "request_id", "user_id", "device_id", "duration_ms")

_STATIC_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(https?://tapi\.bale\.ai/bot)([^/\s?#]+)", re.IGNORECASE),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(password_hash\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(password\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(authorization\s*[=:]\s*)(.+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(bearer\s+)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(cookie\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(session(?:[_ ]?(?:id|key))?\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(csrf(?:[_ ]?token)?\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
    (
        re.compile(r"(?i)\b(secret[_ ]?key\s*[=:]\s*)(\S+)"),
        rf"\1{REDACTED}",
    ),
)

_state: dict[str, Any] = {
    "configured": False,
    "service": None,
    "service_filter": None,
}


def redact_text(text: str) -> str:
    """Redact secrets and bot-token URLs from arbitrary text."""
    if not text:
        return text

    token = os.environ.get("BALE_BOT_TOKEN")
    if token:
        text = text.replace(token, REDACTED)

    for pattern, repl in _STATIC_REDACT_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _redact_exc_info(
    exc_info: tuple[type[BaseException] | None, BaseException | None, Any],
) -> tuple[type[BaseException] | None, BaseException | None, Any]:
    exc_type, exc_value, exc_tb = exc_info
    if exc_value is None:
        return exc_info

    redacted_message = redact_text(str(exc_value))
    if redacted_message == str(exc_value):
        return exc_info

    try:
        new_exc: BaseException = exc_type(redacted_message)  # type: ignore[misc]
    except Exception:
        new_exc = Exception(redacted_message)
    return exc_type, new_exc, exc_tb


class ServiceContextFilter(logging.Filter):
    """Inject service= into every LogRecord."""

    def __init__(self, service: ServiceName) -> None:
        super().__init__()
        self.service: ServiceName = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service  # type: ignore[attr-defined]
        return True


class RedactingFilter(logging.Filter):
    """Redact secrets in msg, args, and exc_info before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)

        record.msg = redact_text(rendered)
        record.args = ()

        if record.exc_info:
            record.exc_info = _redact_exc_info(record.exc_info)
            # Force formatter to rebuild exc_text from redacted exc_info.
            record.exc_text = None

        if isinstance(record.exc_text, str):
            record.exc_text = redact_text(record.exc_text)

        return True


class ContractFormatter(logging.Formatter):
    """One-line Timex log format with optional context fields."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created).astimezone()
        ms = int(record.msecs)
        # %z -> +0330 style offset
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{ms:03d}{dt.strftime('%z')}"

    def formatException(self, ei: tuple[type[BaseException] | None, BaseException | None, Any]) -> str:
        formatted = super().formatException(ei)
        return redact_text(formatted)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record)
        service = getattr(record, "service", "unknown")
        parts = [
            timestamp,
            record.levelname,
            f"service={service}",
            f"logger={record.name}",
        ]

        for key in _OPTIONAL_FIELDS:
            value = getattr(record, key, None)
            if value is not None and value != "":
                parts.append(f"{key}={value}")

        message = redact_text(record.getMessage())
        parts.append(f"message={message}")
        line = " ".join(parts)

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            else:
                record.exc_text = redact_text(record.exc_text)
            line = f"{line}\n{record.exc_text}"
        elif record.stack_info:
            line = f"{line}\n{redact_text(self.formatStack(record.stack_info))}"

        return redact_text(line)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_level() -> int:
    raw = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def default_log_dir() -> Path:
    """Default log directory anchored to project root (not process cwd)."""
    configured = os.environ.get("LOG_DIR")
    if configured:
        return Path(configured).expanduser()
    return _PROJECT_ROOT / "logs"


def _handler_by_name(logger: logging.Logger, name: str) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, "name", None) == name:
            return handler
    return None


def _make_formatter() -> ContractFormatter:
    return ContractFormatter()


def _attach_filters(handler: logging.Handler, service_filter: ServiceContextFilter) -> None:
    # Avoid stacking duplicate filters on reconfigure paths.
    handler.filters.clear()
    handler.addFilter(service_filter)
    handler.addFilter(RedactingFilter())


def _build_rotating_file_handler(path: Path, name: str) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filename=str(path),
        maxBytes=_env_int("LOG_MAX_BYTES", 10 * 1024 * 1024),
        backupCount=_env_int("LOG_BACKUP_COUNT", 10),
        encoding="utf-8",
    )
    handler.name = name
    handler.setFormatter(_make_formatter())
    return handler


def _apply_third_party_levels(service: ServiceName, app_level: int) -> None:
    for name in (
        "sqlalchemy",
        "sqlalchemy.engine",
        "asyncio",
        "httpx",
        "urllib3",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    if service == "web":
        logging.getLogger("uvicorn").setLevel(app_level)
        logging.getLogger("uvicorn.error").setLevel(app_level)
        access = logging.getLogger("uvicorn.access")
        # Access volume is independent; keep at INFO unless root is more restrictive.
        access.setLevel(logging.INFO)


def _remove_named_handler(logger: logging.Logger, name: str) -> None:
    handler = _handler_by_name(logger, name)
    if handler is not None:
        logger.removeHandler(handler)
        handler.close()


def _reset_logging_state() -> None:
    """Remove Timex handlers and clear module state. Intended for tests."""
    root = logging.getLogger()
    for name in (_HANDLER_STDOUT, _HANDLER_APP_FILE):
        _remove_named_handler(root, name)

    access = logging.getLogger("uvicorn.access")
    _remove_named_handler(access, _HANDLER_ACCESS_FILE)
    access.propagate = True

    _state["configured"] = False
    _state["service"] = None
    _state["service_filter"] = None


def _ensure_access_logger(service: ServiceName, service_filter: ServiceContextFilter) -> None:
    access = logging.getLogger("uvicorn.access")
    access.propagate = False

    if service != "web":
        _remove_named_handler(access, _HANDLER_ACCESS_FILE)
        return

    existing = _handler_by_name(access, _HANDLER_ACCESS_FILE)
    if existing is not None:
        _attach_filters(existing, service_filter)
        return

    log_dir = default_log_dir()
    handler = _build_rotating_file_handler(log_dir / "web.access.log", _HANDLER_ACCESS_FILE)
    _attach_filters(handler, service_filter)
    access.addHandler(handler)
    access.setLevel(logging.INFO)


def configure_logging(service: ServiceName) -> None:
    """
    Configure process-wide Timex logging once per process.

    Idempotent: repeated calls do not attach duplicate handlers.
    """
    if service not in ALLOWED_SERVICES:
        raise ValueError(
            f"Unsupported service {service!r}; expected one of {sorted(ALLOWED_SERVICES)}"
        )

    app_level = _resolve_level()
    root = logging.getLogger()
    root.setLevel(app_level)

    service_filter: ServiceContextFilter
    if _state["configured"] and _state["service_filter"] is not None:
        service_filter = _state["service_filter"]
        service_filter.service = service
    else:
        service_filter = ServiceContextFilter(service)
        _state["service_filter"] = service_filter

    # Already configured for this process: refresh levels/filters only.
    if _state["configured"]:
        for handler_name in (_HANDLER_STDOUT, _HANDLER_APP_FILE):
            handler = _handler_by_name(root, handler_name)
            if handler is not None:
                _attach_filters(handler, service_filter)
                handler.setLevel(app_level)

        # Service switch (mainly tests): replace app file handler path.
        if _state["service"] != service:
            _remove_named_handler(root, _HANDLER_APP_FILE)
            if _env_bool("LOG_TO_FILE", True):
                app_handler = _build_rotating_file_handler(
                    default_log_dir() / f"{service}.app.log",
                    _HANDLER_APP_FILE,
                )
                app_handler.setLevel(app_level)
                _attach_filters(app_handler, service_filter)
                root.addHandler(app_handler)
            _state["service"] = service

        _ensure_access_logger(service, service_filter)
        _apply_third_party_levels(service, app_level)
        return

    # First-time setup
    if _env_bool("LOG_TO_STDOUT", True) and _handler_by_name(root, _HANDLER_STDOUT) is None:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.name = _HANDLER_STDOUT
        stdout_handler.setLevel(app_level)
        stdout_handler.setFormatter(_make_formatter())
        _attach_filters(stdout_handler, service_filter)
        root.addHandler(stdout_handler)

    if _env_bool("LOG_TO_FILE", True) and _handler_by_name(root, _HANDLER_APP_FILE) is None:
        app_handler = _build_rotating_file_handler(
            default_log_dir() / f"{service}.app.log",
            _HANDLER_APP_FILE,
        )
        app_handler.setLevel(app_level)
        _attach_filters(app_handler, service_filter)
        root.addHandler(app_handler)

    _ensure_access_logger(service, service_filter)
    _apply_third_party_levels(service, app_level)

    _state["configured"] = True
    _state["service"] = service


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a stdlib logger; prefers caller module name when omitted."""
    if name is None:
        return logging.getLogger()
    return logging.getLogger(name)
