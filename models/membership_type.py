"""
انواع عضویت قابل مدیریت از دیتابیس (جایگزین CONTRACT_TYPES).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


BEHAVIOR_PERMANENT = "permanent"
BEHAVIOR_CONSCRIPT = "conscript"
BEHAVIOR_PHYSICIAN = "physician"
BEHAVIOR_STANDARD_PRORATE = "standard_prorate"

BEHAVIOR_PROFILES = (
    BEHAVIOR_PERMANENT,
    BEHAVIOR_CONSCRIPT,
    BEHAVIOR_PHYSICIAN,
    BEHAVIOR_STANDARD_PRORATE,
)


class MembershipType(TimestampMixin, Base):
    """مرجع انواع عضویت — code پایدار و یکتا (عدد مثبت حداکثر ۶ رقم)."""

    __tablename__ = "membership_types"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    code_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Domain semantics key — نه presentation و نه annual leave base
    behavior_profile: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=BEHAVIOR_STANDARD_PRORATE,
        server_default=BEHAVIOR_STANDARD_PRORATE,
    )

    rules = relationship(
        "MembershipTypeRule",
        back_populates="membership_type",
        cascade="all, delete-orphan",
        order_by="MembershipTypeRule.effective_from",
    )

    __table_args__ = (
        CheckConstraint(
            "code ~ '^[1-9][0-9]{0,5}$'",
            name="ck_membership_types_code_positive",
        ),
        CheckConstraint(
            "behavior_profile IN ("
            "'permanent', 'conscript', 'physician', 'standard_prorate')",
            name="ck_membership_types_behavior_profile",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MembershipType(code='{self.code}', name='{self.name}', "
            f"active={self.is_active}, profile={self.behavior_profile})>"
        )
