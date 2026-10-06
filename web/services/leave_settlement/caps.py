"""
Dated settlement caps: per-year storage transfer + buyback by membership/region/period.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import jdatetime
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.leave_settlement_cap_period import LeaveSettlementCapPeriod
from models.policy import Policy, PolicyValue
from web.services.leave_entitlement_service import (
    jalali_year_bounds_g,
    resolve_max_buyback as resolve_max_buyback_legacy,
    resolve_max_carry_forward as resolve_max_carry_forward_legacy,
    resolve_membership_code_for_policy,
    resolve_region_code_from_service_location,
)


class SettlementCapOverlapError(ValueError):
    """بازه با ردیف موجود هم‌پوشانی دارد."""


def _region_applies(db: Session, membership_code: str) -> bool:
    code = resolve_membership_code_for_policy(membership_code)
    policy = db.query(Policy).filter(Policy.category == "leave").first()
    if not policy:
        return True
    flag = (
        db.query(PolicyValue)
        .filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == f"region_applies_dept_{code}",
            PolicyValue.region_code.is_(None),
        )
        .first()
    )
    if flag is None:
        return True
    return flag.parameter_value not in ("false", "0", "off", "")


def jalali_year_end_g(year_j: int) -> date:
    """آخرین روز میلادی سال شمسی (برای as_of سالانه)."""
    _, end_g = jalali_year_bounds_g(year_j)
    return end_g


def _range_overlaps(
    from_a: date,
    to_a: Optional[date],
    from_b: date,
    to_b: Optional[date],
) -> bool:
    """بازه نیمه‌باز [from, to] با to=None به‌معنی باز."""
    end_a = to_a or date.max
    end_b = to_b or date.max
    return from_a <= end_b and from_b <= end_a


def list_periods(
    db: Session,
    *,
    membership_code: Optional[str] = None,
    region_code: Optional[str] = None,
    membership_level_only: bool = False,
) -> List[LeaveSettlementCapPeriod]:
    q = db.query(LeaveSettlementCapPeriod)
    if membership_code is not None:
        q = q.filter(
            LeaveSettlementCapPeriod.membership_code
            == resolve_membership_code_for_policy(membership_code)
        )
    if membership_level_only:
        q = q.filter(LeaveSettlementCapPeriod.region_code.is_(None))
    elif region_code is not None:
        q = q.filter(LeaveSettlementCapPeriod.region_code == region_code)
    return q.order_by(
        LeaveSettlementCapPeriod.membership_code,
        LeaveSettlementCapPeriod.region_code.nullsfirst(),
        LeaveSettlementCapPeriod.effective_from,
    ).all()


def find_covering_period(
    db: Session,
    membership_code: str,
    *,
    region_code: Optional[str],
    as_of: date,
    membership_level: bool,
) -> Optional[LeaveSettlementCapPeriod]:
    code = resolve_membership_code_for_policy(membership_code)
    q = db.query(LeaveSettlementCapPeriod).filter(
        LeaveSettlementCapPeriod.membership_code == code,
        LeaveSettlementCapPeriod.effective_from <= as_of,
        or_(
            LeaveSettlementCapPeriod.effective_to.is_(None),
            LeaveSettlementCapPeriod.effective_to >= as_of,
        ),
    )
    if membership_level:
        q = q.filter(LeaveSettlementCapPeriod.region_code.is_(None))
    else:
        if not region_code:
            return None
        q = q.filter(LeaveSettlementCapPeriod.region_code == region_code)
    return q.order_by(LeaveSettlementCapPeriod.effective_from.desc()).first()


def resolve_settlement_caps(
    db: Session,
    membership_code: str,
    *,
    region_code: Optional[str] = None,
    user_id: Optional[str] = None,
    as_of_date: Optional[date] = None,
    year_j: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Resolve storage_cap + buyback_cap for as_of.

    Lookup: region row (if region_applies) → membership-level row → legacy PolicyValues.
    """
    code = resolve_membership_code_for_policy(membership_code)
    if as_of_date is None:
        if year_j is not None:
            as_of_date = jalali_year_end_g(int(year_j))
        else:
            as_of_date = date.today()

    applies = _region_applies(db, code)
    effective_region = region_code
    if applies and not effective_region and user_id:
        effective_region = resolve_region_code_from_service_location(db, user_id)

    if applies and effective_region:
        row = find_covering_period(
            db,
            code,
            region_code=effective_region,
            as_of=as_of_date,
            membership_level=False,
        )
        if row is not None:
            return {
                "storage_cap": row.storage_cap,
                "buyback_cap": row.buyback_cap,
                "source": "period_region",
                "period_id": row.id,
                "as_of": as_of_date,
                "region_code": effective_region,
            }

    row = find_covering_period(
        db,
        code,
        region_code=None,
        as_of=as_of_date,
        membership_level=True,
    )
    if row is not None:
        return {
            "storage_cap": row.storage_cap,
            "buyback_cap": row.buyback_cap,
            "source": "period_membership",
            "period_id": row.id,
            "as_of": as_of_date,
            "region_code": None,
        }

    year_for_legacy = year_j
    if year_for_legacy is None:
        year_for_legacy = jdatetime.date.fromgregorian(date=as_of_date).year

    return {
        "storage_cap": resolve_max_carry_forward_legacy(db, code),
        "buyback_cap": resolve_max_buyback_legacy(
            db,
            code,
            user_id=user_id,
            region_code=effective_region,
            year_j=year_for_legacy,
            _skip_dated_periods=True,
        ),
        "source": "legacy",
        "period_id": None,
        "as_of": as_of_date,
        "region_code": effective_region if applies else None,
    }


