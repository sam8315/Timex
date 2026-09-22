"""
تاریخچه ممیزی آدرس‌های کارمندان (append-only)

الگو مشابه UserPermissionHistory است: به‌ازای هر CREATE/UPDATE/DELETE یک ردیف
با اسنپ‌شات کامل وضعیت آدرس ثبت می‌شود. جدول history عمومی و قابل‌استفاده
مجدد در پروژه وجود نداشت، پس جدول اختصاصی ساخته شد.

نکته‌ها:
- address_id عمداً کلید خارجی نیست تا حذف آدرس، سوابق آن (از جمله ردیف
  DELETE) را پاک نکند.
- city_id هم اسنپ‌شات است (بدون FK) تا با حذف/تغییر شهر مرجع از بین نرود.
- همه ستون‌های اسنپ‌شات nullable هستند تا ثبت تاریخچه هیچ‌وقت مسدود نشود.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Integer, String, Boolean, ForeignKey, Text, Date, DateTime, Numeric,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


HISTORY_ACTIONS = {
    'CREATE': 'ایجاد',
    'UPDATE': 'ویرایش',
    'DELETE': 'حذف',
}


class EmployeeAddressHistory(Base):
    """لاگ الحاقی تغییرات آدرس (هر تغییر یک ردیف با اسنپ‌شات کامل)"""

    __tablename__ = "employee_address_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # پیوند به آدرس/کاربر هدف (بدون FK روی address تا سوابق حذف باقی بماند)
    address_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    action: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    changed_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # اسنپ‌شات وضعیت آدرس در لحظه تغییر
    address_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    residence_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_primary: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    city_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    gnaf_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "action IN ('CREATE', 'UPDATE', 'DELETE')",
            name="ck_employee_address_history_action"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<EmployeeAddressHistory(address_id={self.address_id}, "
            f"action='{self.action}')>"
        )
