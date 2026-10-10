"""
مدل جدول تعطیلات
"""
from datetime import date
from typing import Optional
from sqlalchemy import Integer, String, Date, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, TimestampMixin


class Holiday(TimestampMixin, Base):
    """مدل جدول تعطیلات"""
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_national: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    group_id: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)  # 🆕

    def __repr__(self) -> str:
        return f"<Holiday(date={self.holiday_date}, title='{self.title}', group='{self.group_id}')>"

    @property
    def group_name(self) -> str:
        """نام گروه تعطیل. NULL یعنی ملی. مقدار غیرخالی کد نوع عضویت است."""
        if self.group_id is None:
            return "ملی (همه)"
        session = None
        try:
            from sqlalchemy.orm import object_session
            session = object_session(self)
        except Exception:
            session = None
        if session is not None:
            try:
                from models.membership_type import MembershipType
                row = session.get(MembershipType, self.group_id)
                if row is not None:
                    return row.name
            except Exception:
                pass
        return f"گروه {self.group_id}"