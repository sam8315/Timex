"""
مدل انواع مرخصی
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class LeaveType(Base):
    """مدل جدول انواع مرخصی"""
    __tablename__ = "leave_types"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_quota_based: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<LeaveType(code='{self.code}', name='{self.name}')>"