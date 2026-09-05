"""Service regions used by annual leave policies."""
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Region(TimestampMixin, Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    default_annual_leave_days: Mapped[float] = mapped_column(Float, default=30.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
