"""
مدل جدول رکوردهای تردد
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class Attendance(TimestampMixin, Base):
    """مدل جدول رکوردهای تردد"""
    __tablename__ = "attendances"

    # فیلدهای اصلی
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
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

    # 🆕 فیلدهای جدید
    source: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        default='M',
        server_default='M',
        index=True,
        comment="منبع رکورد: D=Device, L=Legacy MySQL, M=Manual"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
        index=True,
        comment="حذف منطقی: true=حذف شده، false=فعال"
    )

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="attendances")

    # Constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'timestamp', name='uq_user_timestamp'),
    )

    # 🆕 ثابت‌های کلاس برای source
    SOURCE_DEVICE = 'D'
    SOURCE_LEGACY = 'L'
    SOURCE_MANUAL = 'M'

    def __repr__(self) -> str:
        return f"<Attendance(user_id={self.user_id}, timestamp={self.timestamp}, source={self.source})>"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'timestamp': self.timestamp,
            'status': self.status,
            'punch': self.punch,
            'source': self.source,
            'is_deleted': self.is_deleted,
            'synced_at': self.synced_at,
        }

    @staticmethod
    def get_source_name(source_code: str) -> str:
        """تبدیل کد منبع به نام خوانا"""
        names = {
            'D': '📱 دستگاه',
            'L': '📦 MySQL قدیمی',
            'M': '✋ دستی'
        }
        return names.get(source_code, f'نامشخص ({source_code})')