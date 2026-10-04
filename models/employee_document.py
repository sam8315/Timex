"""
مدل مدارک پرونده پرسنلی (Employee Documents)
فایل‌ها فقط از طریق Unified File Storage (category: employee-documents) نگهداری می‌شوند.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin

DOCUMENT_TYPES = {
    "NATIONAL_ID": "کارت ملی",
    "BIRTH_CERTIFICATE": "شناسنامه",
    "MILITARY_SERVICE": "پایان خدمت / معافیت",
    "EDUCATION_DEGREE": "مدرک تحصیلی",
    "EMPLOYMENT_ORDER": "حکم / مدرک استخدامی",
    "INSURANCE": "بیمه",
    "PROFESSIONAL_LICENSE": "مجوز حرفه‌ای",
    "OTHER": "سایر",
}

DOCUMENT_STATUSES = {
    "PENDING": "در انتظار بررسی",
    "VERIFIED": "تأیید شده",
    "REJECTED": "رد شده",
}

_STATUS_VALUES = ", ".join(f"'{s}'" for s in DOCUMENT_STATUSES)
_TYPE_VALUES = ", ".join(f"'{t}'" for t in DOCUMENT_TYPES)


class EmployeeDocument(TimestampMixin, Base):
    """مدارک پرسنلی کارمند — soft-delete با deleted_at."""

    __tablename__ = "employee_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        nullable=False,
        index=True,
    )

    uploaded_by: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    verified_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    user = relationship("User", backref="employee_documents")

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="ck_employee_document_status",
        ),
        CheckConstraint(
            f"document_type IN ({_TYPE_VALUES})",
            name="ck_employee_document_type",
        ),
        CheckConstraint("size_bytes > 0", name="ck_employee_document_size"),
    )

    @property
    def document_type_name(self) -> str:
        return DOCUMENT_TYPES.get(self.document_type, self.document_type)

    @property
    def status_name(self) -> str:
        return DOCUMENT_STATUSES.get(self.status, self.status)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def __repr__(self) -> str:
        return (
            f"<EmployeeDocument(id={self.id}, user_id='{self.user_id}', "
            f"type='{self.document_type}', status='{self.status}')>"
        )
