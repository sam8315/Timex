"""Travel Leave distance-band rules and annual quota."""
from typing import Optional

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class TravelLeavePolicyRule(TimestampMixin, Base):
    """Distance-to-days mapping rule for Travel Leave."""

    __tablename__ = "travel_leave_policy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    min_km: Mapped[float] = mapped_column(Float, nullable=False)
    max_km: Mapped[float] = mapped_column(Float, nullable=False)
    travel_days: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<TravelLeavePolicyRule({self.min_km}-{self.max_km}km "
            f"=> {self.travel_days} days)>"
        )


class TravelLeaveQuotaSetting(TimestampMixin, Base):
    """Configurable annual Travel Leave usage quota."""

    __tablename__ = "travel_leave_quota_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    annual_max_usage: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameter_key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    parameter_value: Mapped[str] = mapped_column(String(50), nullable=False)