def assert_no_overlap(
    db: Session,
    *,
    membership_code: str,
    region_code: Optional[str],
    effective_from: date,
    effective_to: Optional[date],
    exclude_id: Optional[int] = None,
) -> None:
    code = resolve_membership_code_for_policy(membership_code)
    q = db.query(LeaveSettlementCapPeriod).filter(
        LeaveSettlementCapPeriod.membership_code == code,
    )
    if region_code is None:
        q = q.filter(LeaveSettlementCapPeriod.region_code.is_(None))
    else:
        q = q.filter(LeaveSettlementCapPeriod.region_code == region_code)
    if exclude_id is not None:
        q = q.filter(LeaveSettlementCapPeriod.id != exclude_id)
    for other in q.all():
        if _range_overlaps(
            effective_from, effective_to, other.effective_from, other.effective_to
        ):
            raise SettlementCapOverlapError(
                f"بازه با ردیف #{other.id} "
                f"({other.effective_from}–{other.effective_to or 'باز'}) هم‌پوشانی دارد"
            )


def create_period(
    db: Session,
    *,
    membership_code: str,
    region_code: Optional[str],
    effective_from: date,
    effective_to: Optional[date],
    storage_cap: Optional[int],
    buyback_cap: Optional[int],
    created_by: Optional[str] = None,
    commit: bool = True,
) -> LeaveSettlementCapPeriod:
    code = resolve_membership_code_for_policy(membership_code)
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("تاریخ پایان نمی‌تواند قبل از شروع باشد")
    if storage_cap is not None and storage_cap < 0:
        raise ValueError("سقف ذخیره نمی‌تواند منفی باشد")
    if buyback_cap is not None and buyback_cap < 0:
        raise ValueError("سقف بازخرید نمی‌تواند منفی باشد")

    # region خالی = سطح عضویت (همه مناطق / وقتی اعمال منطقه خاموش است)
    if not _region_applies(db, code):
        region_code = None
    else:
        region_code = (region_code or None)

    assert_no_overlap(
        db,
        membership_code=code,
        region_code=region_code,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    row = LeaveSettlementCapPeriod(
        membership_code=code,
        region_code=region_code,
        effective_from=effective_from,
        effective_to=effective_to,
        storage_cap=storage_cap,
        buyback_cap=buyback_cap,
        created_by=created_by,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def update_period(
    db: Session,
    period_id: int,
    *,
    membership_code: Optional[str] = None,
    region_code: Optional[str] = None,
    effective_from: Optional[date] = None,
    effective_to: Optional[date] = None,
    storage_cap: Optional[int] = None,
    buyback_cap: Optional[int] = None,
    clear_effective_to: bool = False,
    set_region_code: bool = False,
    set_storage_cap: bool = False,
    set_buyback_cap: bool = False,
    commit: bool = True,
) -> LeaveSettlementCapPeriod:
    row = db.query(LeaveSettlementCapPeriod).filter(
        LeaveSettlementCapPeriod.id == period_id
    ).first()
    if not row:
        raise ValueError("ردیف یافت نشد")

    new_membership = (
        resolve_membership_code_for_policy(membership_code)
        if membership_code is not None
        else row.membership_code
    )
    new_from = effective_from if effective_from is not None else row.effective_from
    if clear_effective_to:
        new_to: Optional[date] = None
    elif effective_to is not None:
        new_to = effective_to
    else:
        new_to = row.effective_to
    if new_to is not None and new_to < new_from:
        raise ValueError("تاریخ پایان نمی‌تواند قبل از شروع باشد")

    if set_region_code:
        new_region = region_code or None
    else:
        new_region = row.region_code
    if not _region_applies(db, new_membership):
        new_region = None

    new_storage = row.storage_cap
    if set_storage_cap:
        new_storage = storage_cap
    new_buyback = row.buyback_cap
    if set_buyback_cap:
        new_buyback = buyback_cap
    if new_storage is not None and new_storage < 0:
        raise ValueError("سقف ذخیره نمی‌تواند منفی باشد")
    if new_buyback is not None and new_buyback < 0:
        raise ValueError("سقف بازخرید نمی‌تواند منفی باشد")

    assert_no_overlap(
        db,
        membership_code=new_membership,
        region_code=new_region,
        effective_from=new_from,
        effective_to=new_to,
        exclude_id=row.id,
    )
    row.membership_code = new_membership
    row.region_code = new_region
    row.effective_from = new_from
    row.effective_to = new_to
    row.storage_cap = new_storage
    row.buyback_cap = new_buyback
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def delete_period(db: Session, period_id: int, *, commit: bool = True) -> None:
    row = db.query(LeaveSettlementCapPeriod).filter(
        LeaveSettlementCapPeriod.id == period_id
    ).first()
    if not row:
        raise ValueError("ردیف یافت نشد")
    db.delete(row)
    if commit:
        db.commit()
    else:
        db.flush()


def parse_jalali_date(text: str) -> Optional[date]:
    raw = (text or "").strip().replace("-", "/")
    if not raw:
        return None
    parts = [int(p) for p in raw.split("/")]
    if len(parts) != 3:
        raise ValueError("تاریخ نامعتبر است")
    return jdatetime.date(parts[0], parts[1], parts[2]).togregorian()


def parse_optional_cap(raw: str) -> Optional[int]:
    text = (raw or "").strip().lower()
    if text in ("", "none", "null", "-1", "unlimited"):
        return None
    return max(0, int(float(text)))


def _jalali_year_end(year_j: int) -> date:
    return jalali_year_bounds_g(year_j)[1]


def _jalali_year_start(year_j: int) -> date:
    return jalali_year_bounds_g(year_j)[0]


def seed_default_settlement_cap_periods(
    db: Session,
    *,
    created_by: str = "system",
    force: bool = False,
) -> int:
    """
    درج پیش‌فرض‌های قابل‌ویرایش (فقط وقتی جدول خالی است، مگر force=True).

    رسمی:
      ۱۳۰۰–۱۳۸۹ ذخیره/بازخرید نامحدود (سطح عضویت)
      ۱۳۹۰–۱۳۹۸ ذخیره نامحدود، بازخرید ۱۵ (سطح عضویت)
      از ۱۳۹۹: ذخیره نامحدود؛ بازخرید به‌ازای منطقه (عادی ۱۵، …)
    قراردادی: ذخیره ۹، بازخرید ۹
    وظیفه / خریدخدمت: هر دو نامحدود
    """
    from web.services.leave_entitlement_service import DEFAULT_BUYBACK_BY_REGION

    existing = db.query(LeaveSettlementCapPeriod).count()
    if existing and not force:
        return 0

    if force and existing:
        db.query(LeaveSettlementCapPeriod).delete()
        db.flush()

    specs: List[Dict[str, Any]] = [
        {
            "membership_code": "1",
            "region_code": None,
            "effective_from": _jalali_year_start(1300),
            "effective_to": _jalali_year_end(1389),
            "storage_cap": None,
            "buyback_cap": None,
        },
        {
            "membership_code": "1",
            "region_code": None,
            "effective_from": _jalali_year_start(1390),
            "effective_to": _jalali_year_end(1398),
            "storage_cap": None,
            "buyback_cap": 15,
        },
    ]
    for region_code, bb in DEFAULT_BUYBACK_BY_REGION.items():
        specs.append(
            {
                "membership_code": "1",
                "region_code": region_code,
                "effective_from": _jalali_year_start(1399),
                "effective_to": None,
                "storage_cap": None,
                "buyback_cap": int(bb),
            }
        )
    specs.extend(
        [
            {
                "membership_code": "4",
                "region_code": None,
                "effective_from": _jalali_year_start(1300),
                "effective_to": None,
                "storage_cap": 9,
                "buyback_cap": 9,
            },
            {
                "membership_code": "2",
                "region_code": None,
                "effective_from": _jalali_year_start(1300),
                "effective_to": None,
                "storage_cap": None,
                "buyback_cap": None,
            },
            {
                "membership_code": "3",
                "region_code": None,
                "effective_from": _jalali_year_start(1300),
                "effective_to": None,
                "storage_cap": None,
                "buyback_cap": None,
            },
        ]
    )

    created = 0
    for spec in specs:
        # ensure region row exists when seeding regional caps
        if spec["region_code"]:
            from models.region import Region

            if not db.query(Region).filter(
                Region.code == spec["region_code"]
            ).first():
                continue
        create_period(
            db,
            membership_code=spec["membership_code"],
            region_code=spec["region_code"],
            effective_from=spec["effective_from"],
            effective_to=spec["effective_to"],
            storage_cap=spec["storage_cap"],
            buyback_cap=spec["buyback_cap"],
            created_by=created_by,
            commit=False,
        )
        created += 1
    db.commit()
    return created

