"""Travel Leave detail — optional 1:1 extension of an AL LeaveRequest."""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class TravelLeaveDetail(TimestampMixin, Base):
    """Persisted snapshot of a Travel Leave calculation attached to an AL request."""

    __tablename__ = "travel_leave_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leave_request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # --- Origin (resolved server-side from effective service location) ---
    origin_service_location_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("employee_service_locations.id"), nullable=True
    )
    origin_city_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cities.id"), nullable=True
    )
    origin_city_name_snapshot: Mapped[Optional[str]] = mapped_column(String(100))
    origin_latitude_snapshot: Mapped[Optional[float]] = mapped_column(Float)
    origin_longitude_snapshot: Mapped[Optional[float]] = mapped_column(Float)

    # --- Destination (validated against City reference) ---
    destination_city_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cities.id"), nullable=False
    )
    destination_city_name_snapshot: Mapped[str] = mapped_column(String(100))
    destination_province_snapshot: Mapped[Optional[str]] = mapped_column(String(100))
    destination_latitude_snapshot: Mapped[float] = mapped_column(Float)
    destination_longitude_snapshot: Mapped[float] = mapped_column(Float)

    # --- Calculation ---
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    calculated_travel_days: Mapped[int] = mapped_column(Integer, nullable=False)
    final_travel_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Manual override ---
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overridden_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    overridden_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Policy snapshots ---
    policy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    policy_rule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    annual_max_usage_snapshot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rule_min_km_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rule_max_km_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rule_travel_days_snapshot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Jalali year for quota ---
    jalali_year: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Timestamps for lifecycle ---
    calculated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relationship ---
    leave_request = relationship("LeaveRequest", backref="travel_leave_detail")
