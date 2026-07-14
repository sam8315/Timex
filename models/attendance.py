"""
مدل جدول رکوردهای تردد
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class Attendance(TimestampMixin, Base):
    """مدل جدول رکوردهای تردد"""
    __tablename__ = "attendances"

    # فیلدهای اصلی
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.uid", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    punch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="attendances")

    # Constraint: یک کاربر در یک زمان خاص، فقط یک رکورد داشته باشد
    __table_args__ = (
        UniqueConstraint('user_id', 'timestamp', name='uq_user_timestamp'),
    )

    def __repr__(self) -> str:
        return f"<Attendance(user_id={self.user_id}, timestamp={self.timestamp})>"

    def to_dict(self) -> dict:
        """تبدیل مدل به دیکشنری"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'timestamp': self.timestamp,
            'status': self.status,
            'punch': self.punch,
            'synced_at': self.synced_at,
        }