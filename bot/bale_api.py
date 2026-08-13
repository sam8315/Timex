"""
پوشش API ربات بله
بله از API مشابه تلگرام استفاده می‌کند
"""
import json
import requests
from bot.config import BALE_API_BASE


def _post(method: str, data: dict) -> dict:
    """ارسال درخواست به API بله"""
    url = f"{BALE_API_BASE}/{method}"
    try:
        response = requests.post(url, json=data, timeout=40)
        return response.json()
    except Exception as e:
        print(f"❌ خطا در {method}: {e}")
        return {}


def get_me() -> dict:
    """دریافت اطلاعات ربات"""
    url = f"{BALE_API_BASE}/getMe"
    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as e:
        print(f"❌ خطا در getMe: {e}")
        return {}


def get_updates(offset: int = 0, timeout: int = 30) -> list:
    """دریافت آپدیت‌ها (long polling)"""
    data = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"]
    }
    result = _post("getUpdates", data)
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
        [{"text": "🗓️ تردد یک روز خاص"}]  # 🆕
    ],
    "resize_keyboard": True
}

REMOVE_KEYBOARD = {
    "remove_keyboard": True
}