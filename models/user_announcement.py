"""Per-user announcement acknowledgement model."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class UserAnnouncement(TimestampMixin, Base):
    __tablename__ = "user_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    announcement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("system_announcements.id", ondelete="CASCADE"), nullable=False
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now)

    user: Mapped["User"] = relationship("User", back_populates="user_read_states")
    announcement: Mapped["SystemAnnouncement"] = relationship(
        "SystemAnnouncement", back_populates="user_read_states"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "announcement_id", name="uq_user_announcements_user_announcement"),
        Index("ix_user_announcements_user", "user_id"),
        Index("ix_user_announcements_user_seen", "user_id", "seen_at"),
    )
