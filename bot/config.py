"""
تنظیمات ربات بله
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.orm import sessionmaker
from database.engine import engine

# 🆕 بارگذاری فایل .env از ریشه پروژه
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# 🔑 توکن ربات بله از .env
BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN")

# بررسی وجود توکن
if not BOT_TOKEN:
    raise ValueError(
        "❌ توکن ربات بله یافت نشد!\n"
        "   لطفاً BALE_BOT_TOKEN را در فایل .env تنظیم کنید."
    )

# Host without token — safe to mention in diagnostics.
BALE_API_HOST = "https://tapi.bale.ai"


def build_api_url(method: str) -> str:
    """
    Build a Bale method URL.

    WARNING: The returned value contains BOT_TOKEN.
    Never log this URL or pass it into log messages.
    """
    return f"{BALE_API_HOST}/bot{BOT_TOKEN}/{method}"


# Backward-compatible base (contains token). Prefer build_api_url() for new code.
# Do not log BALE_API_BASE.
BALE_API_BASE = f"{BALE_API_HOST}/bot{BOT_TOKEN}"

# Session دیتابیس
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ⏱️ تایم‌اوت long polling (ثانیه)
POLLING_TIMEOUT = 30

# کلیدواژه‌ها
KEYWORDS = {
    'today': ['today', 'امروز', 'تردد امروز', '📅 تردد امروز'],
    'yesterday': ['yesterday', 'دیروز', 'تردد دیروز', '📆 تردد دیروز'],
    'specific': ['specific', 'روز خاص', 'تردد یک روز خاص', '🗓️ تردد یک روز خاص'],
    'balance': ['balance', 'مانده', 'مرخصی', 'مانده مرخصی', '💰 مانده مرخصی', 'موجودی'],
    'web_panel': ['web', 'پنل وب', 'ورود به پنل وب', '🌐 ورود به پنل وب', 'وب', 'سایت'],  # 🆕
    'start': ['/start', 'start', 'شروع'],
}
