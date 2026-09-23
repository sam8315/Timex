"""
مدل جدول حساب‌های بانکی کارمندان
- پشتیبانی از چند حساب برای هر کاربر (1:N)
- حداکثر یک حساب «اصلیِ فعال» (is_primary AND is_active) به ازای هر کاربر
  با ایندکس یکتای جزئی تضمین می‌شود
- bank_name اسنپ‌شات متنی ردیف مرجع banks است (همانند employee_addresses.city)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


VERIFICATION_STATUSES = {
    'unverified': 'در انتظار بررسی',
    'verified': 'تأیید شده',
    'rejected': 'رد شده',
}


class EmployeeBankAccount(TimestampMixin, Base):
    """جدول حساب‌های بانکی کارمندان"""
    __tablename__ = "employee_bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    bank_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("banks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)

    branch_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    branch_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    card_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    sheba: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    account_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    account_title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True
    )

    verification_status: Mapped[str] = mapped_column(
        String(20),
        default='unverified',
        nullable=False,
        index=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    verification_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user = relationship("User", backref="bank_accounts")
    bank = relationship("Bank")

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('unverified', 'verified', 'rejected')",
            name="ck_employee_bank_account_verification_status"
        ),
        Index(
            'uq_employee_bank_account_primary_active',
            'user_id',
            unique=True,
            postgresql_where='is_primary = true AND is_active = true'
        ),
    )

    def __repr__(self) -> str:
        primary_tag = " [primary]" if self.is_primary else ""
        return (
            f"<EmployeeBankAccount(user_id='{self.user_id}', "
            f"bank='{self.bank_name}', account='{self.account_number}'{primary_tag}>"
        )

    @property
    def verification_status_name(self) -> str:
        """نام فارسی وضعیت تأیید"""
        return VERIFICATION_STATUSES.get(
            self.verification_status, self.verification_status
        )
