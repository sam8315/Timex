"""
سیاست گزارش — تنظیمات نسخه‌دار و مستقل برای هر گزارش.

مستقل از AttendancePolicy؛ هر گزارش با `report_key` پایدار تنظیمات جدا دارد.
"""
from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class ReportPolicy(TimestampMixin, Base):
    __tablename__ = "report_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_key: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="شناسه پایدار گزارش، مثل legal_overtime_monthly",
    )
    effective_from_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    settings: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "effective_to_date IS NULL OR effective_to_date >= effective_from_date",
            name="ck_report_policies_date_order",
        ),
        Index("ix_report_policies_key_from", "report_key", "effective_from_date"),
        Index(
            "uq_report_policies_active_key_from",
            "report_key", "effective_from_date",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ReportPolicy({self.report_key}, from={self.effective_from_date}, "
            f"active={self.is_active})>"
        )
