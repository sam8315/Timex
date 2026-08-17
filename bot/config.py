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

# آدرس API بله
BALE_API_BASE = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# Session دیتابیس
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ⏱️ تایم‌اوت long polling (ثانیه)
POLLING_TIMEOUT = 30

# کلیدواژه‌ها
KEYWORDS = {
    'today': ['today', 'امروز', 'تردد امروز', '📅 تردد امروز'],
    'yesterday': ['yesterday', 'دیروز', 'تردد دیروز', '📆 تردد دیروز'],
    'specific': ['specific', 'روز خاص', 'تردد یک روز خاص', '🗓️ تردد یک روز خاص'],  # 🆕
    'balance': ['balance', 'مانده', 'مرخصی', 'مانده مرخصی', '💰 مانده مرخصی', 'موجودی'],  # 🆕
    'start': ['/start', 'start', 'شروع'],
}