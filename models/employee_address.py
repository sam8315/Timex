"""
مدل جدول آدرس‌های کارمندان
- پشتیبانی از چند آدرس برای هر کاربر (1:N)
- امکان مشخص کردن یک آدرس اصلی (primary) به ازای هر کاربر
- پشتیبانی از تاریخچه آدرس با valid_from / valid_to

معناشناسی پرچم‌ها:
- is_primary یعنی «آدرس اصلیِ فعلیِ کارمند»؛ یک پرچم تاریخی نیست و در هر
  لحظه حداکثر یک آدرس برای هر کاربر می‌تواند is_primary=True داشته باشد
  (ایندکس یکتای جزئی).
- valid_from / valid_to بازه اعتبار/تاریخچه هر آدرس را مستقل از is_primary
  توصیف می‌کنند؛ سطرهای تاریخی ملزم به primary ماندن نیستند.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Integer, String, Boolean, ForeignKey, Text, Date, Numeric,
    CheckConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from models.base import Base, TimestampMixin


# نوع آدرس
ADDRESS_TYPES = {
    'HOME': 'خانه',
    'WORK': 'کار',
    'MAILING': 'پستی',
    'OTHER': 'سایر',
}

# وضعیت اقامت (situation résidentielle)
RESIDENCE_STATUSES = {
    'owner': 'مالک',
    'tenant': 'اجاره‌دار',
    'family': 'خانه زیر تکفل خانواده',
    'org_housing': 'مسکن سازمانی',
    'provided': 'ارائه‌شده/رایگان',
    'other': 'سایر',
    'unknown': 'نامشخص',
}


class EmployeeAddress(TimestampMixin, Base):
    """جدول آدرس‌های کارمندان"""
    __tablename__ = "employee_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ارتباط با جدول users
    # همانند employee_phones؛ همه سیستم با user_id کار می‌کند
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # نوع آدرس
    address_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="نوع آدرس: HOME, WORK, MAILING, OTHER"
    )

    # وضعیت اقامت
    residence_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="وضعیت اقامت: owner, tenant, family, org_housing, provided, other, unknown"
    )

    # اطلاعات آدرس
    province: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    district: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)

    # آدرس اصلیِ فعلی کارمند (نه پرچم تاریخی)؛ حداکثر یکی به ازای هر کاربر
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True
    )

    # فیلدهای اختیاری
    gnaf_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    # بازه اعتبار/تاریخچه؛ مستقل از is_primary (سطر تاریخی لازم نیست primary بماند)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # مرجع ساخت‌یافته شهر (master data) — اختیاری؛ متن‌ها snapshot می‌مانند
    # همانند employee_service_locations؛ حذف شهرِ ارجاع‌شده ممنوع است
    city_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("cities.id", ondelete="RESTRICT"),
        nullable=True,
        index=True
    )

    # Relationships
    user = relationship("User", backref="addresses")
    city_ref = relationship("City")

    # Constraints
    __table_args__ = (
        # postal_code باید دقیقاً ۱۰ رقم عددی باشد (فرمت کد پستی ایران)
        CheckConstraint(
            "postal_code ~ '^[0-9]{10}$'",
            name="ck_employee_address_postal_code_format"
        ),
        # عرض جغرافیایی باید بین -90 تا 90 باشد
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_employee_address_latitude_range"
        ),
        # طول جغرافیایی باید بین -180 تا 180 باشد
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_employee_address_longitude_range"
        ),
        # valid_to نباید قبل از valid_from باشد (وقتی هر دو مقدار داشته باشند)
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_employee_address_validity_range"
        ),
        # مقادیر مجاز address_type
        CheckConstraint(
            "address_type IN ('HOME', 'WORK', 'MAILING', 'OTHER')",
            name="ck_employee_address_type"
        ),
        # مقادیر مجاز residence_status
        CheckConstraint(
            "residence_status IN ('owner', 'tenant', 'family', 'org_housing', 'provided', 'other', 'unknown')",
            name="ck_employee_address_residence_status"
        ),
        # یک آدرس اصلی (primary) به ازای هر کاربر — ایندکس جزئی (partial index)
        Index(
            'uq_employee_address_primary_per_user',
            'user_id',
            unique=True,
            postgresql_where='is_primary = true'
        ),
    )

    @validates("address_type")
    def _normalize_address_type(self, key, value):
        """تبدیل به بزرگ برای سازگاری با CHECK constraint"""
        if isinstance(value, str):
            return value.upper()
        return value

    def __repr__(self) -> str:
        primary_tag = "⭐" if self.is_primary else ""
        return f"<EmployeeAddress(user_id='{self.user_id}', type='{self.address_type}', city='{self.city}' {primary_tag})>"

    @property
    def address_type_name(self) -> str:
        """نام فارسی نوع آدرس"""
        return ADDRESS_TYPES.get(self.address_type, self.address_type)

    @property
    def residence_status_name(self) -> str:
        """نام فارسی وضعیت اقامت"""
        return RESIDENCE_STATUSES.get(self.residence_status, self.residence_status)

    def to_dict(self) -> dict:
        """تبدیل مدل به دیکشنری"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'address_type': self.address_type,
            'address_type_name': self.address_type_name,
            'residence_status': self.residence_status,
            'residence_status_name': self.residence_status_name,
            'province': self.province,
            'city': self.city,
            'city_id': self.city_id,
            'district': self.district,
            'postal_code': self.postal_code,
            'address': self.address,
            'is_primary': self.is_primary,
            'gnaf_id': self.gnaf_id,
            'latitude': float(self.latitude) if self.latitude is not None else None,
            'longitude': float(self.longitude) if self.longitude is not None else None,
            'valid_from': self.valid_from.isoformat() if self.valid_from else None,
            'valid_to': self.valid_to.isoformat() if self.valid_to else None,
            'notes': self.notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
