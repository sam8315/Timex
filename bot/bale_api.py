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
        return []

    if _get_updates_fail_count > 0:
        logger.info(
            "Polling recovered after %s consecutive failures",
            _get_updates_fail_count,
            extra={"event": "bot.polling_started"},
        )
        _get_updates_fail_count = 0

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
