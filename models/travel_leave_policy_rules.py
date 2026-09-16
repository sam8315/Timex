"""Travel Leave policy distance rules and annual quotas."""
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class TravelLeavePolicyRule(TimestampMixin, Base):
    """Distance-to-days mapping rule for one Travel Leave policy."""
    __tablename__ = "travel_leave_policy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("travel_leave_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    min_km: Mapped[float] = mapped_column(Float, nullable=False)
    max_km: Mapped[float] = mapped_column(Float, nullable=False)
    travel_days: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)
    policy = relationship("TravelLeavePolicy", back_populates="rules")


class TravelLeaveQuotaSetting(TimestampMixin, Base):
    """Annual Travel Leave usage quota per policy and marital status."""
    __tablename__ = "travel_leave_quota_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(Integer, ForeignKey("travel_leave_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    marital_status: Mapped[str] = mapped_column(String(1), nullable=False)
    annual_max_usage: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameter_key: Mapped[str] = mapped_column(String(100), nullable=False)
    parameter_value: Mapped[str] = mapped_column(String(50), nullable=False)
    policy = relationship("TravelLeavePolicy", back_populates="quota_settings")
