"""Unit tests for core.logging_config shared logging infrastructure."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from core.logging_config import (
    REDACTED,
    _HANDLER_ACCESS_FILE,
    _HANDLER_APP_FILE,
    _HANDLER_STDOUT,
    _reset_logging_state,
    configure_logging,
    default_log_dir,
    get_logger,
    redact_text,
)


FAKE_TOKEN = "TEST_BALE_TOKEN_ABC123XYZ"


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path, monkeypatch):
    """Isolate each test: clean handlers, dedicated LOG_DIR, no stdout noise."""
    _reset_logging_state()
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("LOG_TO_STDOUT", "0")
    monkeypatch.setenv("LOG_TO_FILE", "1")
    monkeypatch.setenv("LOG_MAX_BYTES", "10485760")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "10")
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)
    yield
    _reset_logging_state()


def _app_handler() -> logging.Handler:
    handler = next(
        (
            h
            for h in logging.getLogger().handlers
            if getattr(h, "name", None) == _HANDLER_APP_FILE
        ),
        None,
    )
    assert handler is not None, "expected timex app file handler"
    return handler


def _read_app_log(service: str, tmp_path: Path) -> str:
    path = tmp_path / f"{service}.app.log"
    assert path.exists(), f"missing log file: {path}"
    return path.read_text(encoding="utf-8")


def test_configure_logging_web(tmp_path):
    configure_logging("web")
    logger = get_logger("tests.web")
    logger.info("web ready", extra={"event": "service.starting"})
    text = _read_app_log("web", tmp_path)
    assert "service=web" in text
    assert "message=web ready" in text


def test_configure_logging_adms(tmp_path):
    configure_logging("adms")
    get_logger("tests.adms").info("adms ready")
    text = _read_app_log("adms", tmp_path)
    assert "service=adms" in text


def test_configure_logging_bale(tmp_path):
    configure_logging("bale")
    get_logger("tests.bale").info("bale ready")
    text = _read_app_log("bale", tmp_path)
    assert "service=bale" in text


def test_service_field_injected_automatically(tmp_path):
    configure_logging("adms")
    get_logger("core.adms_server").info("Handshake received", extra={"event": "device.handshake"})
    text = _read_app_log("adms", tmp_path)
    assert "service=adms" in text
    assert "logger=core.adms_server" in text


def test_required_format_fields(tmp_path):
    configure_logging("adms")
    get_logger("core.adms_server").info(
        "Handshake received",
        extra={
            "event": "device.handshake",
            "device_id": "SN123",
            "request_id": "req-1",
            "user_id": "u9",
            "duration_ms": 42,
        },
    )
    text = _read_app_log("adms", tmp_path).strip().splitlines()[0]
    assert " INFO " in f" {text} " or " INFO " in text
    assert "service=adms" in text
    assert "logger=core.adms_server" in text
    assert "event=device.handshake" in text
    assert "device_id=SN123" in text
    assert "request_id=req-1" in text
    assert "user_id=u9" in text
    assert "duration_ms=42" in text
    assert "message=Handshake received" in text
    # Timestamp prefix roughly ISO-like
    assert text[0:4].isdigit() and "T" in text[:25]


def test_info_is_default_level(tmp_path, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging("web")
    assert logging.getLogger().level == logging.INFO


def test_debug_suppressed_when_info(tmp_path):
    configure_logging("web")
    logger = get_logger("tests.level")
    logger.debug("secret debug")
    logger.info("visible info")
    text = _read_app_log("web", tmp_path)
    assert "secret debug" not in text
    assert "visible info" in text


def test_debug_enabled_with_log_level(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    _reset_logging_state()
    configure_logging("web")
    get_logger("tests.level").debug("debug visible")
    text = _read_app_log("web", tmp_path)
    assert "debug visible" in text
    assert "DEBUG" in text


def test_redact_fake_bot_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BALE_BOT_TOKEN", FAKE_TOKEN)
    configure_logging("bale")
    get_logger("bot.main").info(f"token value is {FAKE_TOKEN}")
    text = _read_app_log("bale", tmp_path)
    assert FAKE_TOKEN not in text
    assert REDACTED in text


def test_redact_token_inside_url(tmp_path, monkeypatch):
    monkeypatch.setenv("BALE_BOT_TOKEN", FAKE_TOKEN)
    configure_logging("bale")
    url = f"https://tapi.bale.ai/bot{FAKE_TOKEN}/getMe"
    get_logger("bot.bale_api").error(f"request failed: {url}")
    text = _read_app_log("bale", tmp_path)
    assert FAKE_TOKEN not in text
    assert f"https://tapi.bale.ai/bot{REDACTED}" in text


def test_redact_token_inside_exception_message(tmp_path, monkeypatch):
    monkeypatch.setenv("BALE_BOT_TOKEN", FAKE_TOKEN)
    configure_logging("bale")
    logger = get_logger("bot.bale_api")
    url = f"https://tapi.bale.ai/bot{FAKE_TOKEN}/sendMessage"
    try:
        raise ConnectionError(f"Failed to POST {url}")
    except ConnectionError:
        logger.exception("api.call_failed")
    text = _read_app_log("bale", tmp_path)
    assert FAKE_TOKEN not in text
    assert "api.call_failed" in text
    assert REDACTED in text


def test_no_duplicate_handlers_on_second_configure():
    configure_logging("adms")
    root = logging.getLogger()
    before = len(root.handlers)
    app_before = sum(
        1 for h in root.handlers if getattr(h, "name", None) == _HANDLER_APP_FILE
    )
    configure_logging("adms")
    after = len(root.handlers)
    app_after = sum(
        1 for h in root.handlers if getattr(h, "name", None) == _HANDLER_APP_FILE
    )
    assert before == after
    assert app_before == 1
    assert app_after == 1


def test_rotating_file_handler_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_MAX_BYTES", "2048")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "3")
    _reset_logging_state()
    configure_logging("adms")
    handler = _app_handler()
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 2048
    assert handler.backupCount == 3
    assert Path(handler.baseFilename) == (tmp_path / "adms.app.log").resolve()


def test_utf8_output(tmp_path):
    configure_logging("web")
    get_logger("tests.utf8").info("پیام فارسی با UTF-8")
    raw = (tmp_path / "web.app.log").read_bytes()
    # UTF-8 encoded Persian text must be present
    assert "پیام فارسی".encode("utf-8") in raw
    text = raw.decode("utf-8")
    assert "پیام فارسی با UTF-8" in text


def test_web_access_logger_isolated(tmp_path):
    configure_logging("web")
    access = logging.getLogger("uvicorn.access")
    assert access.propagate is False
    access_handlers = [
        h for h in access.handlers if getattr(h, "name", None) == _HANDLER_ACCESS_FILE
    ]
    assert len(access_handlers) == 1
    assert isinstance(access_handlers[0], RotatingFileHandler)

    access.info("GET /health 200")
    access_text = (tmp_path / "web.access.log").read_text(encoding="utf-8")
    assert "GET /health 200" in access_text

    # Must not appear on application log
    get_logger("tests.web").info("app only")
    app_text = _read_app_log("web", tmp_path)
    assert "GET /health 200" not in app_text
    assert "app only" in app_text


def test_default_log_dir_uses_project_root(monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    from core import logging_config as mod

    expected = mod._PROJECT_ROOT / "logs"
    assert default_log_dir() == expected


def test_redact_text_password_patterns():
    url = f"https://tapi.bale.ai/bot{FAKE_TOKEN}/x"
    redacted_url = redact_text(url)
    assert FAKE_TOKEN not in redacted_url
    assert f"https://tapi.bale.ai/bot{REDACTED}" in redacted_url
    assert "password=***REDACTED***" in redact_text("password=supersecret")
    auth = redact_text("Authorization: Bearer abc.def")
    assert "abc.def" not in auth
    assert REDACTED in auth
    assert "Bearer ***REDACTED***" in redact_text("Bearer abc.def")
    assert "cookie=***REDACTED***" in redact_text("cookie=abc123")
    assert "csrf_token=***REDACTED***" in redact_text("csrf_token=tok")
    assert "secret_key=***REDACTED***" in redact_text("secret_key=xyz")


def test_third_party_levels_set():
    configure_logging("web")
    assert logging.getLogger("sqlalchemy").level == logging.WARNING
    assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
    assert logging.getLogger("asyncio").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING
    assert logging.getLogger("uvicorn").level == logging.INFO
    assert logging.getLogger("uvicorn.error").level == logging.INFO


def test_unsupported_service_raises():
    with pytest.raises(ValueError):
        configure_logging("unknown")  # type: ignore[arg-type]


def test_stdout_handler_optional(monkeypatch):
    monkeypatch.setenv("LOG_TO_STDOUT", "1")
    monkeypatch.setenv("LOG_TO_FILE", "0")
    _reset_logging_state()
    configure_logging("bale")
    root = logging.getLogger()
    names = {getattr(h, "name", None) for h in root.handlers}
    assert _HANDLER_STDOUT in names
    assert _HANDLER_APP_FILE not in names
