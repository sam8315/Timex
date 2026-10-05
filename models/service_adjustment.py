"""
سوابق تعدیل خدمت (کسر / اضافه / سنوات مثبت) — معماری بدون موتور پایان خدمت.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


ADJUSTMENT_TYPES = (
    "service_deduction",
    "extra_service",
    "positive_seniority",
)


class ServiceAdjustment(Base):
    """ثبت اولیه immutable؛ اصلاح فقط با رکورد correction."""

    __tablename__ = "service_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("contracts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    adjustment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    years: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # active | corrected | void
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    corrects_adjustment_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("service_adjustments.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "adjustment_type IN ("
            "'service_deduction', 'extra_service', 'positive_seniority')",
            name="ck_service_adjustment_type",
        ),
        CheckConstraint(
            "status IN ('active', 'corrected', 'void')",
            name="ck_service_adjustment_status",
        ),
        CheckConstraint("years >= 0", name="ck_service_adj_years"),
        CheckConstraint("months >= 0 AND months < 12", name="ck_service_adj_months"),
        CheckConstraint("days >= 0", name="ck_service_adj_days"),
    )
