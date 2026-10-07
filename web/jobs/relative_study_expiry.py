"""
انقضای خودکار وضعیت «در حال تحصیل» بستگان.

داخل پروسهٔ وب (lifespan) هر ساعت expire_ended_studies را اجرا می‌کند.
خاموش‌کردن: RELATIVE_STUDY_EXPIRY_ENABLED=0
فاصله: RELATIVE_STUDY_EXPIRY_INTERVAL_SECONDS (پیش‌فرض 3600)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from sqlalchemy.orm import Session

from database.engine import SessionLocal
from web.services.employee_relative_service import expire_ended_studies

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 3600

_stop_event: Optional[threading.Event] = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def _env_enabled() -> bool:
    raw = (os.getenv("RELATIVE_STUDY_EXPIRY_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _interval_seconds() -> int:
    raw = (os.getenv("RELATIVE_STUDY_EXPIRY_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid RELATIVE_STUDY_EXPIRY_INTERVAL_SECONDS=%r; using %s",
            raw,
            _DEFAULT_INTERVAL_SECONDS,
        )
        return _DEFAULT_INTERVAL_SECONDS
    return max(30, value)


def run_once(db: Optional[Session] = None) -> int:
    """یک‌بار انقضای تحصیل را اعمال می‌کند. اگر db ندهید SessionLocal ساخته می‌شود."""
    owns_session = db is None
    session = db if db is not None else SessionLocal()
    try:
        updated = expire_ended_studies(session)
        logger.info(
            "relative_study_expiry run_once updated=%s",
            updated,
            extra={"event": "relative_study_expiry"},
        )
        return updated
    finally:
        if owns_session:
            session.close()


def _loop(stop_event: threading.Event) -> None:
    # اجرای فوری پس از استارت
    try:
        run_once()
    except Exception:
        logger.exception(
            "relative_study_expiry initial run failed",
            extra={"event": "relative_study_expiry"},
        )

    while not stop_event.wait(timeout=_interval_seconds()):
        try:
            run_once()
        except Exception:
            logger.exception(
                "relative_study_expiry periodic run failed",
                extra={"event": "relative_study_expiry"},
            )


def start_scheduler() -> bool:
    """شروع thread؛ False اگر خاموش یا از قبل در حال اجرا باشد."""
    global _stop_event, _thread
    if not _env_enabled():
        logger.info(
            "relative_study_expiry scheduler disabled by env",
            extra={"event": "relative_study_expiry"},
        )
        return False

    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_loop,
            args=(stop_event,),
            name="relative-study-expiry",
            daemon=True,
        )
        _stop_event = stop_event
        _thread = thread
        thread.start()
        logger.info(
            "relative_study_expiry scheduler started interval=%ss",
            _interval_seconds(),
            extra={"event": "relative_study_expiry"},
        )
        return True


def stop_scheduler(timeout: float = 5.0) -> None:
    """توقف thread پس از lifespan shutdown."""
    global _stop_event, _thread
    with _lock:
        stop_event = _stop_event
        thread = _thread
        _stop_event = None
        _thread = None

    if stop_event is None or thread is None:
        return
    stop_event.set()
    thread.join(timeout=timeout)
    if thread.is_alive():
        logger.warning(
            "relative_study_expiry thread did not stop within %.1fs",
            timeout,
            extra={"event": "relative_study_expiry"},
        )
    else:
        logger.info(
            "relative_study_expiry scheduler stopped",
            extra={"event": "relative_study_expiry"},
        )


def is_scheduler_running() -> bool:
    return _thread is not None and _thread.is_alive()
