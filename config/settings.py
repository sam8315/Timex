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

# تنظیمات برنامه
APP_NAME = "سیستم مدیریت حضور و غیاب"
APP_VERSION = "1.0.0"