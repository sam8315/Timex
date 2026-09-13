"""System announcement model."""
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class SystemAnnouncement(TimestampMixin, Base):
    __tablename__ = "system_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    announcement_type: Mapped[str] = mapped_column(String(30), nullable=False, default="feature")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )

    user_read_states: Mapped[list["UserAnnouncement"]] = relationship(
        "UserAnnouncement",
        back_populates="announcement",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_system_announcements_active_published", "is_active", "published_at"),
        Index("ix_system_announcements_expires_at", "expires_at"),
    )
