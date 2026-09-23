"""مدیریت Session با کوکی امضا شده"""
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from fastapi import Request, Response
from typing import Optional, Dict
from web.config import WebConfig

serializer = URLSafeTimedSerializer(WebConfig.SECRET_KEY)


def create_session_token(user_id: str, role: str) -> str:
    return serializer.dumps({"user_id": user_id, "role": role})


def verify_session_token(token: str) -> Optional[Dict]:
    try:
        return serializer.loads(token, max_age=WebConfig.SESSION_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None


def set_session_cookie(response: Response, user_id: str, role: str) -> None:
    token = create_session_token(user_id, role)
    response.set_cookie(
        key=WebConfig.SESSION_COOKIE_NAME,
        value=token,
        max_age=WebConfig.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax"
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=WebConfig.SESSION_COOKIE_NAME)


def get_session_from_request(request: Request) -> Optional[Dict]:
    token = request.cookies.get(WebConfig.SESSION_COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)


# ---------------------------------------------------------------------------
# CSRF — توکن امضاشده برای فرمهای POST حساس
# (SameSite=Lax روی کوکی، لایه اول دفاع است؛ این توکن لایه دوم است)
# ---------------------------------------------------------------------------
_CSRF_SALT = "timex-csrf"


def make_csrf_token(user_id: str) -> str:
    """توکن CSRF امضاشده برای یک کاربر (پایدار در طول نشست)."""
    return serializer.dumps({"csrf": "1", "uid": user_id}, salt=_CSRF_SALT)


def check_csrf_token(token: str, user_id: str) -> bool:
    """اعتبارسنجی توکن CSRF؛ امضا و تطابق با کاربر جاری را چک میکند."""
    if not token:
        return False
    try:
        data = serializer.loads(token, salt=_CSRF_SALT, max_age=WebConfig.CSRF_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return False
    return data.get("csrf") == "1" and data.get("uid") == user_id


# ---------------------------------------------------------------------------
# ریست پسورد - زمینه موقت امضاشده
# ---------------------------------------------------------------------------
_RESET_SALT = "timex-reset"


def create_reset_token(reset_request_id: int) -> str:
    """توکن موقت امضاشده برای زمینه بازنشانی رمز عبور."""
    import time
    return serializer.dumps(
        {"rid": reset_request_id, "ts": int(time.time())},
        salt=_RESET_SALT,
    )


def verify_reset_token(token: str) -> Optional[Dict]:
    """اعتبارسنجی توکن بازنشانی؛ None اگر منقضی یا نامعتبر باشد."""
    if not token:
        return None
    try:
        data = serializer.loads(token, salt=_RESET_SALT, max_age=WebConfig.RESET_CONTEXT_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    return data


def set_reset_cookie(response: Response, reset_request_id: int) -> None:
    """ذخیره توکن بازنشانی در کوکی امضاشده."""
    token = create_reset_token(reset_request_id)
    response.set_cookie(
        key=WebConfig.RESET_COOKIE_NAME,
        value=token,
        max_age=WebConfig.RESET_CONTEXT_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


def clear_reset_cookie(response: Response) -> None:
    """پاک‌سازی کوکی بازنشانی."""
    response.delete_cookie(key=WebConfig.RESET_COOKIE_NAME)


def get_reset_context(request: Request) -> Optional[Dict]:
    """خواندن و اعتبارسنجی زمینه بازنشانی از کوکی."""
    token = request.cookies.get(WebConfig.RESET_COOKIE_NAME)
    if not token:
        return None
    return verify_reset_token(token)