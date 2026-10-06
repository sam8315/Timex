"""مناطق/وضعیت خدمت وظیفه — مدت خدمت قابل تعریف در پالیسی (بدون هاردکد)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, String, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class ServiceDutyRegion(TimestampMixin, Base):
    """منطقه خدمت وظیفه با مدت ماه دقیق و فلگ اثر بومی/غیربومی."""

    __tablename__ = "service_duty_regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    native_affects: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_months_native: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_months_non_native: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "("
            "(native_affects = FALSE AND duration_months IS NOT NULL AND duration_months > 0)"
            " OR "
            "(native_affects = TRUE AND duration_months_native IS NOT NULL "
            "AND duration_months_native > 0 "
            "AND duration_months_non_native IS NOT NULL "
            "AND duration_months_non_native > 0)"
            ")",
            name="ck_service_duty_region_duration",
        ),
    )

    def __repr__(self) -> str:
        return f"<ServiceDutyRegion(code={self.code!r}, name={self.name!r})>"
