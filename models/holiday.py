"""
مدل تعطیلات
"""
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import Integer, String, DateTime, Date, Boolean, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class Holiday(Base):
    """مدل جدول تعطیلات"""
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_national: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    group_ids: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<Holiday(date={self.holiday_date}, title='{self.title}')>"