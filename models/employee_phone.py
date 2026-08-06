"""
مدل جدول شماره موبایل کارمندان
- پشتیبانی از چند شماره برای هر کاربر
- امکان مشخص کردن شماره پیش‌فرض
"""
from typing import Optional
from sqlalchemy import Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class EmployeePhone(TimestampMixin, Base):
    """جدول شماره موبایل کارمندان"""
    __tablename__ = "employee_phones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ارتباط با جدول users (راحت‌تر از employee_id چون همه سیستم با user_id کار می‌کند)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # اطلاعات تماس
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    label: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="برچسب: همراه، منزل، اضطراری"
    )

    # آیا این شماره پیش‌فرض است؟
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True
    )

    # Relationships
    user = relationship("User", backref="phones")

    def __repr__(self) -> str:
        default_tag = "⭐" if self.is_default else ""
        return f"<Phone(user_id='{self.user_id}', {self.phone_number} {default_tag})>"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'phone_number': self.phone_number,
            'label': self.label,
            'is_default': self.is_default,
            'created_at': self.created_at,
        }