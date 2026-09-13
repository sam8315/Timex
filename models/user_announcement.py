"""
مدل جدول وضعیت دیده‌شده پیام‌های کاربر
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class UserAnnouncement(TimestampMixin, Base):
    """مدل جدول وضعیت دیده‌شده پیام‌ها برای هر کاربر"""
    __tablename__ = "user_announcements"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("system_announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "user_id", "announcement_id",
            name="uq_user_announcements_user_announcement"
        ),
        Index("ix_user_announcements_user_announcement", "user_id", "announcement_id"),
        Index("ix_user_announcements_user_seen", "user_id", "seen_at"),
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    announcement: Mapped["SystemAnnouncement"] = relationship(
        "SystemAnnouncement", back_populates="user_read_states"
    )

    def __repr__(self) -> str:
        return (
            f"<UserAnnouncement(user_id='{self.user_id}', "
            f"announcement_id={self.announcement_id}, seen_at={self.seen_at})>"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "announcement_id": self.announcement_id,
            "seen_at": self.seen_at.isoformat() if self.seen_at else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
