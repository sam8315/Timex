"""
مدل جدول درخواست‌های بازنشانی رمز عبور
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, BigInteger, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class PasswordResetRequest(TimestampMixin, Base):
    """مدل جدول درخواست‌های بازنشانی رمز عبور"""
    __tablename__ = "password_reset_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    otp_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship to User model
    user = relationship("User", backref="password_reset_requests")

    def __repr__(self) -> str:
        status = "Consumed" if self.consumed_at else "Active"
        return f"<PasswordResetRequest(id={self.id}, user_id='{self.user_id}', status='{status}')>"
