"""
تنظیمات و پیکربندی برنامه
"""
import os
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()

# تنظیمات دستگاه
DEVICE_IP = os.getenv("DEVICE_IP", "192.168.1.232")
DEVICE_PORT = int(os.getenv("DEVICE_PORT", 4370))
TIMEOUT = int(os.getenv("TIMEOUT", 30))

# تنظیمات دیتابیس PostgreSQL
DB_USER = os.getenv("DB_USER", "timex_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "timex_db")

# ساخت رشته اتصال (Connection String) برای SQLAlchemy
# فرمت: postgresql://user:password@host:port/dbname
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# تنظیمات برنامه
APP_NAME = "سیستم مدیریت حضور و غیاب"
APP_VERSION = "1.0.0"