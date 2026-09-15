"""Travel Leave policy scoped by contract type (Membership)."""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class TravelLeavePolicy(TimestampMixin, Base):
    """Travel Leave policy for one contract type / membership."""

    __tablename__ = "travel_leave_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    distance_method: Mapped[str] = mapped_column(
        String(30), default="geographic", nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    rules = relationship(
        "TravelLeavePolicyRule",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="TravelLeavePolicyRule.min_km",
    )
    quota_settings = relationship(
        "TravelLeaveQuotaSetting",
        back_populates="policy",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "contract_type_code",
            name="uq_travel_leave_policy_contract_type",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TravelLeavePolicy(contract_type_code='{self.contract_type_code}', "
            f"enabled={self.is_enabled}, method='{self.distance_method}')>"
        )
