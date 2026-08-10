"""
مدل جدول درخواست‌های انتقال/بازخرید مرخصی
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


# وضعیت‌های درخواست
REQUEST_STATUS = {
    'P': '⏳ در انتظار بررسی',
    'A': '✅ تایید شده (قصد استفاده)',
    'C': '💰 بازخرید تایید شد',
    'R': '🔄 رد شد → انتقال به سال جدید',
}


class LeaveCarryForwardRequest(TimestampMixin, Base):
    """مدل جدول درخواست‌های انتقال/بازخرید مرخصی"""
    __tablename__ = "leave_carry_forward_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    from_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    to_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(2), nullable=False)
    days_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # انتخاب کاربر: USE = قصد استفاده, CASH = بازخرید
    user_choice: Mapped[str] = mapped_column(String(4), nullable=False)

    # وضعیت: P = در انتظار, A = تایید استفاده, C = تایید بازخرید, R = رد بازخرید
    status: Mapped[str] = mapped_column(String(1), default='P', nullable=False, index=True)

    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    user = relationship("User", backref="carry_forward_requests")

    def __repr__(self) -> str:
        return f"<LeaveCarryForwardRequest(user_id='{self.user_id}', from={self.from_year}, choice='{self.user_choice}', status='{self.status}')>"

    @property
    def status_name(self) -> str:
        return REQUEST_STATUS.get(self.status, 'نامشخص')

    @property
    def user_choice_name(self) -> str:
        return 'قصد استفاده' if self.user_choice == 'USE' else 'درخواست بازخرید'