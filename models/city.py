"""Reference city entity for Travel Leave origin/destination."""
from typing import Optional

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class City(TimestampMixin, Base):
    """Active reference city with geographic coordinates and service region."""

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    province: Mapped[Optional[str]] = mapped_column(String(100))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Service region grade (NORMAL / GRADE_1..3); source of truth for employee region
    region_code: Mapped[str] = mapped_column(
        String(20), nullable=False, default='NORMAL', server_default='NORMAL',
    )
