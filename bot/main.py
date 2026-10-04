"""
نقطه ورود ربات بله
اجرا: python -m bot.main
"""
import logging
import time
import sys

from core.logging_config import configure_logging
from core.service_monitoring import merge_metrics, record_error, record_heartbeat, record_startup
from bot import bale_api
from bot.config import POLLING_TIMEOUT
from bot.handlers import handle_message

logger = logging.getLogger(__name__)

# Heartbeat cadence for service_health (reuse polling loop; no extra thread).
_HEARTBEAT_INTERVAL_SEC = 60.0
_last_heartbeat_mono = 0.0


def _maybe_record_heartbeat() -> None:
    """Emit at most one heartbeat per interval from the existing poll loop."""
    global _last_heartbeat_mono
    now = time.monotonic()
    if _last_heartbeat_mono and (now - _last_heartbeat_mono) < _HEARTBEAT_INTERVAL_SEC:
        return
    record_heartbeat("bale")
    _last_heartbeat_mono = now


def _monitor_loop_failure(consecutive: int, error_type: str) -> None:
    """Best-effort loop-level failure snapshot (never raises to caller)."""
    try:
        record_error(
            "bale",
            error_code="POLLING_LOOP_FAILED",
            error_summary=f"Polling loop failed ({error_type})",
        )
        merge_metrics(
            "bale",
            {
                "loop_consecutive_failures": int(consecutive),
                "recovery": "failed",
            },
        )
    except Exception:
        logger.exception(
            "Bale loop failure monitoring update failed",
            extra={"event": "database.operation_failed"},
        )


def _monitor_loop_recovery() -> None:
    """Best-effort loop recovery snapshot (never raises to caller)."""
    try:
        merge_metrics(
            "bale",
            {
                "loop_consecutive_failures": 0,
                "recovery": "recovered",
            },
        )
    except Exception:
        logger.exception(
            "Bale loop recovery monitoring update failed",
            extra={"event": "database.operation_failed"},
        )


def main():
    configure_logging("bale")

    logger.info(
        "Bale bot process starting",
        extra={"event": "service.starting"},
    )

    # بررسی اتصال به ربات
    bot_info = bale_api.get_me()
    if not bot_info.get('ok'):
        logger.critical(
            "Bot connection failed; check BALE_BOT_TOKEN in .env",
            extra={"event": "service.stopping"},
        )
        try:
            record_error(
                "bale",
                error_code="BALE_API_FAILED",
                error_summary="Bot connection failed (getMe)",
            )
            merge_metrics("bale", {"bot_connected": False})
        except Exception:
            logger.exception(
                "Bale connection-failure monitoring update failed",
                extra={"event": "database.operation_failed"},
            )
        sys.exit(1)

    bot_name = bot_info.get('result', {}).get('username', 'unknown')
    logger.info(
        "Bot connected username=%s",
        bot_name,
        extra={"event": "bot.connected"},
    )

    # Real service lifecycle starts here: bot is connected and polling will begin.
    record_startup("bale")
    try:
        merge_metrics("bale", {"bot_connected": True, "consecutive_failures": 0})
    except Exception:
        logger.exception(
            "Bale connection monitoring update failed",
            extra={"event": "database.operation_failed"},
        )

    logger.info(
        "Starting polling timeout=%ss",
        POLLING_TIMEOUT,
        extra={"event": "bot.polling_started"},
    )

    offset = 0
    consecutive_loop_errors = 0

    try:
        while True:
            try:
                _maybe_record_heartbeat()

                updates = bale_api.get_updates(offset=offset, timeout=POLLING_TIMEOUT)

                if consecutive_loop_errors > 0:
                    logger.info(
                        "Polling loop recovered after %s consecutive errors",
                        consecutive_loop_errors,
                        extra={"event": "bot.polling_started"},
                    )
                    consecutive_loop_errors = 0
                    _monitor_loop_recovery()

                for update in updates:
                    offset = update.get('update_id', 0) + 1

                    message = update.get('message')
                    if message:
                        try:
                            handle_message(message)
                        except Exception:
                            logger.exception(
                                "Message handler failed update_id=%s",
                                update.get('update_id'),
                                extra={"event": "bot.api_call"},
                            )

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                consecutive_loop_errors += 1
                error_type = type(exc).__name__
                if consecutive_loop_errors == 1:
                    logger.exception(
                        "Polling loop error error_type=%s",
                        error_type,
                        extra={"event": "bot.polling_error"},
                    )
                else:
                    logger.warning(
                        "Polling loop transient failure error_type=%s consecutive=%s",
                        error_type,
                        consecutive_loop_errors,
                        extra={"event": "bot.polling_error"},
                    )
                _monitor_loop_failure(consecutive_loop_errors, error_type)
                time.sleep(5)

            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info(
            "Bale bot stopped",
            extra={"event": "service.stopping"},
        )


if __name__ == "__main__":
    main()
