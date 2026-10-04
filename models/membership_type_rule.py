"""
نسخه‌های کامل Rule برای هر نوع عضویت (non-overlapping, snapshot-based).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class MembershipTypeRule(TimestampMixin, Base):
    """یک نسخه کامل از قواعد عضویت از effective_from به بعد."""

    __tablename__ = "membership_type_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(
        String(6),
        ForeignKey("membership_types.code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    annual_leave_base: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    supports_service_deduction: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    supports_extra_service: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    supports_positive_seniority: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # pending | scheduled | active | superseded
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    supersedes_rule_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("membership_type_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    membership_type = relationship("MembershipType", back_populates="rules")

    __table_args__ = (
        UniqueConstraint(
            "membership_type_code",
            "effective_from",
            name="uq_membership_rule_code_effective",
        ),
        CheckConstraint(
            "annual_leave_base >= 0",
            name="ck_membership_rule_annual_nonneg",
        ),
        CheckConstraint(
            "status IN ('pending', 'scheduled', 'active', 'superseded')",
            name="ck_membership_rule_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MembershipTypeRule(id={self.id}, code='{self.membership_type_code}', "
            f"from={self.effective_from}, annual={self.annual_leave_base})>"
        )
