"""
مدل درخواست‌های مرخصی
"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Integer, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class LeaveRequest(Base):
    """مدل جدول درخواست‌های مرخصی"""
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    leave_type: Mapped[str] = mapped_column(
        String(2),
        ForeignKey("leave_types.code"),
        nullable=False,
        index=True
    )
    from_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    to_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(1), default='A', nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<LeaveRequest(user_id='{self.user_id}', type='{self.leave_type}', status='{self.status}')>"