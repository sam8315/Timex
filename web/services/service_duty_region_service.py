"""CRUD و resolve مدت خدمت از مناطق وظیفه (بدون هاردکد نام/ماه)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import List, Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from models.service_duty_region import ServiceDutyRegion
from web.services.membership_service import MembershipError

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")


class ServiceDutyRegionError(MembershipError):
    pass


def list_duty_regions(
    db: Session,
    *,
    active_only: bool = False,
) -> List[ServiceDutyRegion]:
    q = db.query(ServiceDutyRegion)
    if active_only:
        q = q.filter(ServiceDutyRegion.is_active.is_(True))
    return q.order_by(
        ServiceDutyRegion.sort_order.asc(),
        ServiceDutyRegion.name.asc(),
    ).all()


def get_duty_region(db: Session, code: str) -> Optional[ServiceDutyRegion]:
    code = (code or "").strip()
    if not code:
        return None
    return (
        db.query(ServiceDutyRegion)
        .filter(ServiceDutyRegion.code == code)
        .first()
    )


def resolve_service_duration_months(
    db: Session,
    region_code: str,
    is_native: Optional[bool] = None,
) -> int:
    """مدت قانونی خدمت به ماه از پالیسی منطقه."""
    region = get_duty_region(db, region_code)
    if not region:
        raise ServiceDutyRegionError("منطقه خدمت یافت نشد")
    if not region.is_active:
        raise ServiceDutyRegionError("منطقه خدمت غیرفعال است")

    if region.native_affects:
        if is_native is None:
            raise ServiceDutyRegionError(
                "برای این منطقه تعیین بومی/غیربومی الزامی است"
            )
        months = (
            region.duration_months_native
            if is_native
            else region.duration_months_non_native
        )
    else:
        months = region.duration_months

    if months is None or int(months) <= 0:
        raise ServiceDutyRegionError("مدت خدمت برای این منطقه تعریف نشده است")
    return int(months)


def _normalize_code(code: Optional[str], name: str) -> str:
    raw = (code or "").strip().upper()
    if raw:
        if not CODE_RE.match(raw):
            raise ServiceDutyRegionError(
                "کد منطقه نامعتبر است (حروف بزرگ انگلیسی، عدد و _ — ۲ تا ۴۰ کاراکتر)"
            )
        return raw

    # تولید از نام: فقط ASCII؛ در غیر این صورت SDR + hash کوتاه
    slug = unicodedata.normalize("NFKD", name or "")
    slug = "".join(ch for ch in slug if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_").upper()
    if CODE_RE.match(slug):
        return slug[:40]
    digest = int(hashlib.md5(name.strip().encode("utf-8")).hexdigest()[:7], 16) % 10_000_000
    return f"SDR{digest:07d}"


def _validate_durations(
    *,
    native_affects: bool,
    duration_months: Optional[int],
    duration_months_native: Optional[int],
    duration_months_non_native: Optional[int],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    if native_affects:
        n = int(duration_months_native or 0)
        nn = int(duration_months_non_native or 0)
        if n <= 0 or nn <= 0:
            raise ServiceDutyRegionError(
                "وقتی بومی/غیربومی اثر دارد، هر دو مدت ماه باید مثبت باشند"
            )
        return None, n, nn

    m = int(duration_months or 0)
    if m <= 0:
        raise ServiceDutyRegionError("مدت ماه باید مثبت باشد")
    return m, None, None


def create_duty_region(
    db: Session,
    *,
    name: str,
    native_affects: bool,
    duration_months: Optional[int] = None,
    duration_months_native: Optional[int] = None,
    duration_months_non_native: Optional[int] = None,
    code: Optional[str] = None,
    sort_order: int = 0,
    is_active: bool = True,
) -> ServiceDutyRegion:
    name = (name or "").strip()
    if not name:
        raise ServiceDutyRegionError("نام منطقه الزامی است")
    if len(name) > 200:
        raise ServiceDutyRegionError("نام منطقه نباید بیشتر از ۲۰۰ کاراکتر باشد")

    region_code = _normalize_code(code, name)
    if get_duty_region(db, region_code):
        raise ServiceDutyRegionError("کد منطقه تکراری است")

    dm, dmn, dmnn = _validate_durations(
        native_affects=bool(native_affects),
        duration_months=duration_months,
        duration_months_native=duration_months_native,
        duration_months_non_native=duration_months_non_native,
    )

    row = ServiceDutyRegion(
        code=region_code,
        name=name,
        native_affects=bool(native_affects),
        duration_months=dm,
        duration_months_native=dmn,
        duration_months_non_native=dmnn,
        sort_order=int(sort_order or 0),
        is_active=bool(is_active),
    )
    db.add(row)
    db.flush()
    return row


def update_duty_region(
    db: Session,
    code: str,
    *,
    name: str,
    native_affects: bool,
    duration_months: Optional[int] = None,
    duration_months_native: Optional[int] = None,
    duration_months_non_native: Optional[int] = None,
    sort_order: int = 0,
    is_active: bool = True,
) -> ServiceDutyRegion:
    row = get_duty_region(db, code)
    if not row:
        raise ServiceDutyRegionError("منطقه یافت نشد")

    name = (name or "").strip()
    if not name:
        raise ServiceDutyRegionError("نام منطقه الزامی است")
    if len(name) > 200:
        raise ServiceDutyRegionError("نام منطقه نباید بیشتر از ۲۰۰ کاراکتر باشد")

    dm, dmn, dmnn = _validate_durations(
        native_affects=bool(native_affects),
        duration_months=duration_months,
        duration_months_native=duration_months_native,
        duration_months_non_native=duration_months_non_native,
    )

    row.name = name
    row.native_affects = bool(native_affects)
    row.duration_months = dm
    row.duration_months_native = dmn
    row.duration_months_non_native = dmnn
    row.sort_order = int(sort_order or 0)
    row.is_active = bool(is_active)
    db.flush()
    return row


def toggle_duty_region(db: Session, code: str) -> ServiceDutyRegion:
    row = get_duty_region(db, code)
    if not row:
        raise ServiceDutyRegionError("منطقه یافت نشد")
    row.is_active = not bool(row.is_active)
    db.flush()
    return row


def delete_duty_region(db: Session, code: str) -> None:
    row = get_duty_region(db, code)
    if not row:
        raise ServiceDutyRegionError("منطقه یافت نشد")

    in_use = (
        db.query(Contract.id)
        .filter(Contract.service_duty_region_code == row.code)
        .first()
    )
    if in_use:
        raise ServiceDutyRegionError(
            "حذف ممکن نیست؛ قرارداد به این منطقه منتسب است. ابتدا غیرفعال کنید."
        )
    db.delete(row)
    db.flush()


def region_as_dict(row: ServiceDutyRegion) -> dict:
    return {
        "code": row.code,
        "name": row.name,
        "native_affects": bool(row.native_affects),
        "duration_months": row.duration_months,
        "duration_months_native": row.duration_months_native,
        "duration_months_non_native": row.duration_months_non_native,
        "sort_order": row.sort_order,
        "is_active": bool(row.is_active),
    }


# Seed اختیاری insert-only — runtime به وجود این ردیف‌ها وابسته نیست
_OPTIONAL_SEED = (
    ("OPERATIONAL", "مناطق درگیر و عملیاتی", True, None, 15, 14, 10),
    ("BORDER_HARSH", "مناطق مرزی و بدآب‌وهوا", True, None, 15, 15, 20),
    ("NORMAL_DUTY", "مناطق عادی", True, None, 21, 18, 30),
    ("AMRIYEH", "امریه دستگاه غیرنظامی", False, 24, None, None, 40),
)


def seed_default_duty_regions(db: Session) -> int:
    """Insert-only seed برای محیط خالی؛ هیچ overwrite روی ردیف موجود."""
    created = 0
    for (
        code,
        name,
        native_affects,
        duration_months,
        duration_months_native,
        duration_months_non_native,
        sort_order,
    ) in _OPTIONAL_SEED:
        if get_duty_region(db, code):
            continue
        db.add(
            ServiceDutyRegion(
                code=code,
                name=name,
                native_affects=native_affects,
                duration_months=duration_months,
                duration_months_native=duration_months_native,
                duration_months_non_native=duration_months_non_native,
                sort_order=sort_order,
                is_active=True,
            )
        )
        created += 1
    if created:
        db.flush()
    return created
