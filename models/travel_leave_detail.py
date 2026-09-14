"""Travel Leave detail linked 1:1 to LeaveRequest."""
from sqlalchemy import Integer, Float, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin

class TravelLeaveDetail(Base, TimestampMixin):
    __tablename__ = "travel_leave_details"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leave_request_id: Mapped[int] = mapped_column(Integer, ForeignKey("leave_requests.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    origin_city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"), nullable=True)
    destination_city_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cities.id"), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    travel_days_calculated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    travel_days_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    travel_policy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("policies.id"), nullable=True)
    travel_policy_rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leave_request = relationship("LeaveRequest", backref="travel_leave_detail")
