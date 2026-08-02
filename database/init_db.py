"""
مدیریت ساخت و مقداردهی اولیه جداول دیتابیس
"""
from sqlalchemy import inspect
from database.engine import engine
from models import Base


def create_tables() -> None:
    """
    ساخت تمام جداول تعریف شده در مدل‌ها
    اگر جدول از قبل وجود داشته باشد، تغییری ایجاد نمی‌کند
    """
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ جداول دیتابیس با موفقیت ساخته/بررسی شدند")
    except Exception as e:
        print(f"❌ خطا در ساخت جداول: {e}")
        raise


def check_tables() -> None:
    """بررسی و نمایش جداول موجود در دیتابیس"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if not tables:
        print("⚠️  هیچ جدولی در دیتابیس وجود ندارد")
        return

    print(f"\n📊 جداول موجود در دیتابیس ({len(tables)} جدول):")
    for table in tables:
        columns = inspector.get_columns(table)
        print(f"  • {table} ({len(columns)} ستون)")


def drop_all_tables() -> None:
    """
    حذف تمام جداول (فقط برای توسعه - با احتیاط استفاده شود!)
    """
    try:
        Base.metadata.drop_all(bind=engine)
        print("⚠️  تمام جداول حذف شدند")
    except Exception as e:
        print(f"❌ خطا در حذف جداول: {e}")
        raise


if __name__ == "__main__":
    # اجرای مستقیم برای تست
    print("🔧 در حال ساخت جداول...")
    create_tables()
    check_tables()