"""
مدل بستگان کارکنان (Employee Relatives)

policy-agnostic: فقط واقعیت‌های هویتی/وضعیتی ذخیره می‌شود؛
هیچ فیلد eligibility یا مبلغ حق اولاد وجود ندارد.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


RELATIONSHIP_TYPES = {
    "SPOUSE": "همسر",
    "CHILD": "فرزند",
    "FATHER": "پدر",
    "MOTHER": "مادر",
    "SIBLING": "خواهر/برادر",
    "OTHER": "سایر",
}

RELATIVE_GENDERS = {
    "M": "مرد",
    "F": "زن",
}

RELATIVE_MARITAL_STATUSES = {
    "S": "مجرد",
    "M": "متاهل",
    "D": "مطلقه",
    "W": "همسر فوت‌شده",
}

EMPLOYMENT_STATUSES = {
    "employed": "شاغل",
    "unemployed": "بیکار",
}

INSURANCE_STATUSES = {
    "insured": "بیمه‌شده",
    "uninsured": "فاقد بیمه",
}

RELATIVE_STATUSES = {
    "PENDING": "در انتظار تأیید",
    "VERIFIED": "تأیید شده",
    "REJECTED": "رد شده",
}

_RELATIONSHIP_VALUES = ", ".join(f"'{k}'" for k in RELATIONSHIP_TYPES)
_GENDER_VALUES = ", ".join(f"'{k}'" for k in RELATIVE_GENDERS)
_MARITAL_VALUES = ", ".join(f"'{k}'" for k in RELATIVE_MARITAL_STATUSES)
_EMPLOYMENT_VALUES = ", ".join(f"'{k}'" for k in EMPLOYMENT_STATUSES)
_INSURANCE_VALUES = ", ".join(f"'{k}'" for k in INSURANCE_STATUSES)
_STATUS_VALUES = ", ".join(f"'{k}'" for k in RELATIVE_STATUSES)


class EmployeeRelative(TimestampMixin, Base):
    """بستگان یک کارمند — soft-delete با deleted_at؛ تأیید ادمین با status."""

    __tablename__ = "employee_relatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    father_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    national_code: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True, index=True
    )
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)

    relationship_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    marital_status: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    marriage_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    divorce_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    death_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    is_studying: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    study_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    study_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    employment_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    insurance_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    is_disabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    disability_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    disability_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False, index=True
    )
    submitted_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    user = relationship("User", backref="employee_relatives")
    files = relationship(
        "EmployeeRelativeFile",
        back_populates="relative",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            f"relationship_type IN ({_RELATIONSHIP_VALUES})",
            name="ck_employee_relative_relationship_type",
        ),
        CheckConstraint(
            f"gender IS NULL OR gender IN ({_GENDER_VALUES})",
            name="ck_employee_relative_gender",
        ),
        CheckConstraint(
            f"marital_status IS NULL OR marital_status IN ({_MARITAL_VALUES})",
            name="ck_employee_relative_marital_status",
        ),
        CheckConstraint(
            f"employment_status IS NULL OR employment_status IN ({_EMPLOYMENT_VALUES})",
            name="ck_employee_relative_employment_status",
        ),
        CheckConstraint(
            f"insurance_status IS NULL OR insurance_status IN ({_INSURANCE_VALUES})",
            name="ck_employee_relative_insurance_status",
        ),
        CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="ck_employee_relative_status",
        ),
        CheckConstraint(
            "national_code IS NULL OR national_code ~ '^[0-9]{10}$'",
            name="ck_employee_relative_national_code",
        ),
        CheckConstraint(
            "divorce_date IS NULL OR marriage_date IS NULL "
            "OR divorce_date >= marriage_date",
            name="ck_employee_relative_divorce_after_marriage",
        ),
        CheckConstraint(
            "study_end_date IS NULL OR study_start_date IS NULL "
            "OR study_end_date >= study_start_date",
            name="ck_employee_relative_study_range",
        ),
        CheckConstraint(
            "disability_end_date IS NULL OR disability_start_date IS NULL "
            "OR disability_end_date >= disability_start_date",
            name="ck_employee_relative_disability_range",
        ),
        CheckConstraint(
            "death_date IS NULL OR birth_date IS NULL OR death_date >= birth_date",
            name="ck_employee_relative_death_after_birth",
        ),
        CheckConstraint(
            "marriage_date IS NULL OR birth_date IS NULL "
            "OR marriage_date >= birth_date",
            name="ck_employee_relative_marriage_after_birth",
        ),
        Index(
            "ix_employee_relatives_user_relationship",
            "user_id",
            "relationship_type",
        ),
        Index(
            "uq_employee_relative_user_national_code_active",
            "user_id",
            "national_code",
            unique=True,
            postgresql_where="national_code IS NOT NULL AND deleted_at IS NULL",
        ),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def relationship_type_name(self) -> str:
        return RELATIONSHIP_TYPES.get(self.relationship_type, self.relationship_type)

    @property
    def gender_name(self) -> str:
        if self.gender is None:
            return "نامشخص"
        return RELATIVE_GENDERS.get(self.gender, self.gender)

    @property
    def marital_status_name(self) -> str:
        if self.marital_status is None:
            return "نامشخص"
        return RELATIVE_MARITAL_STATUSES.get(self.marital_status, self.marital_status)

    @property
    def employment_status_name(self) -> str:
        if self.employment_status is None:
            return "نامشخص"
        return EMPLOYMENT_STATUSES.get(self.employment_status, self.employment_status)

    @property
    def insurance_status_name(self) -> str:
        if self.insurance_status is None:
            return "نامشخص"
        return INSURANCE_STATUSES.get(self.insurance_status, self.insurance_status)

    @property
    def status_name(self) -> str:
        return RELATIVE_STATUSES.get(self.status, self.status)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return (
            f"<EmployeeRelative(id={self.id}, user_id='{self.user_id}', "
            f"type='{self.relationship_type}', status='{self.status}', "
            f"name='{self.full_name}')>"
        )
