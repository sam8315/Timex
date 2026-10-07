"""
تاریخچه ممیزی بستگان (append-only)

الگو مشابه EmployeeAddressHistory: به‌ازای هر تغییر یک ردیف با اسنپ‌شات.
relative_id / user_id بدون FK تا با حذف رکورد، سابقه از بین نرود.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base

HISTORY_ACTIONS = {
    "CREATE": "ایجاد",
    "UPDATE": "ویرایش",
    "DELETE": "حذف",
    "VERIFY": "تأیید",
    "REJECT": "رد",
    "STUDY_EXPIRE": "انقضای تحصیل",
    "FILE_ADD": "افزودن فایل",
    "FILE_DELETE": "حذف فایل",
}

_ACTION_VALUES = ", ".join(f"'{k}'" for k in HISTORY_ACTIONS)


class EmployeeRelativeHistory(Base):
    __tablename__ = "employee_relative_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    relative_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot fields (all nullable so history never blocks mutations)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    father_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    national_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    relationship_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
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
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"action IN ({_ACTION_VALUES})",
            name="ck_employee_relative_history_action",
        ),
    )

    @property
    def action_name(self) -> str:
        return HISTORY_ACTIONS.get(self.action, self.action)

    @property
    def full_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else "—"

    def __repr__(self) -> str:
        return (
            f"<EmployeeRelativeHistory(relative_id={self.relative_id}, "
            f"action='{self.action}')>"
        )
