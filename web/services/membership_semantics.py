"""
Canonical membership domain semantics — identity (code) جدا از behavior.

Runtime نباید با if code == \"1\" قانون مرخصی را تشخیص دهد؛
از behavior_profile ذخیره‌شده روی membership_types استفاده می‌کند.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from models.membership_type import (
    BEHAVIOR_CONSCRIPT,
    BEHAVIOR_PERMANENT,
    BEHAVIOR_PHYSICIAN,
    BEHAVIOR_STANDARD_PRORATE,
    MembershipType,
)

# Seed-only map for insert of legacy codes 1–7 (نه runtime lookup)
SEED_BEHAVIOR_BY_CODE = {
    "1": BEHAVIOR_PERMANENT,
    "2": BEHAVIOR_CONSCRIPT,
    "3": BEHAVIOR_STANDARD_PRORATE,
    "4": BEHAVIOR_STANDARD_PRORATE,
    "5": BEHAVIOR_PHYSICIAN,
    "6": BEHAVIOR_STANDARD_PRORATE,
    "7": BEHAVIOR_STANDARD_PRORATE,
}

COVERAGE_OPEN_YEAR = "open_year"
COVERAGE_ACTUAL_END = "actual_end"
COVERAGE_CONTRACT_END = "contract_end"

CHARGE_PERMANENT = "permanent"
CHARGE_PHYSICIAN = "physician"
CHARGE_PRORATE = "prorate"


def get_behavior_profile(db: Session, membership_code: str) -> str:
    code = str(membership_code or "").strip()
    if not code:
        return BEHAVIOR_STANDARD_PRORATE
    row = db.query(MembershipType).filter(MembershipType.code == code).first()
    if row is not None and row.behavior_profile:
        return str(row.behavior_profile)
    # Missing type: safe default (never invent permanent/conscript from bare code)
    return BEHAVIOR_STANDARD_PRORATE


def is_permanent(db: Session, membership_code: str) -> bool:
    return get_behavior_profile(db, membership_code) == BEHAVIOR_PERMANENT


def is_conscript(db: Session, membership_code: str) -> bool:
    return get_behavior_profile(db, membership_code) == BEHAVIOR_CONSCRIPT


def is_physician(db: Session, membership_code: str) -> bool:
    return get_behavior_profile(db, membership_code) == BEHAVIOR_PHYSICIAN


def coverage_mode(db: Session, membership_code: str) -> str:
    profile = get_behavior_profile(db, membership_code)
    if profile == BEHAVIOR_PERMANENT:
        return COVERAGE_OPEN_YEAR
    if profile == BEHAVIOR_CONSCRIPT:
        return COVERAGE_ACTUAL_END
    return COVERAGE_CONTRACT_END


def charge_mode(db: Session, membership_code: str) -> str:
    profile = get_behavior_profile(db, membership_code)
    if profile == BEHAVIOR_PERMANENT:
        return CHARGE_PERMANENT
    if profile == BEHAVIOR_PHYSICIAN:
        return CHARGE_PHYSICIAN
    return CHARGE_PRORATE


def uses_department_travel_resolve(db: Session, membership_code: str) -> bool:
    """Travel Leave: official/conscript resolve via Employee.department (رفتار فعلی)."""
    profile = get_behavior_profile(db, membership_code)
    return profile in (BEHAVIOR_PERMANENT, BEHAVIOR_CONSCRIPT)


def default_buyback_cap(db: Session, membership_code: str) -> Optional[int]:
    """پیش‌فرض بدون رکورد سیاست — همان رفتار قبلی بدون code literals."""
    profile = get_behavior_profile(db, membership_code)
    if profile == BEHAVIOR_PERMANENT:
        return 15
    # conscript / physician / standard_prorate → unlimited (None)
    return None


def uses_region_buyback_eras(db: Session, membership_code: str) -> bool:
    """رسمی: سقف بازخرید از منطقه/عصر تاریخی."""
    return is_permanent(db, membership_code)
