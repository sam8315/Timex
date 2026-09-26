"""تنظیمات وب"""
import os
from dotenv import load_dotenv

load_dotenv()


def _required_secret(env_name: str) -> str:
    """Read a required cryptographic secret from the environment."""
    value = os.getenv(env_name, "").strip()
    if len(value) < 32:
        raise RuntimeError(
            f"{env_name} must be set and contain at least 32 characters"
        )
    return value


class WebConfig:
    # Used by the Timex-signed authentication, CSRF, and reset cookies.
    SECRET_KEY = _required_secret("WEB_SECRET_KEY")
    # Used by Starlette's request.session cookie. Keep it separate from SECRET_KEY.
    SESSION_MIDDLEWARE_SECRET_KEY = _required_secret("WEB_SESSION_MIDDLEWARE_SECRET_KEY")
    SESSION_COOKIE_NAME = "timex_session"
    RESET_COOKIE_NAME = "timex_reset_context"
    SESSION_MAX_AGE = 8 * 60 * 60  # 8 ساعت
    CSRF_MAX_AGE = 2 * 60 * 60  # اعتبار توکن CSRF: 2 ساعت

    HOST = os.getenv("WEB_HOST", "0.0.0.0")
    PORT = int(os.getenv("WEB_PORT", "8082"))

    ROLE_USER = "user"
    ROLE_ADMIN = "admin"
    ROLE_SUPER_ADMIN = "super_admin"

    RESET_CONTEXT_MAX_AGE = 10 * 60  # 10 دقیقه - زمان اعتبار ماشه بازنشانی رمز