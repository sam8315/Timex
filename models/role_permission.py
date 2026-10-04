"""مدل پیش‌فرض دسترسی نقش‌ها + تاریخچه ممیزی"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, Boolean, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class RolePermission(Base):
    """پیش‌فرض دسترسی برای یک نقش (منبع حقیقت قابل‌ویرایش از UI)."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "permission", name="uq_role_permissions_role_perm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(100), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    updated_by: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=True
    )


class RolePermissionHistory(Base):
    """لاگ الحاقی تغییرات پیش‌فرض نقش."""

    __tablename__ = "role_permission_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # enable / disable
    granted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
