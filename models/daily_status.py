"""
مدل جدول وضعیت روزانه (مأموریت و استراحت)
"""
from datetime import date
from typing import Optional
from sqlalchemy import Integer, String, Date, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


# کدهای وضعیت مجاز
STATUS_CODES = {
    'M': 'مأموریت',
    'R': 'استراحت',
}


class DailyStatus(TimestampMixin, Base):
    """مدل جدول وضعیت روزانه - فقط مأموریت و استراحت"""
    __tablename__ = "daily_statuses"

    # 🆕 جلوگیری از ثبت چند وضعیت برای یک روز
    __table_args__ = (
        UniqueConstraint('user_id', 'status_date', name='uq_user_date'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    status_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 🆕 فقط M (مأموریت) یا R (استراحت)
    status_code: Mapped[str] = mapped_column(String(1), nullable=False, index=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 🆕 چه کسی ثبت کرده (مدیر)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    user = relationship("User", backref="daily_statuses")

    def __repr__(self) -> str:
        return f"<DailyStatus(user_id='{self.user_id}', date={self.status_date}, status='{self.status_code}')>"

    @property
    def status_name(self) -> str:
        """نام فارسی وضعیت"""
        return STATUS_CODES.get(self.status_code, 'نامشخص')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'status_date': self.status_date.isoformat(),
            'status_code': self.status_code,
            'status_name': self.status_name,
            'description': self.description,
            'created_by': self.created_by,
        }