"""
سرویس خواندن/نوشتن انواع عضویت و Ruleهای نسخه‌دار.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.membership_rule_change import MembershipRuleChangeRequest
from models.membership_type import MembershipType
from models.membership_type_rule import MembershipTypeRule
from models.policy import Policy, PolicyValue
from models.region import Region
from models.reserved_membership_code import ReservedMembershipCode
from models.service_adjustment import ServiceAdjustment
from models.travel_leave_policy import TravelLeavePolicy

CODE_RE = re.compile(r"^[1-9][0-9]{0,5}$")

# Seed snapshot: code, name, annual, deduction, extra, seniority, sort_order
# فقط برای seed/reconcile — نه برای runtime name lookup در UI/reports.
SEED_MEMBERSHIPS: Tuple[Tuple[str, str, int, bool, bool, bool, int], ...] = (
    ("1", "رسمی", 30, False, False, True, 1),
    ("2", "وظیفه", 30, True, True, False, 2),
    ("3", "خریدخدمت", 30, False, False, False, 3),
    ("4", "قراردادی", 30, False, False, False, 4),
    ("5", "پزشکی", 0, False, False, False, 5),
    ("6", "سایر / متفرقه", 0, False, False, False, 6),
    ("7", "قرارداد با بیمه‌ها", 0, False, False, False, 7),
)

SEED_CODE_FLAGS = {
    code: {
        "name": name,
        "annual_leave_base": annual,
        "supports_service_deduction": deduction,
        "supports_extra_service": extra,
        "supports_positive_seniority": seniority,
        "sort_order": sort_order,
    }
    for code, name, annual, deduction, extra, seniority, sort_order in SEED_MEMBERSHIPS
}


class MembershipError(ValueError):
    pass


def validate_membership_code(code: str) -> str:
    code = (code or "").strip()
    if not CODE_RE.match(code):
        raise MembershipError(
            "کد عضویت باید عدد مثبت حداکثر ۶ رقم باشد (بدون صفر پیشرو)"
        )
    return code


def list_membership_types(
    db: Session,
    *,
    active_only: bool = False,
) -> List[MembershipType]:
    q = db.query(MembershipType)
    if active_only:
        q = q.filter(MembershipType.is_active.is_(True))
    return q.order_by(
        MembershipType.sort_order, MembershipType.code
    ).all()


def get_membership_type(db: Session, code: str) -> Optional[MembershipType]:
    return db.query(MembershipType).filter(MembershipType.code == code).first()


def membership_types_as_dict(db: Session, *, active_only: bool = True) -> Dict[str, dict]:
    """جایگزین CONTRACT_TYPES برای UI/validation (از DB)."""
    result: Dict[str, dict] = {}
    for row in list_membership_types(db, active_only=active_only):
        rule = get_effective_rule(db, row.code)
        result[row.code] = {
            "name": row.name,
            "annual_leave_base": rule.annual_leave_base if rule else 0,
            "supports_service_deduction": (
                rule.supports_service_deduction if rule else False
            ),
            "supports_extra_service": (
                rule.supports_extra_service if rule else False
            ),
            "supports_positive_seniority": (
                rule.supports_positive_seniority if rule else False
            ),
            "is_active": row.is_active,
            "description": row.description,
            "sort_order": row.sort_order,
        }
    return result


def employment_type_options(db: Session, *, active_only: bool = False) -> List[Tuple[str, str]]:
    """گزینه‌های فیلتر گزارش/UI: all + membership_types از DB."""
    opts: List[Tuple[str, str]] = [("all", "همه")]
    for row in list_membership_types(db, active_only=active_only):
        opts.append((row.code, row.name))
    return opts


def get_effective_rule(
    db: Session,
    membership_type_code: str,
    on_date: Optional[date] = None,
) -> Optional[MembershipTypeRule]:
    """
    Rule مؤثر فقط بر اساس تاریخ: آخرین effective_from <= on_date.
    status مانع resolve نیست (برای lifecycle/UI به‌روز می‌شود).
    """
    on_date = on_date or date.today()
    return (
        db.query(MembershipTypeRule)
        .filter(
            MembershipTypeRule.membership_type_code == membership_type_code,
            MembershipTypeRule.effective_from <= on_date,
        )
        .order_by(MembershipTypeRule.effective_from.desc())
        .first()
    )


def refresh_rule_lifecycle_statuses(
    db: Session,
    membership_type_code: str,
    *,
    as_of: Optional[date] = None,
) -> None:
    """به‌روزرسانی status برای UI؛ resolve از status استفاده نمی‌کند."""
    today = as_of or date.today()
    rules = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == membership_type_code)
        .order_by(MembershipTypeRule.effective_from.asc())
        .all()
    )
    effective = None
    for rule in rules:
        if rule.effective_from > today:
            rule.status = "scheduled"
        elif effective is None or rule.effective_from >= effective.effective_from:
            if effective is not None and effective.effective_from < rule.effective_from:
                effective.status = "superseded"
            rule.status = "active"
            effective = rule
        else:
            rule.status = "superseded"
    db.flush()


def resolve_annual_leave_base(
    db: Session,
    membership_code: str,
    on_date: Optional[date] = None,
) -> int:
    rule = get_effective_rule(db, membership_code, on_date=on_date)
    if rule is None:
        return 0
    return max(0, int(rule.annual_leave_base))


def _get_leave_policy(db: Session) -> Optional[Policy]:
    return db.query(Policy).filter(Policy.category == "leave").first()


def _get_policy_param(
    db: Session,
    policy_id: int,
    key: str,
    region_code: Optional[str] = None,
) -> Optional[PolicyValue]:
    query = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy_id,
        PolicyValue.parameter_key == key,
    )
    if region_code is None:
        query = query.filter(PolicyValue.region_code.is_(None))
    else:
        query = query.filter(PolicyValue.region_code == region_code)
    return query.first()


def _region_applies(db: Session, policy_id: int, membership_code: str) -> bool:
    flag = _get_policy_param(
        db, policy_id, f"region_applies_dept_{membership_code}"
    )
    if flag is None:
        return True
    return flag.parameter_value not in ("false", "0", "off", "")


def resolve_annual_leave_base_with_region(
    db: Session,
    membership_code: str,
    region_code: Optional[str] = None,
    on_date: Optional[date] = None,
) -> int:
    """
    Membership annual_leave_base
    → Leave Policy region_applies
    → regional override if present
    → fallback to annual_leave_base
    """
    base = resolve_annual_leave_base(db, membership_code, on_date=on_date)
    policy = _get_leave_policy(db)
    if not policy:
        return base
    if not _region_applies(db, policy.id, membership_code):
        return base
    if not region_code:
        return base

    region = db.query(Region).filter(Region.code == region_code).first()
    if region is None:
        return base

    region_days = int(region.default_annual_leave_days)
    scoped = _get_policy_param(
        db, policy.id, "annual_leave_days", region_code=region_code
    )
    if scoped and scoped.parameter_value is not None:
        try:
            region_days = int(float(scoped.parameter_value))
        except (TypeError, ValueError):
            pass
    return max(0, region_days)


def count_business_dependencies(db: Session, code: str) -> dict:
    """Business History — مانع hard delete؛ technical children cascade مانع نیستند."""
    contracts = (
        db.query(func.count(Contract.id))
        .filter(Contract.contract_type_code == code)
        .scalar()
        or 0
    )
    travel = (
        db.query(func.count(TravelLeavePolicy.id))
        .filter(TravelLeavePolicy.contract_type_code == code)
        .scalar()
        or 0
    )
    rule_requests = (
        db.query(func.count(MembershipRuleChangeRequest.id))
        .filter(MembershipRuleChangeRequest.membership_type_code == code)
        .scalar()
        or 0
    )
    service_adj = (
        db.query(func.count(ServiceAdjustment.id))
        .join(Contract, ServiceAdjustment.contract_id == Contract.id)
        .filter(Contract.contract_type_code == code)
        .scalar()
        or 0
    )
    employees = (
        db.query(func.count(Employee.user_id))
        .filter(Employee.department == code)
        .scalar()
        or 0
    )
    return {
        "contracts": int(contracts),
        "travel_leave_policies": int(travel),
        "membership_rule_change_requests": int(rule_requests),
        "service_adjustments": int(service_adj),
        "employees": int(employees),
    }


def has_business_history(db: Session, code: str) -> bool:
    deps = count_business_dependencies(db, code)
    return any(deps.values())


def create_membership_type(
    db: Session,
    *,
    code: str,
    name: str,
    description: Optional[str] = None,
    sort_order: int = 0,
    is_active: bool = True,
    created_by: Optional[str] = None,
    migration_date: Optional[date] = None,
) -> MembershipType:
    code = validate_membership_code(code)
    name = (name or "").strip()
    if not name:
        raise MembershipError("نام نوع عضویت الزامی است")
    if len(name) > 100:
        raise MembershipError("نام نوع عضویت نباید بیشتر از ۱۰۰ کاراکتر باشد")

    if db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).first():
        raise MembershipError("این کد قبلاً مصرف شده و قابل استفاده مجدد نیست")

    if get_membership_type(db, code):
        raise MembershipError("نوع عضویت با این کد از قبل وجود دارد")

    row = MembershipType(
        code=code,
        name=name,
        description=(description or None),
        sort_order=sort_order,
        is_active=is_active,
        code_locked=False,
    )
    db.add(row)
    db.flush()

    # Rule نسخه اول — هرگز از عضویت دیگر ارث نمی‌برد؛ flags همه false، annual=0
    effective = migration_date or date.today()
    db.add(
        MembershipTypeRule(
            membership_type_code=code,
            effective_from=effective,
            annual_leave_base=0,
            supports_service_deduction=False,
            supports_extra_service=False,
            supports_positive_seniority=False,
            status="active",
            created_by=created_by,
        )
    )
    db.flush()
    return row


def create_rule_snapshot(
    db: Session,
    *,
    membership_type_code: str,
    effective_from: date,
    annual_leave_base: int,
    supports_service_deduction: bool,
    supports_extra_service: bool,
    supports_positive_seniority: bool,
    created_by: Optional[str] = None,
) -> MembershipTypeRule:
    """ایجاد Rule جدید به‌صورت snapshot کامل؛ non-overlapping."""
    mt = get_membership_type(db, membership_type_code)
    if not mt:
        raise MembershipError("نوع عضویت یافت نشد")

    annual_leave_base = max(0, int(annual_leave_base))
    existing_same = (
        db.query(MembershipTypeRule)
        .filter(
            MembershipTypeRule.membership_type_code == membership_type_code,
            MembershipTypeRule.effective_from == effective_from,
        )
        .first()
    )
    if existing_same:
        raise MembershipError("برای این تاریخ effective_from قبلاً Rule ثبت شده است")

    today = date.today()
    prev = get_effective_rule(db, membership_type_code, on_date=effective_from)

    status = "scheduled" if effective_from > today else "active"
    rule = MembershipTypeRule(
        membership_type_code=membership_type_code,
        effective_from=effective_from,
        annual_leave_base=annual_leave_base,
        supports_service_deduction=bool(supports_service_deduction),
        supports_extra_service=bool(supports_extra_service),
        supports_positive_seniority=bool(supports_positive_seniority),
        status=status,
        supersedes_rule_id=prev.id if prev else None,
        created_by=created_by,
    )
    db.add(rule)
    db.flush()
    refresh_rule_lifecycle_statuses(db, membership_type_code)

    if has_business_history(db, membership_type_code):
        mt.code_locked = True
    return rule


def update_scheduled_rule(
    db: Session,
    rule_id: int,
    *,
    annual_leave_base: int,
    supports_service_deduction: bool,
    supports_extra_service: bool,
    supports_positive_seniority: bool,
    effective_from: Optional[date] = None,
) -> MembershipTypeRule:
    rule = db.query(MembershipTypeRule).filter(MembershipTypeRule.id == rule_id).first()
    if not rule:
        raise MembershipError("Rule یافت نشد")
    today = date.today()
    # Past/current immutable؛ فقط آینده قابل ویرایش
    if rule.effective_from <= today:
        raise MembershipError("فقط Rule آینده (scheduled) قابل ویرایش است")

    if effective_from is not None:
        if effective_from <= today:
            raise MembershipError("effective_from باید در آینده باشد")
        clash = (
            db.query(MembershipTypeRule)
            .filter(
                MembershipTypeRule.membership_type_code == rule.membership_type_code,
                MembershipTypeRule.effective_from == effective_from,
                MembershipTypeRule.id != rule.id,
            )
            .first()
        )
        if clash:
            raise MembershipError("تاریخ effective_from با Rule دیگر تداخل دارد")
        rule.effective_from = effective_from

    rule.annual_leave_base = max(0, int(annual_leave_base))
    rule.supports_service_deduction = bool(supports_service_deduction)
    rule.supports_extra_service = bool(supports_extra_service)
    rule.supports_positive_seniority = bool(supports_positive_seniority)
    rule.status = "scheduled"
    db.flush()
    return rule


def delete_scheduled_rule(db: Session, rule_id: int) -> None:
    rule = db.query(MembershipTypeRule).filter(MembershipTypeRule.id == rule_id).first()
    if not rule:
        raise MembershipError("Rule یافت نشد")
    today = date.today()
    if rule.effective_from <= today:
        raise MembershipError("فقط Rule آینده (scheduled) قابل حذف است")
    code = rule.membership_type_code
    db.delete(rule)
    db.flush()
    refresh_rule_lifecycle_statuses(db, code)


def deactivate_membership(db: Session, code: str) -> MembershipType:
    mt = get_membership_type(db, code)
    if not mt:
        raise MembershipError("نوع عضویت یافت نشد")
    mt.is_active = False
    if has_business_history(db, code):
        mt.code_locked = True
    db.flush()
    return mt


def activate_membership(db: Session, code: str) -> MembershipType:
    """Reactivate مجاز حتی پس از inactive."""
    mt = get_membership_type(db, code)
    if not mt:
        raise MembershipError("نوع عضویت یافت نشد")
    mt.is_active = True
    db.flush()
    return mt


def delete_membership(
    db: Session,
    code: str,
    *,
    reserved_by: Optional[str] = None,
) -> None:
    mt = get_membership_type(db, code)
    if not mt:
        raise MembershipError("نوع عضویت یافت نشد")
    deps = count_business_dependencies(db, code)
    if any(deps.values()):
        raise MembershipError(
            "این نوع عضویت سابقه کسب‌وکاری دارد و فقط قابل غیرفعال‌سازی است "
            f"(قرارداد={deps['contracts']}, سیاست توراهی={deps['travel_leave_policies']}, "
            f"درخواست Rule={deps['membership_rule_change_requests']}, "
            f"تعدیل خدمت={deps['service_adjustments']}, "
            f"کارمند={deps['employees']})"
        )
    # Hard delete: rules cascade as technical children؛ reserve code
    db.delete(mt)
    db.flush()
    if not db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).first():
        db.add(
            ReservedMembershipCode(
                code=code,
                reason="hard_delete_unused_membership",
                reserved_by=reserved_by,
            )
        )
    db.flush()


def seed_default_memberships(db: Session, *, migration_date: Optional[date] = None) -> int:
    """
    Seed هفت عضویت اولیه. Idempotent: اگر وجود داشته باشد چیزی اضافه نمی‌کند.
    هیچ عضویت جدیدی فراتر از ۱..۷ نمی‌سازد.
    """
    today = migration_date or date.today()
    created = 0
    for code, name, annual, deduction, extra, seniority, sort_order in SEED_MEMBERSHIPS:
        if get_membership_type(db, code):
            continue
        min_start = (
            db.query(func.min(Contract.start_date))
            .filter(Contract.contract_type_code == code)
            .scalar()
        )
        effective = min_start or today
        row = MembershipType(
            code=code,
            name=name,
            is_active=True,
            description=None,
            sort_order=sort_order,
            code_locked=has_business_history(db, code),
        )
        db.add(row)
        db.flush()
        db.add(
            MembershipTypeRule(
                membership_type_code=code,
                effective_from=effective,
                annual_leave_base=annual,
                supports_service_deduction=deduction,
                supports_extra_service=extra,
                supports_positive_seniority=seniority,
                status="active",
                created_by="system_seed",
            )
        )
        created += 1
    db.flush()
    return created


def reconcile_seed_membership_rules(db: Session) -> int:
    """
    هم‌ترازی flags (+ annual_leave_base seed) روی اولین Rule کدهای 1–7.
    هیچ UPDATE روی contracts / leave_balances / leave_transactions نمی‌زند.
    """
    updated = 0
    for code, flags in SEED_CODE_FLAGS.items():
        mt = get_membership_type(db, code)
        if not mt:
            continue
        if mt.name != flags["name"]:
            mt.name = flags["name"]
        if mt.sort_order != flags["sort_order"]:
            mt.sort_order = flags["sort_order"]
        first_rule = (
            db.query(MembershipTypeRule)
            .filter(MembershipTypeRule.membership_type_code == code)
            .order_by(
                MembershipTypeRule.effective_from.asc(),
                MembershipTypeRule.id.asc(),
            )
            .first()
        )
        if not first_rule:
            continue
        changed = False
        if first_rule.annual_leave_base != flags["annual_leave_base"]:
            first_rule.annual_leave_base = flags["annual_leave_base"]
            changed = True
        if first_rule.supports_service_deduction != flags["supports_service_deduction"]:
            first_rule.supports_service_deduction = flags["supports_service_deduction"]
            changed = True
        if first_rule.supports_extra_service != flags["supports_extra_service"]:
            first_rule.supports_extra_service = flags["supports_extra_service"]
            changed = True
        if first_rule.supports_positive_seniority != flags["supports_positive_seniority"]:
            first_rule.supports_positive_seniority = flags["supports_positive_seniority"]
            changed = True
        if changed:
            updated += 1
    db.flush()
    return updated


def lock_codes_with_history(db: Session) -> int:
    locked = 0
    for mt in list_membership_types(db, active_only=False):
        if has_business_history(db, mt.code) and not mt.code_locked:
            mt.code_locked = True
            locked += 1
    db.flush()
    return locked
