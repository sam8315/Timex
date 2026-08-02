"""
مدل جدول درخواست‌های مرخصی
"""
from datetime import date, datetime
from typing import Optional
from sqlalchemy import Integer, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class LeaveRequest(TimestampMixin, Base):
    """مدل جدول درخواست‌های مرخصی"""
    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    leave_type: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    from_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    to_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # وضعیت: P=Pending, A=Approved, R=Rejected
    status: Mapped[str] = mapped_column(String(1), default='P', nullable=False, index=True)

    approved_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="leave_requests")
    daily_statuses = relationship("DailyStatus", back_populates="leave_request")

    def __repr__(self) -> str:
        return f"<LeaveRequest(user_id='{self.user_id}', type='{self.leave_type}', status='{self.status}')>"