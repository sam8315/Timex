"""Employee service-region history."""
from datetime import date
from typing import Optional

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class EmployeeRegion(TimestampMixin, Base):
    __tablename__ = "employee_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    region_code: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date)
    approved_by: Mapped[Optional[str]] = mapped_column(String(50))
    reason: Mapped[Optional[str]] = mapped_column(String(500))
