"""دستور صریح اعمال اثر مالی مرخصی استعلاجی. خودش فیش نمی‌سازد."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class LeaveFinancialOrder(TimestampMixin, Base):
    __tablename__ = "leave_financial_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leave_request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    year_j: Mapped[int] = mapped_column(Integer, nullable=False)
    month_j: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("payroll_runs.id", ondelete="SET NULL"), nullable=True
    )
    # recalc | next_period | reopen | unspecified
    resolution: Mapped[str] = mapped_column(String(20), nullable=False, default="unspecified")
    # pending | applied | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    before_amounts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_amounts_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "order_type IN ('initial', 'change', 'cancel')",
            name="ck_leave_financial_orders_type",
        ),
        CheckConstraint(
            "resolution IN ('recalc', 'next_period', 'reopen', 'unspecified')",
            name="ck_leave_financial_orders_resolution",
        ),
        CheckConstraint(
            "status IN ('pending', 'applied', 'rejected')",
            name="ck_leave_financial_orders_status",
        ),
    )
