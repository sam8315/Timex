"""
مدل جدول قراردادها - نسخه نهایی
"""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import Boolean, Integer, String, Date, ForeignKey, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, object_session
from models.base import Base, TimestampMixin


class Contract(TimestampMixin, Base):
    """مدل جدول قراردادها"""
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # کد نوع عضویت (FK منطقی به membership_types.code؛ مقدار موجود تغییر نمی‌کند)
    contract_type_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # قرارداد رسمی هم ممکن است end_date داشته باشد (۲۰-۳۰ سال)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # مرخصی استحقاقی و استعلاجی (به روز) — backward compatibility snapshot
    annual_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # کسر خدمت (فقط وقتی Rule.supports_service_deduction)
    service_deduction_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # فیلدهای خدمت وظیفه (conscript) — nullable برای سایر عضویت‌ها
    dispatch_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    unit_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    clinic_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_native: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    service_duty_region_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user = relationship("User", backref="contracts")

    # Constraints
    __table_args__ = (
        CheckConstraint('annual_leave_days >= 0', name='check_annual_leave'),
        CheckConstraint('sick_leave_days >= 0', name='check_sick_leave'),
        CheckConstraint('service_deduction_days >= 0', name='check_deduction'),
    )

    def __repr__(self) -> str:
        return f"<Contract(user_id='{self.user_id}', type_code='{self.contract_type_code}')>"

    # ============================================
    # Properties
    # ============================================

    @property
    def contract_type_name(self) -> str:
        """نام فارسی نوع عضویت از membership_types."""
        session = object_session(self)
        if session is not None:
            try:
                from models.membership_type import MembershipType
                mt = session.get(MembershipType, self.contract_type_code)
                if mt is not None:
                    return mt.name
            except Exception:
                pass
        return f'نامشخص ({self.contract_type_code})'

    @property
    def allow_service_deduction(self) -> bool:
        """آیا کسر خدمت طبق Rule مؤثر مجاز است؟"""
        session = object_session(self)
        if session is not None:
            try:
                from web.services.membership_service import get_effective_rule
                rule = get_effective_rule(
                    session, self.contract_type_code, on_date=self.start_date
                )
                if rule is not None:
                    return bool(rule.supports_service_deduction)
            except Exception:
                pass
        return False

    @property
    def contract_duration_days(self) -> Optional[int]:
        """مدت قرارداد به روز"""
        if self.end_date is None:
            return None  # قرارداد باز
        return (self.end_date - self.start_date).days + 1

    @property
    def actual_end_date(self) -> Optional[date]:
        """تاریخ پایان واقعی با احتساب کسر خدمت"""
        if self.end_date is None:
            return None
        # مسیر موتور جدید وظیفه: end_date از قبل مؤثر است (تعدیل‌ها اعمال شده)
        if self.service_duty_region_code:
            return self.end_date
        if self.service_deduction_days > 0:
            return self.end_date - timedelta(days=self.service_deduction_days)
        return self.end_date


    @property
    def is_active(self) -> bool:
        """آیا قرارداد فعال است؟"""
        today = date.today()
        if self.actual_end_date is None:
            return self.start_date <= today
        return self.start_date <= today <= self.actual_end_date

    @property
    def status_name(self) -> str:
        """وضعیت قرارداد"""
        if self.is_active:
            return "✅ فعال"
        if self.actual_end_date and date.today() > self.actual_end_date:
            return "⏰ منقضی"
        return "⏳ در انتظار شروع"

    @property
    def prorated_annual_leave(self) -> int:
        """مرخصی استحقاقی تناسبی بر اساس مدت سپری شده قرارداد"""
        if self.start_date is None:
            return 0

        today = date.today()
        effective_end = min(today, self.end_date) if self.end_date else today

        if effective_end < self.start_date:
            return 0

        days_passed = (effective_end - self.start_date).days
        # محاسبه تناسبی: (روزهای سپری شده / 365) × کل مرخصی سالانه
        prorated = int((days_passed / 365.0) * self.annual_leave_days)
        return max(0, min(prorated, self.annual_leave_days))

    @property
    def prorated_sick_leave(self) -> int:
        """مرخصی استعلاجی تناسبی بر اساس مدت سپری شده قرارداد"""
        if self.start_date is None:
            return 0

        today = date.today()
        effective_end = min(today, self.end_date) if self.end_date else today

        if effective_end < self.start_date:
            return 0

        days_passed = (effective_end - self.start_date).days
        prorated = int((days_passed / 365.0) * self.sick_leave_days)
        return max(0, min(prorated, self.sick_leave_days))

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'contract_type_code': self.contract_type_code,
            'contract_type_name': self.contract_type_name,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'actual_end_date': self.actual_end_date.isoformat() if self.actual_end_date else None,
            'service_deduction_days': self.service_deduction_days,
            'annual_leave_days': self.annual_leave_days,
            'sick_leave_days': self.sick_leave_days,
            'prorated_annual_leave': self.prorated_annual_leave,
            'prorated_sick_leave': self.prorated_sick_leave,
            'is_active': self.is_active,
            'status_name': self.status_name,
        }
