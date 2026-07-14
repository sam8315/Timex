"""
پایه مشترک برای همه مدل‌های دیتابیس
"""
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """کلاس پایه برای همه مدل‌ها"""
    pass


class TimestampMixin:
    """Mixin برای اضافه کردن فیلدهای created_at و updated_at به مدل‌ها"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )