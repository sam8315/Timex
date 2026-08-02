"""
مدیریت اتصال به دیتابیس و Sessionها
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from config.settings import DATABASE_URL

# ایجاد موتور اتصال با تنظیمات بهینه
engine = create_engine(
    DATABASE_URL,
    pool_size=10,  # حداکثر 10 اتصال همزمان
    max_overflow=20,  # 20 اتصال اضافی در زمان شلوغی
    pool_pre_ping=True,  # بررسی سلامت اتصال قبل از استفاده
    echo=False  # برای دیباگ می‌توانید True کنید تا SQLها نمایش داده شوند
)

# ساخت SessionMaker
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Session:
    """
    دریافت یک Session از دیتابیس
    استفاده به صورت Context Manager:

    with get_db() as db:
        db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()