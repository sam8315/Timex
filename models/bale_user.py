"""
مدل جدول کاربران ربات بله
نگاشت chat_id بله به user_id سیستم
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base


class BaleUser(Base):
    """جدول کاربران ربات بله"""
    __tablename__ = "bale_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # شناسه چت در بله (یکتا)
    chat_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        index=True
    )

    # ارتباط با جدول کاربران سیستم
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # شماره موبایل ثبت شده
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # وضعیت فعال بودن (برای /stop)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    # Relationships
    user = relationship("User", backref="bale_accounts")

    def __repr__(self) -> str:
        return f"<BaleUser(chat_id='{self.chat_id}', user_id='{self.user_id}')>"