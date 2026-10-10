"""منبع قطعی نوع عضویت. هیچ مسیر این ماژول از Employee.department حدس نمی‌زند."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.membership_type import MembershipType


SOURCE_CONTRACT = "contract"
SOURCE_BASE = "base"
SOURCE_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class MembershipResolution:
    code: Optional[str]
    source: str
    contract_id: Optional[int] = None
    ambiguous: bool = False

    @property
    def resolved(self) -> bool:
        return self.source != SOURCE_UNRESOLVED and bool(self.code)


def membership_code_known(db: Session, code: Optional[str]) -> bool:
    text = str(code or "").strip()
    if not text:
        return False
    return (
        db.query(MembershipType.code)
        .filter(MembershipType.code == text)
        .first()
        is not None
    )


def resolve_covering_contract(
    db: Session,
    user_id: str,
    on_date: date,
) -> tuple[Optional[Contract], bool]:
    """قرارداد پوشش‌دهنده تاریخ. دو قرارداد با یک start_date مبهم است."""
    contracts = (
        db.query(Contract)
        .filter(
            Contract.user_id == user_id,
            Contract.start_date <= on_date,
            Contract.end_date.is_(None) | (Contract.end_date >= on_date),
        )
        .order_by(Contract.start_date.desc(), Contract.id.desc())
        .all()
    )
    if not contracts:
        return None, False
    if len(contracts) > 1 and contracts[0].start_date == contracts[1].start_date:
        return None, True
    return contracts[0], False


def resolve_employee_membership(
    db: Session,
    user_id: str,
    on_date: Optional[date] = None,
) -> MembershipResolution:
    """
    1. قرارداد پوشش‌دهنده on_date، اگر کدش در membership_types باشد
    2. وگرنه Employee.membership_type_code معتبر
    3. وگرنه unresolved — هرگز «4» یا نوع دیگری انتخاب نمی‌شود

    استثنای توراهی رسمی/وظیفه در travel_leave_service است و اینجا اعمال نمی‌شود.
    """
    target = on_date or date.today()
    contract, ambiguous = resolve_covering_contract(db, user_id, target)
    if ambiguous:
        return MembershipResolution(None, SOURCE_UNRESOLVED, ambiguous=True)
    if contract is not None:
        code = str(contract.contract_type_code or "").strip()
        if membership_code_known(db, code):
            return MembershipResolution(code, SOURCE_CONTRACT, contract.id)
        return MembershipResolution(None, SOURCE_UNRESOLVED, contract.id)

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if employee is not None:
        base = str(employee.membership_type_code or "").strip()
        if membership_code_known(db, base):
            return MembershipResolution(base, SOURCE_BASE)
    return MembershipResolution(None, SOURCE_UNRESOLVED)


def membership_code_for(
    db: Session,
    employee: Optional[Employee],
    on_date: Optional[date] = None,
) -> Optional[str]:
    if employee is None:
        return None
    return resolve_employee_membership(db, employee.user_id, on_date).code


def holiday_applies(group_id: Optional[str], membership_code: Optional[str]) -> bool:
    """NULL گروه = ملی. گروه غیرخالی فقط با همان کد عضویت."""
    if group_id is None:
        return True
    return bool(membership_code) and str(group_id) == str(membership_code)


def sync_employee_base_membership_from_active_contract(
    db: Session,
    user_id: str,
    commit: bool = False,
) -> Optional[str]:
    """
    عضویت پایه را با عضویت مؤثر هم‌تراز می‌کند.
    دپارتمان سازمانی را هرگز نمی‌نویسد. بدون قرارداد، پایه پاک نمی‌شود.
    """
    today = date.today()
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.desc(), Contract.id.desc())
        .all()
    )
    if not contracts:
        return None

    chosen = None
    for contract in contracts:
        if contract.start_date <= today and contract.is_active:
            chosen = contract
            break
    if chosen is None:
        chosen = contracts[0]

    code = str(chosen.contract_type_code or "").strip()
    if not membership_code_known(db, code):
        return None

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if employee is None:
        return None
    if employee.membership_type_code != code:
        employee.membership_type_code = code
        if commit:
            db.commit()
    return code


def resolve_membership_type_code(
    db: Session,
    raw: Optional[str],
    *,
    allow_current: Optional[str] = None,
) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None
    row = db.get(MembershipType, text)
    if row is None:
        raise ValueError("نوع عضویت انتخاب‌شده نامعتبر است")
    if not row.is_active and text != (allow_current or ""):
        raise ValueError("نوع عضویت انتخاب‌شده غیرفعال است")
    return row.code


sync_employee_department_from_active_contract = (
    sync_employee_base_membership_from_active_contract
)
