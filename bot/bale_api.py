"""
پوشش API ربات بله
بله از API مشابه تلگرام استفاده می‌کند
"""
import json
import logging
import requests
from bot.config import build_api_url

logger = logging.getLogger(__name__)

# Consecutive getUpdates failures (log-storm control; retry timing unchanged).
# Also the source of truth for service_health metrics.consecutive_failures.
_get_updates_fail_count = 0


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, (requests.ConnectionError, ConnectionError)):
        return "connection_error"
    if isinstance(exc, requests.HTTPError):
        return "http_error"
    if isinstance(exc, (ValueError, json.JSONDecodeError)):
        return "invalid_response"
    return "unexpected_exception"


def _monitor_api_failure(*, error_class: str, consecutive: int) -> None:
    """Best-effort Bale API failure snapshot (never raises)."""
    try:
        from core.service_monitoring import merge_metrics, record_error

        record_error(
            "bale",
            error_code="BALE_API_FAILED",
            error_summary=f"Bale API getUpdates failed ({error_class})",
        )
        merge_metrics(
            "bale",
            {
                "consecutive_failures": int(consecutive),
                "recovery": "failed",
            },
        )
    except Exception:
        logger.exception(
            "Bale API failure monitoring update failed",
            extra={"event": "database.operation_failed"},
        )


def _monitor_poll_success(*, recovered: bool) -> None:
    """Best-effort successful polling snapshot (never raises)."""
    try:
        from core.service_monitoring import record_success

        metrics = {
            "consecutive_failures": 0,
            "recovery": "recovered" if recovered else "ok",
        }
        record_success("bale", metrics=metrics)
    except Exception:
        logger.exception(
            "Bale poll success monitoring update failed",
            extra={"event": "database.operation_failed"},
        )


def _post(method: str, data: dict) -> dict:
    """ارسال درخواست به API بله"""
    # URL contains bot token — never log it.
    url = build_api_url(method)
    try:
        response = requests.post(url, json=data, timeout=40)
        return response.json()
    except Exception as exc:
        _log_api_failure(method, exc)
        return {}


def _log_api_failure(method: str, exc: BaseException) -> None:
    """Log API failure without URL/token; dampen getUpdates storms."""
    global _get_updates_fail_count
    error_type = type(exc).__name__
    error_class = _classify_error(exc)

    if method == "getUpdates":
        _get_updates_fail_count += 1
        if _get_updates_fail_count == 1:
            logger.exception(
                "getUpdates failed error_class=%s error_type=%s",
                error_class,
                error_type,
                extra={"event": "bot.polling_error"},
            )
        else:
            logger.warning(
                "getUpdates transient failure error_class=%s error_type=%s consecutive=%s",
                error_class,
                error_type,
                _get_updates_fail_count,
                extra={"event": "bot.polling_error"},
            )
        _monitor_api_failure(
            error_class=error_class,
            consecutive=_get_updates_fail_count,
        )
        return

    if method == "sendMessage":
        logger.exception(
            "sendMessage failed error_class=%s error_type=%s",
            error_class,
            error_type,
            extra={"event": "bot.send_message_failed"},
        )
        return

    logger.exception(
        "Bale API request failed method=%s error_class=%s error_type=%s",
        method,
        error_class,
        error_type,
        extra={"event": "bot.api_call"},
    )


def get_me() -> dict:
    """دریافت اطلاعات ربات"""
    url = build_api_url("getMe")
    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as exc:
        error_type = type(exc).__name__
        error_class = _classify_error(exc)
        logger.exception(
            "getMe failed error_class=%s error_type=%s",
            error_class,
            error_type,
            extra={"event": "bot.api_call"},
        )
        return {}


def get_updates(offset: int = 0, timeout: int = 30) -> list:
    """دریافت آپدیت‌ها (long polling)"""
    global _get_updates_fail_count
    data = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"]
    }
    result = _post("getUpdates", data)
    if not result:
        # Failure path: counter/error already updated in _log_api_failure.
        return []

    # Transport may succeed while the API payload reports failure — not a poll success.
    if result.get("ok") is not True:
        _get_updates_fail_count += 1
        logger.warning(
            "getUpdates unsuccessful response consecutive=%s",
            _get_updates_fail_count,
            extra={"event": "bot.polling_error"},
        )
        _monitor_api_failure(
            error_class="unsuccessful_response",
            consecutive=_get_updates_fail_count,
        )
        return []

    recovered = _get_updates_fail_count > 0
    if recovered:
        logger.info(
            "Polling recovered after %s consecutive failures",
            _get_updates_fail_count,
            extra={"event": "bot.polling_started"},
        )
        _get_updates_fail_count = 0

    _monitor_poll_success(recovered=recovered)
    return result.get("result", [])


def send_message(chat_id, text: str, reply_markup: dict = None) -> dict:
    """ارسال پیام متنی"""
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    return _post("sendMessage", data)


# 🎹 کیبوردها
CONTACT_KEYBOARD = {
    "keyboard": [
        [{"text": "📱 ارسال شماره تماس", "request_contact": True}]
    ],
    "resize_keyboard": True,
    "one_time_keyboard": True
}

MAIN_MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "📅 تردد امروز"}, {"text": "📆 تردد دیروز"}],
        [{"text": "🗓️ تردد یک روز خاص"}, {"text": "💰 مانده مرخصی"}],
        [{"text": "🌐 ورود به پنل وب"}],
    ],
    "resize_keyboard": True
}

REMOVE_KEYBOARD = {
    "remove_keyboard": True
}
# کیبورد لغو عملیات
CANCEL_KEYBOARD = {
    "keyboard": [
        [{"text": "❌ لغو"}]
    ],
    "resize_keyboard": True
}
