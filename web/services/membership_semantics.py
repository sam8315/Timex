"""
Canonical membership domain semantics — identity (code) جدا از behavior.

Runtime نباید با if code == \"1\" قانون مرخصی را تشخیص دهد؛
از behavior_profile ذخیره‌شده روی membership_types استفاده می‌کند.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, TYPE_CHECKING

from sqlalchemy.orm import Session

from models.membership_type import (
    BEHAVIOR_CONSCRIPT,
    BEHAVIOR_PERMANENT,
    BEHAVIOR_PHYSICIAN,
    BEHAVIOR_STANDARD_PRORATE,
    MembershipType,
)
from models.membership_type_rule import (
    LEAVE_START_BASIS_CHOICES,
    LEAVE_START_BASIS_LABELS,
    LEAVE_START_CLINIC_ENTRY,
    LEAVE_START_DISPATCH,
    LEAVE_START_UNIT_ENTRY,
)

if TYPE_CHECKING:
    from models.contract import Contract

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
    # Seed codes with NULL/empty profile (legacy DB): use seed map only for 1–7
    if code in SEED_BEHAVIOR_BY_CODE:
        return SEED_BEHAVIOR_BY_CODE[code]
    # Missing / custom type without profile: safe default
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


def normalize_leave_start_basis(value: Optional[str]) -> str:
    """Validate / default leave_start_date_basis enum."""
    v = (value or LEAVE_START_DISPATCH).strip()
    if v not in LEAVE_START_BASIS_CHOICES:
        return LEAVE_START_DISPATCH
    return v


def resolve_leave_start_basis(
    db: Session,
    membership_code: str,
    *,
    on_date: Optional[date] = None,
) -> str:
    """Effective rule's leave start basis; default dispatch."""
    from web.services.membership_service import get_effective_rule

    rule = get_effective_rule(db, membership_code, on_date=on_date)
    if rule is None:
        return LEAVE_START_DISPATCH
    return normalize_leave_start_basis(
        getattr(rule, "leave_start_date_basis", None)
    )


def resolve_conscript_leave_start(
    db: Session,
    contract: "Contract",
    *,
    on_date: Optional[date] = None,
) -> date:
    """
    Coverage/charge start for conscript leave.

    Non-conscript → contract.start_date.
    Conscript → field from leave_start_date_basis, fallback dispatch → start_date.
    """
    code = str(contract.contract_type_code or "")
    if not is_conscript(db, code):
        return contract.start_date

    as_of = on_date or contract.start_date or date.today()
    basis = resolve_leave_start_basis(db, code, on_date=as_of)
    if basis == LEAVE_START_UNIT_ENTRY:
        chosen = contract.unit_entry_date
    elif basis == LEAVE_START_CLINIC_ENTRY:
        chosen = contract.clinic_entry_date
    else:
        chosen = contract.dispatch_date
    return chosen or contract.dispatch_date or contract.start_date


def leave_start_basis_label(basis: Optional[str]) -> str:
    key = normalize_leave_start_basis(basis)
    return LEAVE_START_BASIS_LABELS.get(key, key)


def uses_region_buyback_eras(db: Session, membership_code: str) -> bool:
    """رسمی: سقف بازخرید از منطقه/عصر تاریخی."""
    return is_permanent(db, membership_code)
