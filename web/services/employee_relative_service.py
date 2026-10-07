"""
سرویس مدیریت بستگان کارکنان

policy-agnostic: فقط ثبت/اعتبارسنجی واقعیت‌ها.
هیچ منطق حق اولاد / eligibility / مبلغ در این لایه نیست.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.employee_relative import (
    EMPLOYMENT_STATUSES,
    INSURANCE_STATUSES,
    RELATIONSHIP_TYPES,
    RELATIVE_GENDERS,
    RELATIVE_MARITAL_STATUSES,
    RELATIVE_STATUSES,
    EmployeeRelative,
)
from models.user import User

_UNSET = object()

logger = logging.getLogger(__name__)

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class EmployeeRelativeServiceError(Exception):
    """خطای دامنه سرویس بستگان"""
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_user_exists(db: Session, user_id: str) -> None:
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise EmployeeRelativeServiceError("کاربر یافت نشد")


def _validate_required_text(value, field_label: str, max_len: int) -> str:
    if value is None or not str(value).strip():
        raise EmployeeRelativeServiceError(f"{field_label} نمی‌تواند خالی باشد")
    text = str(value).strip()
    if len(text) > max_len:
        raise EmployeeRelativeServiceError(
            f"{field_label} نمی‌تواند بیش از {max_len} کاراکتر باشد"
        )
    return text


def _normalize_optional_text(value, max_len: int = 100) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_len:
        raise EmployeeRelativeServiceError(
            f"متن نمی‌تواند بیش از {max_len} کاراکتر باشد"
        )
    return text


def _validate_relationship_type(value) -> str:
    if value is None or not str(value).strip():
        raise EmployeeRelativeServiceError("نوع نسبت الزامی است")
    normalized = str(value).strip().upper()
    if normalized not in RELATIONSHIP_TYPES:
        raise EmployeeRelativeServiceError(
            "نوع نسبت نامعتبر است. مقادیر مجاز: "
            + ", ".join(RELATIONSHIP_TYPES.keys())
        )
    return normalized


def _validate_optional_code(value, allowed: dict, field_label: str, *, upper: bool = False):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.upper() if upper else text.lower()
    if key not in allowed:
        raise EmployeeRelativeServiceError(
            f"{field_label} نامعتبر است. مقادیر مجاز: "
            + ", ".join(allowed.keys())
        )
    return key


def _validate_gender(value) -> Optional[str]:
    return _validate_optional_code(value, RELATIVE_GENDERS, "جنسیت", upper=True)


def _validate_marital_status(value) -> Optional[str]:
    return _validate_optional_code(
        value, RELATIVE_MARITAL_STATUSES, "وضعیت تأهل", upper=True
    )


def _validate_employment_status(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "unknown":
        return None
    if text not in EMPLOYMENT_STATUSES:
        raise EmployeeRelativeServiceError(
            "وضعیت اشتغال نامعتبر است. مقادیر مجاز: "
            + ", ".join(EMPLOYMENT_STATUSES.keys())
        )
    return text


def _validate_insurance_status(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "unknown":
        return None
    if text not in INSURANCE_STATUSES:
        raise EmployeeRelativeServiceError(
            "وضعیت بیمه نامعتبر است. مقادیر مجاز: "
            + ", ".join(INSURANCE_STATUSES.keys())
        )
    return text


def _validate_status(value) -> str:
    if value is None or not str(value).strip():
        return "PENDING"
    key = str(value).strip().upper()
    if key not in RELATIVE_STATUSES:
        raise EmployeeRelativeServiceError(
            "وضعیت تأیید نامعتبر است. مقادیر مجاز: "
            + ", ".join(RELATIVE_STATUSES.keys())
        )
    return key


def _validate_optional_bool(value, field_label: str) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if not lowered or lowered in ("unknown", "null"):
            return None
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    raise EmployeeRelativeServiceError(f"{field_label} نامعتبر است")


def is_valid_national_code(code: str) -> bool:
    """اعتبارسنجی الگوریتمی کد ملی ایران (رقم کنترل)."""
    if len(code) != 10 or not code.isdigit():
        return False
    if len(set(code)) == 1:
        return False
    checksum = sum(int(code[i]) * (10 - i) for i in range(9)) % 11
    check_digit = int(code[9])
    if checksum < 2:
        return check_digit == checksum
    return check_digit == 11 - checksum


def _validate_national_code(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).translate(_DIGIT_TRANSLATION).strip()
    if not text:
        return None
    if not re.fullmatch(r"[0-9]{10}", text):
        raise EmployeeRelativeServiceError("کد ملی باید دقیقاً ۱۰ رقم عددی باشد")
    if not is_valid_national_code(text):
        raise EmployeeRelativeServiceError("کد ملی نامعتبر است")
    return text


def _validate_date_not_future(value: Optional[date], field_label: str) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, date):
        raise EmployeeRelativeServiceError(f"{field_label} نامعتبر است")
    if value > date.today():
        raise EmployeeRelativeServiceError(
            f"{field_label} نمی‌تواند در آینده باشد"
        )
    return value


def _ensure_date_order(
    earlier: Optional[date],
    later: Optional[date],
    message: str,
) -> None:
    if earlier is not None and later is not None and later < earlier:
        raise EmployeeRelativeServiceError(message)


def _validate_date_consistency(
    *,
    birth_date: Optional[date],
    marriage_date: Optional[date],
    divorce_date: Optional[date],
    death_date: Optional[date],
    study_start_date: Optional[date],
    study_end_date: Optional[date],
    disability_start_date: Optional[date],
    disability_end_date: Optional[date],
) -> None:
    _ensure_date_order(
        birth_date, death_date, "تاریخ فوت نمی‌تواند قبل از تاریخ تولد باشد"
    )
    _ensure_date_order(
        birth_date, marriage_date, "تاریخ ازدواج نمی‌تواند قبل از تاریخ تولد باشد"
    )
    _ensure_date_order(
        marriage_date, divorce_date, "تاریخ طلاق نمی‌تواند قبل از تاریخ ازدواج باشد"
    )
    _ensure_date_order(
        study_start_date, study_end_date,
        "تاریخ پایان تحصیل نمی‌تواند قبل از تاریخ شروع باشد",
    )
    _ensure_date_order(
        disability_start_date, disability_end_date,
        "تاریخ پایان ازکارافتادگی نمی‌تواند قبل از تاریخ شروع باشد",
    )


def _active_query(db: Session, user_id: Optional[str] = None):
    q = db.query(EmployeeRelative).filter(EmployeeRelative.deleted_at.is_(None))
    if user_id is not None:
        q = q.filter(EmployeeRelative.user_id == user_id)
    return q


def _get_for_user(
    db: Session,
    user_id: str,
    relative_id: int,
    *,
    include_deleted: bool = False,
) -> EmployeeRelative:
    q = db.query(EmployeeRelative).filter(
        EmployeeRelative.id == relative_id,
        EmployeeRelative.user_id == user_id,
    )
    if not include_deleted:
        q = q.filter(EmployeeRelative.deleted_at.is_(None))
    relative = q.first()
    if not relative:
        raise EmployeeRelativeServiceError("فرد وابسته یافت نشد")
    return relative


def _reset_verification(relative: EmployeeRelative) -> None:
    relative.status = "PENDING"
    relative.verified_by = None
    relative.verified_at = None
    relative.rejection_reason = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_relatives(
    db: Session,
    user_id: str,
    *,
    include_deleted: bool = False,
) -> List[EmployeeRelative]:
    """لیست بستگان یک کاربر (پیش‌فرض فقط فعال)."""
    _validate_user_exists(db, user_id)
    if include_deleted:
        q = db.query(EmployeeRelative).filter(EmployeeRelative.user_id == user_id)
    else:
        q = _active_query(db, user_id)
    return q.order_by(
        EmployeeRelative.relationship_type.asc(),
        EmployeeRelative.last_name.asc(),
        EmployeeRelative.first_name.asc(),
        EmployeeRelative.id.asc(),
    ).all()


def get_relative(
    db: Session,
    relative_id: int,
    *,
    include_deleted: bool = False,
) -> EmployeeRelative:
    q = db.query(EmployeeRelative).filter(EmployeeRelative.id == relative_id)
    if not include_deleted:
        q = q.filter(EmployeeRelative.deleted_at.is_(None))
    relative = q.first()
    if not relative:
        raise EmployeeRelativeServiceError("فرد وابسته یافت نشد")
    return relative


def create_relative(
    db: Session,
    user_id: str,
    *,
    first_name: str,
    last_name: str,
    relationship_type: str,
    father_name: Optional[str] = None,
    national_code: Optional[str] = None,
    birth_date: Optional[date] = None,
    gender: Optional[str] = None,
    marital_status: Optional[str] = None,
    marriage_date: Optional[date] = None,
    divorce_date: Optional[date] = None,
    death_date: Optional[date] = None,
    is_studying: Optional[bool] = None,
    study_start_date: Optional[date] = None,
    study_end_date: Optional[date] = None,
    employment_status: Optional[str] = None,
    insurance_status: Optional[str] = None,
    is_disabled: Optional[bool] = None,
    disability_start_date: Optional[date] = None,
    disability_end_date: Optional[date] = None,
    notes: Optional[str] = None,
    created_by: Optional[str] = None,
    submitted_by: Optional[str] = None,
    status: str = "PENDING",
) -> EmployeeRelative:
    """ایجاد فرد وابسته جدید برای کارمند."""
    _validate_user_exists(db, user_id)

    first_name = _validate_required_text(first_name, "نام", 100)
    last_name = _validate_required_text(last_name, "نام خانوادگی", 100)
    relationship_type = _validate_relationship_type(relationship_type)
    father_name = _normalize_optional_text(father_name, 100)
    national_code = _validate_national_code(national_code)
    gender = _validate_gender(gender)
    marital_status = _validate_marital_status(marital_status)
    employment_status = _validate_employment_status(employment_status)
    insurance_status = _validate_insurance_status(insurance_status)
    is_studying = _validate_optional_bool(is_studying, "وضعیت تحصیل")
    is_disabled = _validate_optional_bool(is_disabled, "وضعیت ازکارافتادگی")
    notes = _normalize_optional_text(notes, 5000)
    status = _validate_status(status)

    birth_date = _validate_date_not_future(birth_date, "تاریخ تولد")
    marriage_date = _validate_date_not_future(marriage_date, "تاریخ ازدواج")
    divorce_date = _validate_date_not_future(divorce_date, "تاریخ طلاق")
    death_date = _validate_date_not_future(death_date, "تاریخ فوت")
    study_start_date = _validate_date_not_future(study_start_date, "تاریخ شروع تحصیل")
    study_end_date = _validate_date_not_future(study_end_date, "تاریخ پایان تحصیل")
    disability_start_date = _validate_date_not_future(
        disability_start_date, "تاریخ شروع ازکارافتادگی"
    )
    disability_end_date = _validate_date_not_future(
        disability_end_date, "تاریخ پایان ازکارافتادگی"
    )

    _validate_date_consistency(
        birth_date=birth_date,
        marriage_date=marriage_date,
        divorce_date=divorce_date,
        death_date=death_date,
        study_start_date=study_start_date,
        study_end_date=study_end_date,
        disability_start_date=disability_start_date,
        disability_end_date=disability_end_date,
    )

    relative = EmployeeRelative(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        father_name=father_name,
        national_code=national_code,
        birth_date=birth_date,
        gender=gender,
        relationship_type=relationship_type,
        marital_status=marital_status,
        marriage_date=marriage_date,
        divorce_date=divorce_date,
        death_date=death_date,
        is_studying=is_studying,
        study_start_date=study_start_date,
        study_end_date=study_end_date,
        employment_status=employment_status,
        insurance_status=insurance_status,
        is_disabled=is_disabled,
        disability_start_date=disability_start_date,
        disability_end_date=disability_end_date,
        notes=notes,
        status=status,
        submitted_by=submitted_by or created_by,
        verified_by=created_by if status == "VERIFIED" else None,
        verified_at=_now() if status == "VERIFIED" else None,
    )
    db.add(relative)
    try:
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmployeeRelativeServiceError(
            "این کد ملی برای این کارمند قبلاً ثبت شده است"
        )
    db.refresh(relative)
    if created_by:
        logger.info(
            "employee_relative created user_id=%s relative_id=%s by=%s status=%s",
            user_id, relative.id, created_by, status,
        )
    return relative


def update_relative(
    db: Session,
    user_id: str,
    relative_id: int,
    *,
    first_name=_UNSET,
    last_name=_UNSET,
    father_name=_UNSET,
    national_code=_UNSET,
    birth_date=_UNSET,
    gender=_UNSET,
    relationship_type=_UNSET,
    marital_status=_UNSET,
    marriage_date=_UNSET,
    divorce_date=_UNSET,
    death_date=_UNSET,
    is_studying=_UNSET,
    study_start_date=_UNSET,
    study_end_date=_UNSET,
    employment_status=_UNSET,
    insurance_status=_UNSET,
    is_disabled=_UNSET,
    disability_start_date=_UNSET,
    disability_end_date=_UNSET,
    notes=_UNSET,
    reset_verification: bool = False,
) -> EmployeeRelative:
    """ویرایش فرد وابسته.

    اگر reset_verification=True (مسیر کاربر)، وضعیت VERIFIED/REJECTED
    به PENDING برمی‌گردد.
    """
    _validate_user_exists(db, user_id)
    relative = _get_for_user(db, user_id, relative_id)

    if first_name is not _UNSET:
        relative.first_name = _validate_required_text(first_name, "نام", 100)
    if last_name is not _UNSET:
        relative.last_name = _validate_required_text(last_name, "نام خانوادگی", 100)
    if father_name is not _UNSET:
        relative.father_name = _normalize_optional_text(father_name, 100)
    if national_code is not _UNSET:
        relative.national_code = _validate_national_code(national_code)
    if gender is not _UNSET:
        relative.gender = _validate_gender(gender)
    if relationship_type is not _UNSET:
        relative.relationship_type = _validate_relationship_type(relationship_type)
    if marital_status is not _UNSET:
        relative.marital_status = _validate_marital_status(marital_status)
    if employment_status is not _UNSET:
        relative.employment_status = _validate_employment_status(employment_status)
    if insurance_status is not _UNSET:
        relative.insurance_status = _validate_insurance_status(insurance_status)
    if is_studying is not _UNSET:
        relative.is_studying = _validate_optional_bool(is_studying, "وضعیت تحصیل")
    if is_disabled is not _UNSET:
        relative.is_disabled = _validate_optional_bool(
            is_disabled, "وضعیت ازکارافتادگی"
        )
    if notes is not _UNSET:
        relative.notes = _normalize_optional_text(notes, 5000)

    if birth_date is not _UNSET:
        relative.birth_date = _validate_date_not_future(birth_date, "تاریخ تولد")
    if marriage_date is not _UNSET:
        relative.marriage_date = _validate_date_not_future(
            marriage_date, "تاریخ ازدواج"
        )
    if divorce_date is not _UNSET:
        relative.divorce_date = _validate_date_not_future(divorce_date, "تاریخ طلاق")
    if death_date is not _UNSET:
        relative.death_date = _validate_date_not_future(death_date, "تاریخ فوت")
    if study_start_date is not _UNSET:
        relative.study_start_date = _validate_date_not_future(
            study_start_date, "تاریخ شروع تحصیل"
        )
    if study_end_date is not _UNSET:
        relative.study_end_date = _validate_date_not_future(
            study_end_date, "تاریخ پایان تحصیل"
        )
    if disability_start_date is not _UNSET:
        relative.disability_start_date = _validate_date_not_future(
            disability_start_date, "تاریخ شروع ازکارافتادگی"
        )
    if disability_end_date is not _UNSET:
        relative.disability_end_date = _validate_date_not_future(
            disability_end_date, "تاریخ پایان ازکارافتادگی"
        )

    _validate_date_consistency(
        birth_date=relative.birth_date,
        marriage_date=relative.marriage_date,
        divorce_date=relative.divorce_date,
        death_date=relative.death_date,
        study_start_date=relative.study_start_date,
        study_end_date=relative.study_end_date,
        disability_start_date=relative.disability_start_date,
        disability_end_date=relative.disability_end_date,
    )

    if reset_verification and relative.status in ("VERIFIED", "REJECTED"):
        _reset_verification(relative)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise EmployeeRelativeServiceError(
            "این کد ملی برای این کارمند قبلاً ثبت شده است"
        )
    db.refresh(relative)
    return relative


def soft_delete_relative(
    db: Session,
    user_id: str,
    relative_id: int,
    *,
    deleted_by: str,
    allow_verified: bool = False,
) -> EmployeeRelative:
    """حذف نرم فرد وابسته — داده برای تاریخچه Payroll حفظ می‌شود."""
    _validate_user_exists(db, user_id)
    relative = _get_for_user(db, user_id, relative_id)
    if relative.status == "VERIFIED" and not allow_verified:
        raise EmployeeRelativeServiceError(
            "فرد وابسته تأییدشده قابل حذف توسط کارمند نیست"
        )
    relative.deleted_at = _now()
    relative.deleted_by = deleted_by
    db.commit()
    db.refresh(relative)
    return relative


def verify_relative(
    db: Session,
    user_id: str,
    relative_id: int,
    *,
    verified_by: str,
) -> EmployeeRelative:
    _validate_user_exists(db, user_id)
    relative = _get_for_user(db, user_id, relative_id)
    relative.status = "VERIFIED"
    relative.verified_by = verified_by
    relative.verified_at = _now()
    relative.rejection_reason = None
    db.commit()
    db.refresh(relative)
    return relative


def reject_relative(
    db: Session,
    user_id: str,
    relative_id: int,
    *,
    rejected_by: str,
    reason: str,
) -> EmployeeRelative:
    _validate_user_exists(db, user_id)
    relative = _get_for_user(db, user_id, relative_id)
    reason_text = _validate_required_text(reason, "دلیل رد", 2000)
    relative.status = "REJECTED"
    relative.verified_by = rejected_by
    relative.verified_at = _now()
    relative.rejection_reason = reason_text
    db.commit()
    db.refresh(relative)
    return relative
