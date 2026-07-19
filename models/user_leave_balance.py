"""
مدل موجودی مرخصی کاربران
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class UserLeaveBalance(Base):
    """مدل جدول موجودی مرخصی کاربران"""
    __tablename__ = "user_leave_balance"

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
    total_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
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

    @property
    def remaining_days(self) -> int:
        return self.total_days - self.used_days

    def __repr__(self) -> str:
        return f"<UserLeaveBalance(user_id='{self.user_id}', type='{self.leave_type}', remaining={self.remaining_days})>"