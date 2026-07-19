"""
مدل وضعیت روزانه
"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import Integer, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class DailyStatus(Base):
    """مدل جدول وضعیت روزانه"""
    __tablename__ = "daily_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    leave_request_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("leave_requests.id", ondelete="SET NULL"),
        nullable=True
    )
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
        return f"<DailyStatus(user_id='{self.user_id}', date={self.status_date}, status='{self.status_code}')>"