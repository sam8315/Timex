"""
سرویس مدیریت آدرس‌های کارمندان
"""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, List

from sqlalchemy.orm import Session

from models.employee_address import (
    EmployeeAddress, ADDRESS_TYPES, RESIDENCE_STATUSES,
)
from models.user import User


# ---------------------------------------------------------------------------
# Sentinel: distinguishes "field not provided" from "explicitly set to None"
# ---------------------------------------------------------------------------
_UNSET = object()

logger = logging.getLogger(__name__)


class AddressServiceError(Exception):
    """خطای سرویس آدرس"""
    pass


def _validate_user_exists(db: Session, user_id: str) -> None:
    """بررسی وجود کاربر"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise AddressServiceError("کاربر یافت نشد")


def _validate_address_type(address_type: str) -> str:
    """اعتبارسنجی و نرمال‌سازی نوع آدرس"""
    normalized = address_type.strip().upper()
    if normalized not in ADDRESS_TYPES:
        raise AddressServiceError(
            f"نوع آدرس نامعتبر است. مقادیر مجاز: {', '.join(ADDRESS_TYPES.keys())}"
        )
    return normalized


def _validate_residence_status(residence_status: str) -> str:
    """اعتبارسنجی وضعیت اقامت"""
    normalized = residence_status.strip().lower()
    if normalized not in RESIDENCE_STATUSES:
        raise AddressServiceError(
            f"وضعیت اقامت نامعتبر است. مقادیر مجاز: {', '.join(RESIDENCE_STATUSES.keys())}"
        )
    return normalized


def _validate_postal_code(postal_code: str) -> str:
    """اعتبارسنجی کد پستی"""
    normalized = postal_code.strip()
    if not normalized.isdigit() or len(normalized) != 10:
        raise AddressServiceError("کد پستی باید دقیقاً ۱۰ رقم عددی باشد")
    return normalized


def _validate_latitude(value: Optional[Decimal]) -> Optional[Decimal]:
    """اعتبارسنجی عرض جغرافیایی"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except (InvalidOperation, ValueError):
            raise AddressServiceError("مقدار عرض جغرافیایی نامعتبر است")
    if value < -90 or value > 90:
        raise AddressServiceError("عرض جغرافیایی باید بین -90 تا 90 باشد")
    return value


