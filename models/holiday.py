"""
مدل جدول تعطیلات
"""
from datetime import date
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

    def __repr__(self) -> str:
        return f"<Holiday(date={self.holiday_date}, title='{self.title}')>"