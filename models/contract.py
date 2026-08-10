"""
مدل جدول قراردادها - نسخه نهایی
"""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import Integer, String, Date, ForeignKey, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


# 🆕 انواع قرارداد (کد → مشخصات)
CONTRACT_TYPES = {
    '1': {
        'name': 'رسمی',
        'annual_leave': 35,       # ۳۵ روز استحقاقی
        'sick_leave': 120,        # ۴ ماه = ۱۲۰ روز
        'allow_service_deduction': False,
        'editable_leave': False,   # مرخصی قابل ویرایش نیست
    },
    '2': {
        'name': 'وظیفه',
        'annual_leave': 35,
        'sick_leave': 30,         # ۱ ماه
        'allow_service_deduction': True,  # ✅ کسر خدمت دارد
        'editable_leave': False,
    },
    '3': {
        'name': 'خریدخدمت',
        'annual_leave': 30,
        'sick_leave': 30,
        'allow_service_deduction': False,
        'editable_leave': False,
    },
    '4': {
        'name': 'قراردادی',
        'annual_leave': 30,
        'sick_leave': 30,         # ۱ ماه
        'allow_service_deduction': False,
        'editable_leave': False,
    },
    '5': {
        'name': 'پزشک',
        'annual_leave': 0,
        'sick_leave': 0,
        'allow_service_deduction': False,
        'editable_leave': False,
    },
    '6': {
        'name': 'سایر / متفرقه',
        'annual_leave': 0,
        'sick_leave': 0,
        'allow_service_deduction': False,
        'editable_leave': True,    # ✅ مرخصی قابل تعریف است
    },
    '7': {
        'name': 'قرارداد با بیمه‌ها',
        'annual_leave': 0,
        'sick_leave': 0,
        'allow_service_deduction': False,
        'editable_leave': True,    # ✅ مرخصی قابل تعریف است
    },
}


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

    # 🆕 کد نوع قرارداد (1=رسمی، 2=وظیفه، ...، 7=بیمه‌ها)
    contract_type_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # قرارداد رسمی هم ممکن است end_date داشته باشد (۲۰-۳۰ سال)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # مرخصی استحقاقی و استعلاجی (به روز)
    annual_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 🆕 کسر خدمت (فقط برای وظیفه)
    service_deduction_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
        """نام فارسی نوع قرارداد"""
        return CONTRACT_TYPES.get(
            self.contract_type_code, {}
        ).get('name', f'نامشخص ({self.contract_type_code})')

    @property
    def allow_service_deduction(self) -> bool:
        """آیا کسر خدمت مجاز است؟"""
        return CONTRACT_TYPES.get(
            self.contract_type_code, {}
        ).get('allow_service_deduction', False)

    @property
    def contract_duration_days(self) -> Optional[int]:
        """مدت قرارداد به روز"""
        if self.end_date is None:
            return None  # قرارداد باز
        return (self.end_date - self.start_date).days

    @property
    def actual_end_date(self) -> Optional[date]:
        """تاریخ پایان واقعی با احتساب کسر خدمت"""
        if self.end_date is None:
            return None
        if self.service_deduction_days > 0:
            return self.end_date - timedelta(days=self.service_deduction_days)
        return self.end_date

    @property
    def prorated_annual_leave(self) -> float:
        """مرخصی استحقاقی به نسبت مدت قرارداد"""
        duration = self.contract_duration_days
        if duration is None or duration >= 365:
            return float(self.annual_leave_days)
        ratio = duration / 365.0
        return self.annual_leave_days * ratio

    @property
    def prorated_sick_leave(self) -> float:
        """مرخصی استعلاجی به نسبت مدت قرارداد"""
        duration = self.contract_duration_days
        if duration is None or duration >= 365:
            return float(self.sick_leave_days)
        ratio = duration / 365.0
        return self.sick_leave_days * ratio

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