"""CRUD سیاست‌ها، کامپوننت‌ها و assignment حقوق."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.membership_type import MembershipType
from models.payroll import (
    PayrollAnnualLaw,
    PayrollAssignment,
    PayrollComponent,
    PayrollEnabledMembership,
    PayrollRateSettings,
)
from web.services.payroll.seed import ensure_payroll_defaults


class PayrollPolicyError(Exception):
    pass


def list_components(db: Session, include_deleted: bool = False) -> List[PayrollComponent]:
    ensure_payroll_defaults(db)
    q = db.query(PayrollComponent)
    if not include_deleted:
        q = q.filter(PayrollComponent.deleted_at.is_(None))
    return q.order_by(PayrollComponent.sort_order, PayrollComponent.id).all()


def update_component(
    db: Session,
    component_id: int,
    *,
    name: Optional[str] = None,
    subject_to_insurance: Optional[bool] = None,
    subject_to_tax: Optional[bool] = None,
    sort_order: Optional[int] = None,
    is_active: Optional[bool] = None,
    calc_mode: Optional[str] = None,
) -> PayrollComponent:
    comp = db.get(PayrollComponent, component_id)
    if not comp or comp.deleted_at:
        raise PayrollPolicyError("آیتم یافت نشد")
    if name is not None:
        name = name.strip()
        if not name:
            raise PayrollPolicyError("نام آیتم الزامی است")
        comp.name = name
    if subject_to_insurance is not None:
        comp.subject_to_insurance = subject_to_insurance
    if subject_to_tax is not None:
        comp.subject_to_tax = subject_to_tax
    if sort_order is not None:
        comp.sort_order = sort_order
    if is_active is not None:
        comp.is_active = is_active
    if calc_mode:
        from models.payroll import CALC_MODES

        if calc_mode not in CALC_MODES:
            raise PayrollPolicyError("حالت محاسبه نامعتبر است")
        comp.calc_mode = calc_mode
    db.commit()
    db.refresh(comp)
    return comp


def create_component(
    db: Session,
    *,
    code: str,
    name: str,
    kind: str,
    calc_mode: str,
    subject_to_insurance: bool = False,
    subject_to_tax: bool = False,
    sort_order: int = 100,
) -> PayrollComponent:
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        raise PayrollPolicyError("کد و نام الزامی است")
    if db.query(PayrollComponent).filter(PayrollComponent.code == code).first():
        raise PayrollPolicyError("کد آیتم تکراری است")
    if kind not in ("earning", "deduction"):
        raise PayrollPolicyError("نوع آیتم نامعتبر است")
    comp = PayrollComponent(
        code=code,
        name=name,
        kind=kind,
        calc_mode=calc_mode,
        subject_to_insurance=subject_to_insurance,
        subject_to_tax=subject_to_tax,
        sort_order=sort_order,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return comp


def soft_delete_component(db: Session, component_id: int) -> None:
    comp = db.get(PayrollComponent, component_id)
    if not comp or comp.deleted_at:
        raise PayrollPolicyError("آیتم یافت نشد")
    # از حذف کدهای سیستمی حیاتی جلوگیری نمی‌کنیم ولی soft-delete می‌کنیم
    comp.deleted_at = datetime.now(timezone.utc)
    comp.is_active = False
    db.commit()


def get_rate_settings(db: Session) -> PayrollRateSettings:
    ensure_payroll_defaults(db)
    row = db.query(PayrollRateSettings).order_by(PayrollRateSettings.id).first()
    assert row is not None
    return row


def update_rate_settings(db: Session, **kwargs) -> PayrollRateSettings:
    row = get_rate_settings(db)
    for key, value in kwargs.items():
        if hasattr(row, key) and value is not None:
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def list_annual_laws(db: Session) -> List[PayrollAnnualLaw]:
    return (
        db.query(PayrollAnnualLaw)
        .order_by(PayrollAnnualLaw.year_j.desc(), PayrollAnnualLaw.id.desc())
        .all()
    )


def upsert_annual_law(
    db: Session,
    *,
    year_j: int,
    new_seniority_daily: Decimal,
    wage_increase_factor: Decimal,
    effective_from: date,
    effective_to: Optional[date] = None,
    version: str = "1",
    source_reference: Optional[str] = None,
    status: str = "active",
    law_id: Optional[int] = None,
) -> PayrollAnnualLaw:
    if law_id:
        law = db.get(PayrollAnnualLaw, law_id)
        if not law:
            raise PayrollPolicyError("قانون سالانه یافت نشد")
    else:
        law = PayrollAnnualLaw(year_j=year_j, version=version)
        db.add(law)
    law.year_j = year_j
    law.new_seniority_daily = new_seniority_daily
    law.wage_increase_factor = wage_increase_factor
    law.effective_from = effective_from
    law.effective_to = effective_to
    law.version = version or "1"
    law.source_reference = source_reference
    law.status = status or "active"
    db.commit()
    db.refresh(law)
    return law


def delete_annual_law(db: Session, law_id: int) -> None:
    law = db.get(PayrollAnnualLaw, law_id)
    if not law:
        raise PayrollPolicyError("قانون سالانه یافت نشد")
    db.delete(law)
    db.commit()


def list_assignments(db: Session) -> List[PayrollAssignment]:
    from sqlalchemy.orm import joinedload

    return (
        db.query(PayrollAssignment)
        .options(joinedload(PayrollAssignment.component))
        .order_by(PayrollAssignment.effective_from.desc(), PayrollAssignment.id.desc())
        .all()
    )


def create_assignment(
    db: Session,
    *,
    component_id: int,
    amount: Decimal,
    effective_from: date,
    membership_type_code: Optional[str] = None,
    user_id: Optional[str] = None,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
) -> PayrollAssignment:
    if bool(user_id) == bool(membership_type_code):
        raise PayrollPolicyError("یکی از عضویت یا کاربر را مشخص کنید")
    comp = db.get(PayrollComponent, component_id)
    if not comp or comp.deleted_at:
        raise PayrollPolicyError("آیتم یافت نشد")
    row = PayrollAssignment(
        component_id=component_id,
        membership_type_code=membership_type_code or None,
        user_id=user_id or None,
        amount=amount,
        effective_from=effective_from,
        effective_to=effective_to,
        notes=notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_assignment(db: Session, assignment_id: int) -> None:
    row = db.get(PayrollAssignment, assignment_id)
    if not row:
        raise PayrollPolicyError("تخصیص یافت نشد")
    db.delete(row)
    db.commit()


def resolve_amount(
    db: Session,
    *,
    component_code: str,
    user_id: str,
    membership_type_code: Optional[str],
    on_date: date,
) -> Decimal:
    """اولویت: تخصیص فرد > تخصیص عضویت."""
    from decimal import Decimal as Dec

    comp = (
        db.query(PayrollComponent)
        .filter(
            PayrollComponent.code == component_code,
            PayrollComponent.deleted_at.is_(None),
            PayrollComponent.is_active.is_(True),
        )
        .first()
    )
    if not comp:
        return Dec("0")

    def _active(q):
        return (
            q.filter(
                PayrollAssignment.component_id == comp.id,
                PayrollAssignment.is_active.is_(True),
                PayrollAssignment.effective_from <= on_date,
            )
            .filter(
                (PayrollAssignment.effective_to.is_(None))
                | (PayrollAssignment.effective_to >= on_date)
            )
            .order_by(PayrollAssignment.effective_from.desc())
            .first()
        )

    user_row = _active(
        db.query(PayrollAssignment).filter(PayrollAssignment.user_id == user_id)
    )
    if user_row:
        return Dec(user_row.amount)

    if membership_type_code:
        mem_row = _active(
            db.query(PayrollAssignment).filter(
                PayrollAssignment.membership_type_code == membership_type_code
            )
        )
        if mem_row:
            return Decimal(mem_row.amount)

    return Decimal("0")


def list_minimum_wages(db: Session):
    from models.payroll import PayrollMinimumWage

    return (
        db.query(PayrollMinimumWage)
        .order_by(
            PayrollMinimumWage.year_j.desc(),
            PayrollMinimumWage.membership_type_code.asc().nullsfirst(),
        )
        .all()
    )


def upsert_minimum_wage(
    db: Session,
    *,
    year_j: int,
    daily_amount: Decimal,
    effective_from: date,
    source_reference: Optional[str] = None,
    membership_type_code: Optional[str] = None,
    wage_id: Optional[int] = None,
):
    from models.payroll import PayrollMinimumWage

    code = (membership_type_code or "").strip() or None
    if wage_id:
        row = db.get(PayrollMinimumWage, wage_id)
        if not row:
            raise PayrollPolicyError("حداقل مزد یافت نشد")
    else:
        query = db.query(PayrollMinimumWage).filter(PayrollMinimumWage.year_j == year_j)
        if code:
            query = query.filter(PayrollMinimumWage.membership_type_code == code)
        else:
            query = query.filter(PayrollMinimumWage.membership_type_code.is_(None))
        row = query.first()
        if row is None:
            row = PayrollMinimumWage(year_j=year_j, effective_from=effective_from)
            db.add(row)
    row.year_j = year_j
    row.membership_type_code = code
    row.daily_amount = daily_amount
    row.effective_from = effective_from
    row.source_reference = source_reference
    row.status = "active"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این سال و عضویت قبلاً حداقل مزد ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_minimum_wage(db: Session, wage_id: int) -> None:
    from models.payroll import PayrollMinimumWage

    row = db.get(PayrollMinimumWage, wage_id)
    if not row:
        raise PayrollPolicyError("حداقل مزد یافت نشد")
    db.delete(row)
    db.commit()


def list_child_policies(db: Session):
    from models.payroll import PayrollChildAllowancePolicy

    return (
        db.query(PayrollChildAllowancePolicy)
        .order_by(PayrollChildAllowancePolicy.membership_type_code)
        .all()
    )


def upsert_child_policy(
    db: Session,
    *,
    membership_type_code: str,
    applies_to_female: bool,
    age_limit_years: int,
    require_study_above_age: bool,
    wage_day_multiplier: Decimal,
    count_only_verified: bool,
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from models.payroll import PayrollChildAllowancePolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    if policy_id:
        row = db.get(PayrollChildAllowancePolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست حق اولاد یافت نشد")
    else:
        row = PayrollChildAllowancePolicy(membership_type_code=membership_type_code)
        db.add(row)
    row.membership_type_code = membership_type_code
    row.applies_to_female = applies_to_female
    row.age_limit_years = age_limit_years
    row.require_study_above_age = require_study_above_age
    row.wage_day_multiplier = wage_day_multiplier
    row.count_only_verified = count_only_verified
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    db.commit()
    db.refresh(row)
    return row


def delete_child_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollChildAllowancePolicy

    row = db.get(PayrollChildAllowancePolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست حق اولاد یافت نشد")
    db.delete(row)
    db.commit()


def list_overtime_policies(db: Session):
    from models.payroll import PayrollOvertimePolicy

    return (
        db.query(PayrollOvertimePolicy)
        .order_by(PayrollOvertimePolicy.membership_type_code)
        .all()
    )


def upsert_overtime_policy(
    db: Session,
    *,
    membership_type_code: str,
    method: str,
    basis_codes: List[str],
    divisor: Decimal,
    premium_factor: Decimal,
    ordinary_month_hours: Decimal,
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from core.payroll.overtime import OVERTIME_METHODS, parse_basis_codes
    from models.payroll import PayrollOvertimePolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    if method not in OVERTIME_METHODS:
        raise PayrollPolicyError("روش محاسبه اضافه‌کار نامعتبر است")
    if divisor <= 0 or ordinary_month_hours <= 0 or premium_factor < 0:
        raise PayrollPolicyError("عدد ثابت، ساعت عادی ماه و ضریب باید بزرگ‌تر از صفر باشند")
    codes = parse_basis_codes(",".join(basis_codes))
    if policy_id:
        row = db.get(PayrollOvertimePolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست اضافه‌کار یافت نشد")
    else:
        row = (
            db.query(PayrollOvertimePolicy)
            .filter(PayrollOvertimePolicy.membership_type_code == membership_type_code)
            .first()
        )
        if row is None:
            row = PayrollOvertimePolicy(
                membership_type_code=membership_type_code,
                effective_from=effective_from,
            )
            db.add(row)
    row.membership_type_code = membership_type_code
    row.method = method
    row.basis_codes = ",".join(codes)
    row.divisor = divisor
    row.premium_factor = premium_factor
    row.ordinary_month_hours = ordinary_month_hours
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این عضویت قبلاً سیاست اضافه‌کار ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_overtime_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollOvertimePolicy

    row = db.get(PayrollOvertimePolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست اضافه‌کار یافت نشد")
    db.delete(row)
    db.commit()


def list_deficit_policies(db: Session):
    from models.payroll import PayrollDeficitPolicy

    return (
        db.query(PayrollDeficitPolicy)
        .order_by(PayrollDeficitPolicy.membership_type_code)
        .all()
    )


def upsert_deficit_policy(
    db: Session,
    *,
    membership_type_code: str,
    basis_codes: List[str],
    ordinary_month_hours: Decimal,
    basis_days: Decimal,
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from core.payroll.overtime import parse_basis_codes
    from models.payroll import PayrollDeficitPolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    if ordinary_month_hours <= 0 or basis_days <= 0:
        raise PayrollPolicyError("ساعت عادی ماه و روز مبنا باید بزرگ‌تر از صفر باشند")
    codes = parse_basis_codes(",".join(basis_codes))
    if policy_id:
        row = db.get(PayrollDeficitPolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست کسر کار یافت نشد")
    else:
        row = (
            db.query(PayrollDeficitPolicy)
            .filter(PayrollDeficitPolicy.membership_type_code == membership_type_code)
            .first()
        )
        if row is None:
            row = PayrollDeficitPolicy(
                membership_type_code=membership_type_code,
                effective_from=effective_from,
            )
            db.add(row)
    row.membership_type_code = membership_type_code
    row.basis_codes = ",".join(codes)
    row.ordinary_month_hours = ordinary_month_hours
    row.basis_days = basis_days
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این عضویت قبلاً سیاست کسر کار ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_deficit_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollDeficitPolicy

    row = db.get(PayrollDeficitPolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست کسر کار یافت نشد")
    db.delete(row)
    db.commit()


def list_shift_policies(db: Session):
    from models.payroll import PayrollShiftPolicy

    return (
        db.query(PayrollShiftPolicy)
        .order_by(PayrollShiftPolicy.membership_type_code)
        .all()
    )


def upsert_shift_policy(
    db: Session,
    *,
    membership_type_code: str,
    basis_codes: List[str],
    pct_morning_evening: Decimal,
    pct_morning_evening_night: Decimal,
    pct_morning_night: Decimal,
    pct_evening_night: Decimal,
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from core.payroll.shift import parse_shift_basis_codes
    from models.payroll import PayrollShiftPolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    percents = (
        pct_morning_evening,
        pct_morning_evening_night,
        pct_morning_night,
        pct_evening_night,
    )
    if any(item < 0 for item in percents):
        raise PayrollPolicyError("درصد نوبت‌کاری نمی‌تواند منفی باشد")
    codes = parse_shift_basis_codes(",".join(basis_codes))
    if policy_id:
        row = db.get(PayrollShiftPolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست نوبت‌کاری یافت نشد")
    else:
        row = (
            db.query(PayrollShiftPolicy)
            .filter(PayrollShiftPolicy.membership_type_code == membership_type_code)
            .first()
        )
        if row is None:
            row = PayrollShiftPolicy(
                membership_type_code=membership_type_code,
                effective_from=effective_from,
            )
            db.add(row)
    row.membership_type_code = membership_type_code
    row.basis_codes = ",".join(codes)
    row.pct_morning_evening = pct_morning_evening
    row.pct_morning_evening_night = pct_morning_evening_night
    row.pct_morning_night = pct_morning_night
    row.pct_evening_night = pct_evening_night
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این عضویت قبلاً سیاست نوبت‌کاری ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_shift_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollShiftPolicy

    row = db.get(PayrollShiftPolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست نوبت‌کاری یافت نشد")
    db.delete(row)
    db.commit()


def list_night_policies(db: Session):
    from models.payroll import PayrollNightPolicy

    return (
        db.query(PayrollNightPolicy)
        .order_by(PayrollNightPolicy.membership_type_code)
        .all()
    )


def upsert_night_policy(
    db: Session,
    *,
    membership_type_code: str,
    premium_percent: Decimal,
    basis_codes: List[str],
    excluded_patterns: List[str],
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from core.payroll.night import parse_excluded_patterns, parse_night_basis_codes
    from models.payroll import PayrollNightPolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    if premium_percent < 0:
        raise PayrollPolicyError("درصد شب‌کاری نمی‌تواند منفی باشد")
    patterns = parse_excluded_patterns(",".join(excluded_patterns))
    codes = parse_night_basis_codes(",".join(basis_codes))
    if policy_id:
        row = db.get(PayrollNightPolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست شب‌کاری یافت نشد")
    else:
        row = (
            db.query(PayrollNightPolicy)
            .filter(PayrollNightPolicy.membership_type_code == membership_type_code)
            .first()
        )
        if row is None:
            row = PayrollNightPolicy(
                membership_type_code=membership_type_code,
                effective_from=effective_from,
            )
            db.add(row)
    row.membership_type_code = membership_type_code
    row.premium_percent = premium_percent
    row.basis_codes = ",".join(codes)
    row.excluded_patterns = ",".join(patterns)
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این عضویت قبلاً سیاست شب‌کاری ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_night_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollNightPolicy

    row = db.get(PayrollNightPolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست شب‌کاری یافت نشد")
    db.delete(row)
    db.commit()


def list_friday_policies(db: Session):
    from models.payroll import PayrollFridayPolicy

    return (
        db.query(PayrollFridayPolicy)
        .order_by(PayrollFridayPolicy.membership_type_code)
        .all()
    )


def upsert_friday_policy(
    db: Session,
    *,
    membership_type_code: str,
    premium_percent: Decimal,
    basis_codes: List[str],
    excluded_patterns: List[str],
    effective_from: date,
    effective_to: Optional[date] = None,
    notes: Optional[str] = None,
    policy_id: Optional[int] = None,
):
    from core.payroll.friday import parse_excluded_patterns, parse_friday_basis_codes
    from models.payroll import PayrollFridayPolicy

    if not membership_type_code:
        raise PayrollPolicyError("نوع عضویت الزامی است")
    if premium_percent < 0:
        raise PayrollPolicyError("درصد جمعه‌کاری نمی‌تواند منفی باشد")
    patterns = parse_excluded_patterns(",".join(excluded_patterns))
    codes = parse_friday_basis_codes(",".join(basis_codes))
    if policy_id:
        row = db.get(PayrollFridayPolicy, policy_id)
        if not row:
            raise PayrollPolicyError("سیاست جمعه‌کاری یافت نشد")
    else:
        row = (
            db.query(PayrollFridayPolicy)
            .filter(PayrollFridayPolicy.membership_type_code == membership_type_code)
            .first()
        )
        if row is None:
            row = PayrollFridayPolicy(
                membership_type_code=membership_type_code,
                effective_from=effective_from,
            )
            db.add(row)
    row.membership_type_code = membership_type_code
    row.premium_percent = premium_percent
    row.basis_codes = ",".join(codes)
    row.excluded_patterns = ",".join(patterns)
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.notes = notes
    row.is_active = True
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise PayrollPolicyError("برای این عضویت قبلاً سیاست جمعه‌کاری ثبت شده است") from exc
    db.refresh(row)
    return row


def delete_friday_policy(db: Session, policy_id: int) -> None:
    from models.payroll import PayrollFridayPolicy

    row = db.get(PayrollFridayPolicy, policy_id)
    if not row:
        raise PayrollPolicyError("سیاست جمعه‌کاری یافت نشد")
    db.delete(row)
    db.commit()


def payroll_membership_selection_codes(db: Session) -> Optional[set[str]]:
    """کدهای انتخاب‌شده برای ایجاد حقوق؛ None یعنی همهٔ عضویت‌های فعال."""
    rows = db.query(PayrollEnabledMembership.membership_type_code).all()
    if not rows:
        return None
    return {item[0] for item in rows}


def list_enabled_payroll_memberships(db: Session) -> List[MembershipType]:
    ensure_payroll_defaults(db)
    selected = payroll_membership_selection_codes(db)
    query = db.query(MembershipType).filter(MembershipType.is_active.is_(True))
    if selected is not None:
        query = query.filter(MembershipType.code.in_(selected))
    return query.order_by(MembershipType.sort_order, MembershipType.code).all()


def is_payroll_membership_allowed(db: Session, code: str) -> bool:
    if not (code or "").strip():
        return True
    code = code.strip()
    return any(mt.code == code for mt in list_enabled_payroll_memberships(db))


def payroll_membership_codes_for_employees(
    db: Session, run_membership_code: Optional[str]
) -> Optional[set[str]]:
    """کدهای عضویت واجد شرایط در محاسبه. None یعنی بدون محدودیت (همه قراردادها)."""
    if (run_membership_code or "").strip():
        return {run_membership_code.strip()}
    selected = payroll_membership_selection_codes(db)
    if selected is None:
        return None
    return selected


def save_payroll_enabled_memberships(db: Session, codes: List[str]) -> None:
    ensure_payroll_defaults(db)
    active = {
        row.code
        for row in db.query(MembershipType)
        .filter(MembershipType.is_active.is_(True))
        .all()
    }
    cleaned: List[str] = []
    for raw in codes:
        code = (raw or "").strip()
        if code in active and code not in cleaned:
            cleaned.append(code)
    db.query(PayrollEnabledMembership).delete()
    for code in cleaned:
        db.add(PayrollEnabledMembership(membership_type_code=code))
    db.commit()