def _validate_longitude(value: Optional[Decimal]) -> Optional[Decimal]:
    """اعتبارسنجی طول جغرافیایی"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except (InvalidOperation, ValueError):
            raise AddressServiceError("مقدار طول جغرافیایی نامعتبر است")
    if value < -180 or value > 180:
        raise AddressServiceError("طول جغرافیایی باید بین -180 تا 180 باشد")
    return value


def _validate_date_range(
    valid_from: Optional[date], valid_to: Optional[date]
) -> None:
    """اعتبارسنجی بازه تاریخ"""
    if valid_from is not None and valid_to is not None:
        if valid_to < valid_from:
            raise AddressServiceError(
                "تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد"
            )


def _get_address_for_user(
    db: Session, user_id: str, address_id: int
) -> EmployeeAddress:
    """دریافت آدرس متعلق به کاربر مشخص"""
    addr = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == address_id,
        EmployeeAddress.user_id == user_id,
    ).first()
    if not addr:
        raise AddressServiceError("آدرس یافت نشد")
    return addr


def list_addresses(db: Session, user_id: str) -> List[EmployeeAddress]:
    """لیست آدرس‌های یک کاربر"""
    _validate_user_exists(db, user_id)
    return (
        db.query(EmployeeAddress)
        .filter(EmployeeAddress.user_id == user_id)
        .order_by(
            EmployeeAddress.is_primary.desc(),
            EmployeeAddress.created_at.asc(),
        )
        .all()
    )


def get_address(db: Session, user_id: str, address_id: int) -> EmployeeAddress:
    """دریافت یک آدرس بر اساس ID (scoped به کاربر)"""
    _validate_user_exists(db, user_id)
    return _get_address_for_user(db, user_id, address_id)


def create_address(
    db: Session,
    user_id: str,
    address_type: str,
    residence_status: str,
    province: str,
    city: str,
    postal_code: str,
    address_text: str,
    is_primary: bool = False,
    district: Optional[str] = None,
    latitude: Optional[Decimal] = None,
    longitude: Optional[Decimal] = None,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    notes: Optional[str] = None,
    gnaf_id: Optional[str] = None,
) -> EmployeeAddress:
    """ایجاد آدرس جدید"""
    _validate_user_exists(db, user_id)
    address_type = _validate_address_type(address_type)
    residence_status = _validate_residence_status(residence_status)
    postal_code = _validate_postal_code(postal_code)
    latitude = _validate_latitude(latitude)
    longitude = _validate_longitude(longitude)
    _validate_date_range(valid_from, valid_to)

    if is_primary:
        db.query(EmployeeAddress).filter(
            EmployeeAddress.user_id == user_id,
            EmployeeAddress.is_primary == True,
        ).update({EmployeeAddress.is_primary: False})

    new_addr = EmployeeAddress(
        user_id=user_id,
        address_type=address_type,
        residence_status=residence_status,
        province=province.strip(),
        city=city.strip(),
        district=district.strip() if district else None,
        postal_code=postal_code,
        address=address_text.strip(),
        is_primary=is_primary,
        latitude=latitude,
        longitude=longitude,
        valid_from=valid_from,
        valid_to=valid_to,
        notes=notes.strip() if notes else None,
        gnaf_id=gnaf_id.strip() if gnaf_id else None,
    )
    db.add(new_addr)
    db.commit()
    db.refresh(new_addr)
    return new_addr


def update_address(
    db: Session,
    user_id: str,
    address_id: int,
    address_type: Optional[str] = _UNSET,
    residence_status: Optional[str] = _UNSET,
    province: Optional[str] = _UNSET,
    city: Optional[str] = _UNSET,
    district: Optional[str] = _UNSET,
    postal_code: Optional[str] = _UNSET,
    address_text: Optional[str] = _UNSET,
    latitude: Optional[Decimal] = _UNSET,
    longitude: Optional[Decimal] = _UNSET,
    valid_from: Optional[date] = _UNSET,
    valid_to: Optional[date] = _UNSET,
    notes: Optional[str] = _UNSET,
    gnaf_id: Optional[str] = _UNSET,
) -> EmployeeAddress:
    """ویرایش آدرس

    Param defaults use _UNSET sentinel so callers can:
      - omit a param  => keep existing value
      - pass None     => clear the field
      - pass a value  => update the field
    """
    _validate_user_exists(db, user_id)
    addr = _get_address_for_user(db, user_id, address_id)

    if address_type is not _UNSET:
        addr.address_type = _validate_address_type(address_type)
    if residence_status is not _UNSET:
        addr.residence_status = _validate_residence_status(residence_status)
    if postal_code is not _UNSET:
        addr.postal_code = _validate_postal_code(postal_code)
    if latitude is not _UNSET:
        addr.latitude = _validate_latitude(latitude)
    if longitude is not _UNSET:
        addr.longitude = _validate_longitude(longitude)

    if valid_from is not _UNSET:
        addr.valid_from = valid_from
    if valid_to is not _UNSET:
        addr.valid_to = valid_to

    effective_from = valid_from if valid_from is not _UNSET else addr.valid_from
    effective_to = valid_to if valid_to is not _UNSET else addr.valid_to
    _validate_date_range(effective_from, effective_to)

    if province is not _UNSET:
        addr.province = province.strip() if province else None
    if city is not _UNSET:
        addr.city = city.strip() if city else None
    if district is not _UNSET:
        addr.district = district.strip() if district else None
    if address_text is not _UNSET:
        addr.address = address_text.strip() if address_text else None
    if notes is not _UNSET:
        addr.notes = notes.strip() if notes else None
    if gnaf_id is not _UNSET:
        addr.gnaf_id = gnaf_id.strip() if gnaf_id else None

    db.commit()
    db.refresh(addr)
    return addr


def delete_address(db: Session, user_id: str, address_id: int) -> None:
    """حذف آدرس"""
    _validate_user_exists(db, user_id)
    addr = _get_address_for_user(db, user_id, address_id)
    db.delete(addr)
    db.commit()


def set_primary_address(
    db: Session, user_id: str, address_id: int
) -> EmployeeAddress:
    """تنظیم آدرس اصلی"""
    _validate_user_exists(db, user_id)
    addr = _get_address_for_user(db, user_id, address_id)

    db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user_id,
        EmployeeAddress.is_primary == True,
    ).update({EmployeeAddress.is_primary: False})

    addr.is_primary = True
    db.commit()
    db.refresh(addr)
    return addr


def get_primary_address(
    db: Session, user_id: str
) -> Optional[EmployeeAddress]:
    """دریافت آدرس اصلی کاربر"""
    _validate_user_exists(db, user_id)
    return (
        db.query(EmployeeAddress)
        .filter(
            EmployeeAddress.user_id == user_id,
            EmployeeAddress.is_primary == True,
        )
        .first()
    )
