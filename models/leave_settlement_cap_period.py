"""
بازه‌های تاریخ‌دار سقف ذخیره (سالانه) و بازخرید — به‌ازای عضویت و اختیاری منطقه.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class LeaveSettlementCapPeriod(TimestampMixin, Base):
    """یک بازه سیاست: از/تا + سقف ذخیره/سال + سقف بازخرید."""

    __tablename__ = "leave_settlement_cap_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_code: Mapped[str] = mapped_column(
        String(6),
        ForeignKey("membership_types.code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = سطح عضویت (بدون منطقه)
    region_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        ForeignKey("regions.code", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # NULL = نامحدود
    storage_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    buyback_cap: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    membership_type = relationship("MembershipType", lazy="joined")
    region = relationship("Region", lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "storage_cap IS NULL OR storage_cap >= 0",
            name="ck_settlement_cap_storage_nonneg",
        ),
        CheckConstraint(
            "buyback_cap IS NULL OR buyback_cap >= 0",
            name="ck_settlement_cap_buyback_nonneg",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_settlement_cap_range_order",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LeaveSettlementCapPeriod(id={self.id}, mem={self.membership_code!r}, "
            f"region={self.region_code!r}, from={self.effective_from}, "
            f"storage={self.storage_cap}, buyback={self.buyback_cap})>"
        )
