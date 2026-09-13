"""
مدل جدول پیام‌های سیستمی (اعلان‌ها)
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class SystemAnnouncement(TimestampMixin, Base):
    """مدل جدول پیام‌های سیستمی"""
    __tablename__ = "system_announcements"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    version: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    summary: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    announcement_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="general", index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Relationships
    user_read_states: Mapped[list["UserAnnouncement"]] = relationship(
        "UserAnnouncement",
        back_populates="announcement",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<SystemAnnouncement(id={self.id}, title='{self.title}', active={self.is_active})>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "announcement_type": self.announcement_type,
            "is_active": self.is_active,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "expires_at": (
                self.expires_at.isoformat() if self.expires_at else None
            ),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
