"""
مدل‌های ماژول حقوق و دستمزد
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


COMPONENT_KINDS = ("earning", "deduction")
CALC_MODES = (
    "daily_x_covered",
    "fixed_monthly_prorata",
    "seniority_chain",
    "friday_attendance",
    "manual",
    "policy_eidi",
    "policy_bonus",
    "percent_insurance",
    "percent_tax",
    "child_allowance",
    "overtime_policy",
    "holiday_work",
    "work_deficit",
    "shift_policy",
    "night_work",
)
RUN_STATUSES = ("draft", "calculated", "approved", "published")


class PayrollComponent(TimestampMixin, Base):
    __tablename__ = "payroll_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    calc_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_to_insurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_to_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    assignments: Mapped[List["PayrollAssignment"]] = relationship(
        back_populates="component", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("kind IN ('earning', 'deduction')", name="ck_payroll_components_kind"),
    )


class PayrollAnnualLaw(TimestampMixin, Base):
    __tablename__ = "payroll_annual_laws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year_j: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    new_seniority_daily: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    wage_increase_factor: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("1")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="1")
    source_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("year_j", "version", name="uq_payroll_annual_laws_year_version"),
    )


class PayrollRateSettings(TimestampMixin, Base):
    __tablename__ = "payroll_rate_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    insurance_employee_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("7")
    )
    tax_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    friday_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("1.96")
    )
    eidi_payment_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    bonus_payment_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    eidi_day_factor: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("60")
    )
    bonus_day_factor: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("0")
    )
    hours_per_day: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("7.3333")
    )


class PayrollAssignment(TimestampMixin, Base):
    __tablename__ = "payroll_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    membership_type_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    component: Mapped["PayrollComponent"] = relationship(back_populates="assignments")


class PayrollPeriod(TimestampMixin, Base):
    __tablename__ = "payroll_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year_j: Mapped[int] = mapped_column(Integer, nullable=False)
    month_j: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    runs: Mapped[List["PayrollRun"]] = relationship(
        back_populates="period", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("year_j", "month_j", name="uq_payroll_periods_ym"),
    )


class PayrollRun(TimestampMixin, Base):
    __tablename__ = "payroll_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    membership_type_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    component_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    calculated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    period: Mapped["PayrollPeriod"] = relationship(back_populates="runs")
    results: Mapped[List["PayrollResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    manual_entries: Mapped[List["PayrollManualEntry"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    shift_choices: Mapped[List["PayrollShiftChoice"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class PayrollResult(TimestampMixin, Base):
    __tablename__ = "payroll_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    membership_type_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    covered_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    month_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    gross_earnings: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))

    run: Mapped["PayrollRun"] = relationship(back_populates="results")
    items: Mapped[List["PayrollResultItem"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "user_id", name="uq_payroll_results_run_user"),
    )


class PayrollResultItem(TimestampMixin, Base):
    __tablename__ = "payroll_result_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("payroll_components.id", ondelete="SET NULL"), nullable=True
    )
    component_code: Mapped[str] = mapped_column(String(40), nullable=False)
    component_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    unit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    calc_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subject_to_insurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subject_to_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    result: Mapped["PayrollResult"] = relationship(back_populates="items")


class PayrollMinimumWage(TimestampMixin, Base):
    """حداقل مزد روزانه هر سال شمسی، قابل تفکیک بر اساس نوع عضویت.

    membership_type_code خالی یعنی پیش‌فرض همان سال برای عضویت‌هایی که ردیف اختصاصی ندارند.
    """

    __tablename__ = "payroll_minimum_wages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year_j: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    membership_type_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    daily_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    source_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class PayrollChildAllowancePolicy(TimestampMixin, Base):
    """سیاست حق اولاد به‌ازای نوع عضویت. هیچ قاعده‌ای در کد ثابت نیست."""

    __tablename__ = "payroll_child_allowance_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    applies_to_female: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    age_limit_years: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    require_study_above_age: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wage_day_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("3")
    )
    count_only_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PayrollOvertimePolicy(TimestampMixin, Base):
    """سیاست اضافه‌کار به‌ازای نوع عضویت.

    basis_codes کد آیتم‌هایی است که مبلغ ماهانه‌شان مبنای مزد اضافه‌کار است.
    method برابر monthly_div یعنی جمع مبنا ÷ divisor.
    method برابر hourly_x_factor یعنی (جمع مبنا ÷ ordinary_month_hours) × premium_factor.
    """

    __tablename__ = "payroll_overtime_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    method: Mapped[str] = mapped_column(String(40), nullable=False, default="monthly_div")
    basis_codes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    divisor: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("157"))
    premium_factor: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("1.4")
    )
    ordinary_month_hours: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("220")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("membership_type_code", name="uq_payroll_overtime_membership"),
    )

    @property
    def basis_code_list(self) -> List[str]:
        return [c.strip() for c in (self.basis_codes or "").split(",") if c.strip()]


class PayrollDeficitPolicy(TimestampMixin, Base):
    """سیاست کسر کار: نرخ برابر یک ساعت عادی از آیتم‌های مبنا."""

    __tablename__ = "payroll_deficit_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    basis_codes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ordinary_month_hours: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("220")
    )
    basis_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=Decimal("30"))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("membership_type_code", name="uq_payroll_deficit_membership"),
    )

    @property
    def basis_code_list(self) -> List[str]:
        return [c.strip() for c in (self.basis_codes or "").split(",") if c.strip()]


class PayrollShiftPolicy(TimestampMixin, Base):
    """سیاست نوبت‌کاری به‌ازای نوع عضویت.

    درصد هر ترکیب شیفت و آیتم‌های داخل مبنا در سیاست ذخیره می‌شوند.
    ترکیب از ساعات صبح، عصر و شب همان ماه تشخیص داده می‌شود.
    """

    __tablename__ = "payroll_shift_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    basis_codes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pct_morning_evening: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("10")
    )
    pct_morning_evening_night: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("15")
    )
    pct_morning_night: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("22.5")
    )
    pct_evening_night: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("22.5")
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("membership_type_code", name="uq_payroll_shift_membership"),
    )

    @property
    def basis_code_list(self) -> List[str]:
        return [c.strip() for c in (self.basis_codes or "").split(",") if c.strip()]


class PayrollNightPolicy(TimestampMixin, Base):
    """سیاست شب‌کاری به‌ازای نوع عضویت.

    درصد روی مزد ساعتی و نوع نوبت‌هایی که این فوق‌العاده را نمی‌گیرند در سیاست است.
    ساعات شب همان بازه ۲۲:۰۰ تا ۰۶:۰۰ گزارش کارکرد است.
    """

    __tablename__ = "payroll_night_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    premium_percent: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=False, default=Decimal("35")
    )
    excluded_patterns: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("membership_type_code", name="uq_payroll_night_membership"),
    )

    @property
    def excluded_pattern_list(self) -> List[str]:
        return [c.strip() for c in (self.excluded_patterns or "").split(",") if c.strip()]


class PayrollEnabledMembership(Base):
    """عضویت‌هایی که در فرم «حقوق جدید» قابل انتخاب‌اند. خالی = همهٔ فعال."""

    __tablename__ = "payroll_enabled_memberships"

    membership_type_code: Mapped[str] = mapped_column(
        String(10),
        ForeignKey("membership_types.code", ondelete="CASCADE"),
        primary_key=True,
    )


class PayrollShiftChoice(TimestampMixin, Base):
    """نوع نوبت انتخاب‌شده برای هر نفر در یک اجرای حقوق."""

    __tablename__ = "payroll_shift_choices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    pattern: Mapped[str] = mapped_column(String(40), nullable=False, default="none")

    run: Mapped["PayrollRun"] = relationship(back_populates="shift_choices")

    __table_args__ = (
        UniqueConstraint("run_id", "user_id", name="uq_payroll_shift_choice_run_user"),
    )


class PayrollManualEntry(TimestampMixin, Base):
    __tablename__ = "payroll_manual_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    component_code: Mapped[str] = mapped_column(String(40), nullable=False, default="SHIFT")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["PayrollRun"] = relationship(back_populates="manual_entries")

    __table_args__ = (
        UniqueConstraint("run_id", "user_id", "component_code", name="uq_payroll_manual_run_user_comp"),
        Index("ix_payroll_manual_run_user", "run_id", "user_id"),
    )
