"""
مدل جدول درخواست‌های مرخصی
"""
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import Integer, String, Date, DateTime, Time, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


# وضعیت‌های درخواست
STATUS_CODES = {
    'P': '⏳ در انتظار',
    'A': '✅ تایید شده',
    'R': '❌ رد شده',
    'D': '🗑️ حذف شده',
}


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

    # Hourly Leave time fields (Phase 7) — only for leave_type='HL'
    start_time: Mapped[Optional[time]] = mapped_column(
        Time,
        nullable=True,
        comment="ساعت شروع (فقط برای مرخصی ساعتی)"
    )
    end_time: Mapped[Optional[time]] = mapped_column(
        Time,
        nullable=True,
        comment="ساعت پایان (فقط برای مرخصی ساعتی)"
    )

    # وضعیت: P=Pending, A=Approved, R=Rejected, D=Deleted
    status: Mapped[str] = mapped_column(String(1), default='P', nullable=False, index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="leave_requests")
    # 🆕 حذف daily_statuses (چون DailyStatus دیگر leave_request_id ندارد)

    def __repr__(self) -> str:
        return f"<LeaveRequest(user_id='{self.user_id}', type='{self.leave_type}', status='{self.status}')>"

    @property
    def status_name(self) -> str:
        """نام فارسی وضعیت"""
        return STATUS_CODES.get(self.status, 'نامشخص')

    @property
    def leave_type_name(self) -> str:
        """نام فارسی نوع مرخصی"""
        types = {
            'AL': 'استحقاقی',
            'SL': 'استعلاجی',
            'RL': 'تشویقی',
        }
        return types.get(self.leave_type, self.leave_type)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'leave_type': self.leave_type,
            'leave_type_name': self.leave_type_name,
            'from_date': self.from_date.isoformat(),
            'to_date': self.to_date.isoformat(),
            'days_count': self.days_count,
            'reason': self.reason,
            'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
            'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
            'status': self.status,
            'status_name': self.status_name,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejection_reason': self.rejection_reason,
        }