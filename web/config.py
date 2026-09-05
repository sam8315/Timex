"""تنظیمات وب"""
import os
from dotenv import load_dotenv

load_dotenv()


class WebConfig:
    SECRET_KEY = os.getenv("WEB_SECRET_KEY", "timex-change-this-secret-key-2026")
    SESSION_COOKIE_NAME = "timex_session"
    SESSION_MAX_AGE = 8 * 60 * 60  # 8 ساعت
    CSRF_MAX_AGE = 2 * 60 * 60  # اعتبار توکن CSRF: 2 ساعت

    HOST = os.getenv("WEB_HOST", "0.0.0.0")
    PORT = int(os.getenv("WEB_PORT", "8082"))

    ROLE_USER = "user"
    ROLE_ADMIN = "admin"
    ROLE_SUPER_ADMIN = "super_admin"