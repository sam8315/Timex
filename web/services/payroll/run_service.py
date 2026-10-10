"""ایجاد و محاسبه اجرای حقوق."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from core.payroll.calendar_utils import jalali_month_bounds, month_day_count
from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.contract_coverage import best_contract_coverage
from core.payroll.child_allowance import ChildAllowanceRule, ChildFact, resolve_minimum_daily
from core.payroll.overtime import DeficitRule, OvertimeRule, parse_basis_codes
from core.payroll.night import NightRule, parse_excluded_patterns
from core.payroll.shift import PATTERN_NONE, SHIFT_OPTIONS, ShiftRule, parse_shift_basis_codes
from core.payroll.money import D
from core.payroll.seniority import AnnualSeniorityPolicy
from models.contract import Contract
from models.employee import Employee
from models.employee_relative import EmployeeRelative
from models.payroll import (
    PayrollAnnualLaw,
    PayrollChildAllowancePolicy,
    PayrollManualEntry,
    PayrollMinimumWage,
    PayrollOvertimePolicy,
    PayrollDeficitPolicy,
    PayrollShiftPolicy,
    PayrollNightPolicy,
    PayrollShiftChoice,
    PayrollPeriod,
    PayrollResult,
    PayrollResultItem,
    PayrollRun,
)
from web.services.payroll.friday_adapter import get_attendance_hour_buckets
from web.services.payroll.policy_service import (
    get_rate_settings,
    list_components,
    payroll_membership_codes_for_employees,
    resolve_amount,
)
from web.services.payroll.seed import ensure_payroll_defaults


class PayrollRunError(Exception):
    pass


EDITABLE_STATUSES = ("draft", "calculated")


def get_or_create_period(db: Session, year_j: int, month_j: int) -> PayrollPeriod:
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.year_j == year_j, PayrollPeriod.month_j == month_j)
        .first()
    )
    if period:
        return period
    period = PayrollPeriod(year_j=year_j, month_j=month_j)
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def list_runs(db: Session) -> List[PayrollRun]:
    return (
        db.query(PayrollRun)
        .options(joinedload(PayrollRun.period), joinedload(PayrollRun.results))
        .order_by(PayrollRun.id.desc())
        .all()
    )


def get_run(db: Session, run_id: int) -> PayrollRun:
    ensure_payroll_defaults(db)
    run = (
        db.query(PayrollRun)
        .options(
            joinedload(PayrollRun.period),
            joinedload(PayrollRun.results).joinedload(PayrollResult.items),
            joinedload(PayrollRun.manual_entries),
            joinedload(PayrollRun.shift_choices),
        )
        .filter(PayrollRun.id == run_id)
        .first()
    )
    if not run:
        raise PayrollRunError("اجرای حقوق یافت نشد")
    return run


def create_run(
    db: Session,
    *,
    year_j: int,
    month_j: int,
    membership_type_code: Optional[str],
    created_by: Optional[str],
    notes: Optional[str] = None,
    component_codes: Optional[List[str]] = None,
    calculate: bool = True,
) -> PayrollRun:
    ensure_payroll_defaults(db)
    if not (1 <= month_j <= 12):
        raise PayrollRunError("ماه نامعتبر است")
    period = get_or_create_period(db, year_j, month_j)
    run = PayrollRun(
        period_id=period.id,
        membership_type_code=membership_type_code or None,
        status="draft",
        created_by=created_by,
        notes=notes,
        component_codes=_normalize_component_codes(db, component_codes),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    if calculate:
        return calculate_run(db, run.id)
    return get_run(db, run.id)


def _active_annual_laws(db: Session) -> List[AnnualSeniorityPolicy]:
    rows = (
        db.query(PayrollAnnualLaw)
        .filter(PayrollAnnualLaw.status == "active")
        .order_by(PayrollAnnualLaw.year_j, PayrollAnnualLaw.id)
        .all()
    )
    # هر سال: نسخه official اولویت دارد، در غیر این صورت آخرین رکورد
    by_year = {}
    for r in rows:
        prev = by_year.get(r.year_j)
        if prev is None or r.version == "official":
            by_year[r.year_j] = AnnualSeniorityPolicy(
                year_j=r.year_j,
                new_seniority_daily=D(r.new_seniority_daily),
                wage_increase_factor=D(r.wage_increase_factor),
            )
    return list(by_year.values())


def _normalize_component_codes(db: Session, codes: Optional[List[str]]) -> Optional[str]:
    if codes is None:
        return None
    allowed = {
        comp.code
        for comp in list_components(db)
        if comp.is_active and not comp.deleted_at
    }
    chosen = []
    for code in codes:
        code = (code or "").strip()
        if not code:
            continue
        if code not in allowed:
            raise PayrollRunError("آیتم انتخاب‌شده در سیاست حقوق نیست")
        if code not in chosen:
            chosen.append(code)
    if not chosen:
        raise PayrollRunError("حداقل یک آیتم برای محاسبه انتخاب کنید")
    return ",".join(chosen)


def selected_component_codes(run: PayrollRun) -> Optional[set[str]]:
    """None یعنی اجرای قدیمی: همه آیتم‌های فعال."""
    raw = (run.component_codes or "").strip()
    if not raw:
        return None
    return {code.strip() for code in raw.split(",") if code.strip()}


def _component_defs(db: Session, selected: Optional[set[str]] = None) -> List[ComponentDef]:
    comps = [c for c in list_components(db) if c.is_active and not c.deleted_at]
    return [
        ComponentDef(
            id=c.id,
            code=c.code,
            name=c.name,
            kind=c.kind,
            calc_mode=c.calc_mode,
            subject_to_insurance=c.subject_to_insurance,
            subject_to_tax=c.subject_to_tax,
            sort_order=c.sort_order,
        )
        for c in comps
        if selected is None or c.code in selected
    ]


def _eligible_employees(
    db: Session,
    month_start: date,
    month_end: date,
    membership_type_code: Optional[str],
    allowed_membership_codes: Optional[set[str]] = None,
) -> List[tuple[Employee, Contract, int]]:
    q = db.query(Contract).filter(Contract.start_date <= month_end)
    if membership_type_code:
        q = q.filter(Contract.contract_type_code == membership_type_code)
    elif allowed_membership_codes is not None:
        if not allowed_membership_codes:
            return []
        q = q.filter(Contract.contract_type_code.in_(allowed_membership_codes))
    contracts = q.all()

    # گروه‌بندی بر اساس user
    by_user: dict[str, list] = {}
    for c in contracts:
        end = c.actual_end_date
        if end is not None and end < month_start:
            continue
        by_user.setdefault(c.user_id, []).append(c)

    employees_by_id = {
        row.user_id: row
        for row in db.query(Employee).filter(Employee.user_id.in_(by_user.keys())).all()
    } if by_user else {}

    out = []
    for user_id, user_contracts in by_user.items():
        emp = employees_by_id.get(user_id)
        if not emp or not emp.is_active:
            continue
        covered, best = best_contract_coverage(month_start, month_end, user_contracts)
        if covered <= 0 or best is None:
            continue
        out.append((emp, best, covered))
    out.sort(key=lambda t: (t[0].last_name or "", t[0].first_name or ""))
    return out


def shift_roster(db: Session, run: PayrollRun) -> list[dict]:
    """افراد قابل محاسبه، با نوع نوبت ذخیره‌شده. پیش از اولین محاسبه هم پر است."""
    period = run.period
    month_start, month_end = jalali_month_bounds(period.year_j, period.month_j)
    month_days = month_day_count(period.year_j, period.month_j)
    choices = {row.user_id: row.pattern for row in run.shift_choices}
    results = {row.user_id: row for row in run.results}
    rows = []
    seen = set()
    allowed_codes = payroll_membership_codes_for_employees(db, run.membership_type_code)
    for emp, contract, covered in _eligible_employees(
        db,
        month_start,
        month_end,
        run.membership_type_code,
        allowed_membership_codes=allowed_codes,
    ):
        seen.add(emp.user_id)
        result = results.get(emp.user_id)
        rows.append(
            {
                "user_id": emp.user_id,
                "name": emp.full_name,
                "membership": contract.contract_type_code,
                "covered_days": result.covered_days if result else covered,
                "month_days": result.month_days if result else month_days,
                "gross": result.gross_earnings if result else None,
                "deductions": result.total_deductions if result else None,
                "net": result.net_pay if result else None,
                "result_id": result.id if result else None,
                "pattern": choices.get(emp.user_id, PATTERN_NONE),
            }
        )
    for result in run.results:
        if result.user_id in seen:
            continue
        rows.append(
            {
                "user_id": result.user_id,
                "name": result.employee_name,
                "membership": result.membership_type_code,
                "covered_days": result.covered_days,
                "month_days": result.month_days,
                "gross": result.gross_earnings,
                "deductions": result.total_deductions,
                "net": result.net_pay,
                "result_id": result.id,
                "pattern": choices.get(result.user_id, PATTERN_NONE),
            }
        )
    return rows


def set_shift_choices(db: Session, run_id: int, choices: list[tuple[str, str]]) -> None:
    run = get_run(db, run_id)
    if run.status not in EDITABLE_STATUSES:
        raise PayrollRunError("فقط در پیش‌نویس یا محاسبه‌شده می‌توان نوع نوبت را تغییر داد")
    allowed = {code for code, _label in SHIFT_OPTIONS}
    existing = {row.user_id: row for row in run.shift_choices}
    for user_id, pattern in choices:
        user_id = (user_id or "").strip()
        if not user_id:
            continue
        if pattern not in allowed:
            raise PayrollRunError("نوع نوبت نامعتبر است")
        row = existing.get(user_id)
        if row is None:
            row = PayrollShiftChoice(run_id=run_id, user_id=user_id, pattern=pattern)
            db.add(row)
            existing[user_id] = row
        else:
            row.pattern = pattern
    db.commit()


def _minimum_daily_wage(db: Session, year_j: int, membership_code: Optional[str]) -> Decimal:
    rows = (
        db.query(PayrollMinimumWage)
        .filter(
            PayrollMinimumWage.year_j == year_j,
            PayrollMinimumWage.status == "active",
        )
        .all()
    )
    return resolve_minimum_daily(
        [(row.membership_type_code, D(row.daily_amount)) for row in rows],
        membership_code,
    )


def _deficit_rule(db: Session, membership_code: Optional[str], on_date: date):
    if not membership_code:
        return None
    row = (
        db.query(PayrollDeficitPolicy)
        .filter(
            PayrollDeficitPolicy.membership_type_code == membership_code,
            PayrollDeficitPolicy.is_active.is_(True),
            PayrollDeficitPolicy.effective_from <= on_date,
        )
        .filter(
            (PayrollDeficitPolicy.effective_to.is_(None))
            | (PayrollDeficitPolicy.effective_to >= on_date)
        )
        .order_by(PayrollDeficitPolicy.effective_from.desc())
        .first()
    )
    if row is None:
        return None
    return DeficitRule(
        basis_codes=parse_basis_codes(row.basis_codes),
        ordinary_month_hours=D(row.ordinary_month_hours),
        basis_days=D(row.basis_days),
    )


def _overtime_rule(db: Session, membership_code: Optional[str], on_date: date):
    if not membership_code:
        return None
    row = (
        db.query(PayrollOvertimePolicy)
        .filter(
            PayrollOvertimePolicy.membership_type_code == membership_code,
            PayrollOvertimePolicy.is_active.is_(True),
            PayrollOvertimePolicy.effective_from <= on_date,
        )
        .filter(
            (PayrollOvertimePolicy.effective_to.is_(None))
            | (PayrollOvertimePolicy.effective_to >= on_date)
        )
        .order_by(PayrollOvertimePolicy.effective_from.desc())
        .first()
    )
    if row is None:
        return None
    return OvertimeRule(
        method=row.method,
        basis_codes=parse_basis_codes(row.basis_codes),
        divisor=D(row.divisor),
        premium_factor=D(row.premium_factor),
        ordinary_month_hours=D(row.ordinary_month_hours),
    )


def _shift_rule(db: Session, membership_code: Optional[str], on_date: date):
    if not membership_code:
        return None
    row = (
        db.query(PayrollShiftPolicy)
        .filter(
            PayrollShiftPolicy.membership_type_code == membership_code,
            PayrollShiftPolicy.is_active.is_(True),
            PayrollShiftPolicy.effective_from <= on_date,
        )
        .filter(
            (PayrollShiftPolicy.effective_to.is_(None))
            | (PayrollShiftPolicy.effective_to >= on_date)
        )
        .order_by(PayrollShiftPolicy.effective_from.desc())
        .first()
    )
    if row is None:
        return None
    return ShiftRule(
        basis_codes=parse_shift_basis_codes(row.basis_codes),
        pct_morning_evening=D(row.pct_morning_evening),
        pct_morning_evening_night=D(row.pct_morning_evening_night),
        pct_morning_night=D(row.pct_morning_night),
        pct_evening_night=D(row.pct_evening_night),
    )


class _RunPolicyCache:
    """قوانین عضویت یک‌بار در هر اجرای محاسبه؛ از N×۴ کوئری تکراری جلوگیری می‌کند."""

    __slots__ = ("_db", "_on_date", "_ot", "_deficit", "_shift", "_night", "_child")

    def __init__(self, db: Session, on_date: date) -> None:
        self._db = db
        self._on_date = on_date
        self._ot: dict[Optional[str], object] = {}
        self._deficit: dict[Optional[str], object] = {}
        self._shift: dict[Optional[str], object] = {}
        self._night: dict[Optional[str], object] = {}
        self._child: dict[Optional[str], object] = {}

    def overtime(self, membership_code: Optional[str]):
        key = membership_code or ""
        if key not in self._ot:
            self._ot[key] = _overtime_rule(self._db, membership_code, self._on_date)
        return self._ot[key]

    def deficit(self, membership_code: Optional[str]):
        key = membership_code or ""
        if key not in self._deficit:
            self._deficit[key] = _deficit_rule(self._db, membership_code, self._on_date)
        return self._deficit[key]

    def shift(self, membership_code: Optional[str]):
        key = membership_code or ""
        if key not in self._shift:
            self._shift[key] = _shift_rule(self._db, membership_code, self._on_date)
        return self._shift[key]

    def night(self, membership_code: Optional[str]):
        key = membership_code or ""
        if key not in self._night:
            self._night[key] = _night_rule(self._db, membership_code, self._on_date)
        return self._night[key]

    def child(self, membership_code: Optional[str]):
        key = membership_code or ""
        if key not in self._child:
            self._child[key] = _child_rule(self._db, membership_code, self._on_date)
        return self._child[key]


def _night_rule(db: Session, membership_code: Optional[str], on_date: date):
    if not membership_code:
        return None
    row = (
        db.query(PayrollNightPolicy)
        .filter(
            PayrollNightPolicy.membership_type_code == membership_code,
            PayrollNightPolicy.is_active.is_(True),
            PayrollNightPolicy.effective_from <= on_date,
        )
        .filter(
            (PayrollNightPolicy.effective_to.is_(None))
            | (PayrollNightPolicy.effective_to >= on_date)
        )
        .order_by(PayrollNightPolicy.effective_from.desc())
        .first()
    )
    if row is None:
        return None
    return NightRule(
        premium_percent=D(row.premium_percent),
        excluded_patterns=parse_excluded_patterns(row.excluded_patterns),
    )


def _child_rule(db: Session, membership_code: Optional[str], on_date: date):
    if not membership_code:
        return None
    row = (
        db.query(PayrollChildAllowancePolicy)
        .filter(
            PayrollChildAllowancePolicy.membership_type_code == membership_code,
            PayrollChildAllowancePolicy.is_active.is_(True),
            PayrollChildAllowancePolicy.effective_from <= on_date,
        )
        .filter(
            (PayrollChildAllowancePolicy.effective_to.is_(None))
            | (PayrollChildAllowancePolicy.effective_to >= on_date)
        )
        .order_by(PayrollChildAllowancePolicy.effective_from.desc())
        .first()
    )
    if row is None:
        return None
    return ChildAllowanceRule(
        applies_to_female=bool(row.applies_to_female),
        age_limit_years=int(row.age_limit_years),
        require_study_above_age=bool(row.require_study_above_age),
        wage_day_multiplier=D(row.wage_day_multiplier),
        count_only_verified=bool(row.count_only_verified),
    )


def _children_of(db: Session, user_id: str) -> List[ChildFact]:
    rows = (
        db.query(EmployeeRelative)
        .filter(
            EmployeeRelative.user_id == user_id,
            EmployeeRelative.relationship_type == "CHILD",
            EmployeeRelative.deleted_at.is_(None),
        )
        .all()
    )
    return [
        ChildFact(
            birth_date=r.birth_date,
            death_date=r.death_date,
            is_studying=r.is_studying,
            study_start_date=r.study_start_date,
            study_end_date=r.study_end_date,
            status=r.status or "",
        )
        for r in rows
    ]


def calculate_run(db: Session, run_id: int) -> PayrollRun:
    for event in iter_calculate(db, run_id):
        if event.get("error"):
            raise PayrollRunError(event["error"])
    return get_run(db, run_id)


def iter_calculate(db: Session, run_id: int):
    """محاسبه نفر به نفر و گزارش درصد پیشرفت."""
    run = get_run(db, run_id)
    if run.status not in EDITABLE_STATUSES and run.status != "draft":
        if run.status in ("approved", "published"):
            yield {
                "done": True,
                "error": "اجرای تأیید/منتشرشده قابل محاسبه مجدد نیست",
                "percent": 0,
                "name": "",
                "user_id": "",
                "index": 0,
                "total": 0,
            }
            return
    yield {
        "index": 0,
        "total": 0,
        "percent": 0,
        "name": "آماده‌سازی…",
        "user_id": "",
        "done": False,
    }
    period = run.period
    month_start, month_end = jalali_month_bounds(period.year_j, period.month_j)
    month_days = month_day_count(period.year_j, period.month_j)
    rates_row = get_rate_settings(db)
    rates = RateSettingsInput(
        insurance_employee_pct=D(rates_row.insurance_employee_pct),
        tax_pct=D(rates_row.tax_pct),
        friday_coefficient=D(rates_row.friday_coefficient),
        eidi_payment_month=int(rates_row.eidi_payment_month),
        bonus_payment_month=int(rates_row.bonus_payment_month),
        eidi_day_factor=D(rates_row.eidi_day_factor),
        bonus_day_factor=D(rates_row.bonus_day_factor),
        hours_per_day=D(rates_row.hours_per_day),
    )
    components = _component_defs(db, selected_component_codes(run))
    annual = _active_annual_laws(db)
    payroll_date = month_end

    manual_map: dict[tuple[str, str], Decimal] = {}
    for m in run.manual_entries:
        manual_map[(m.user_id, m.component_code)] = D(m.amount)
    choices = {row.user_id: row.pattern for row in run.shift_choices}

    # پاک کردن نتایج قبلی
    for old in list(run.results):
        db.delete(old)
    db.flush()

    earn_codes = [c.code for c in components if c.kind == "earning"]
    allowed_codes = payroll_membership_codes_for_employees(db, run.membership_type_code)
    employees = _eligible_employees(
        db,
        month_start,
        month_end,
        run.membership_type_code,
        allowed_membership_codes=allowed_codes,
    )
    total = len(employees)
    policy_cache = _RunPolicyCache(db, payroll_date)
    min_wage_cache: dict[Optional[str], Decimal] = {}

    for index, (emp, contract, covered) in enumerate(employees, start=1):
        yield {
            "index": index,
            "total": total,
            "percent": int((index - 1) * 100 / total) if total else 100,
            "name": emp.full_name or "",
            "user_id": emp.user_id,
            "done": False,
        }
        amounts = {}
        for code in earn_codes:
            amounts[code] = resolve_amount(
                db,
                component_code=code,
                user_id=emp.user_id,
                membership_type_code=contract.contract_type_code,
                on_date=payroll_date,
            )
        manuals = {
            code: amt
            for (uid, code), amt in manual_map.items()
            if uid == emp.user_id
        }
        friday_hours, overtime_hours, holiday_hours, deficit_hours, morning_hours, evening_hours, night_hours = (
            get_attendance_hour_buckets(db, emp.user_id, period.year_j, period.month_j)
        )
        draft = calculate_employee_payslip(
            EmployeeCalcInput(
                user_id=emp.user_id,
                employee_name=emp.full_name,
                membership_type_code=contract.contract_type_code,
                hire_date=emp.hire_date,
                marital_status=emp.marital_status,
                gender=emp.gender,
                covered_days=covered,
                month_days=month_days,
                year_j=period.year_j,
                month_j=period.month_j,
                payroll_date=payroll_date,
                amounts=amounts,
                manual_amounts=manuals,
                friday_hours=friday_hours,
                overtime_hours=overtime_hours,
                holiday_hours=holiday_hours,
                deficit_hours=deficit_hours,
                morning_hours=morning_hours,
                evening_hours=evening_hours,
                night_hours=night_hours,
                shift_pattern=choices.get(emp.user_id, PATTERN_NONE),
                overtime_rule=policy_cache.overtime(contract.contract_type_code),
                deficit_rule=policy_cache.deficit(contract.contract_type_code),
                shift_rule=policy_cache.shift(contract.contract_type_code),
                night_rule=policy_cache.night(contract.contract_type_code),
                children=_children_of(db, emp.user_id),
                child_rule=policy_cache.child(contract.contract_type_code),
                minimum_daily_wage=min_wage_cache.setdefault(
                    contract.contract_type_code,
                    _minimum_daily_wage(db, period.year_j, contract.contract_type_code),
                ),
            ),
            components,
            rates,
            annual,
        )
        result = PayrollResult(
            run_id=run.id,
            user_id=draft.user_id,
            employee_name=draft.employee_name,
            membership_type_code=draft.membership_type_code,
            covered_days=draft.covered_days,
            month_days=draft.month_days,
            gross_earnings=draft.gross_earnings,
            total_deductions=draft.total_deductions,
            net_pay=draft.net_pay,
        )
        db.add(result)
        db.flush()
        for ln in draft.items:
            db.add(
                PayrollResultItem(
                    result_id=result.id,
                    component_id=ln.component_id,
                    component_code=ln.component_code,
                    component_name=ln.component_name,
                    kind=ln.kind,
                    amount=ln.amount,
                    quantity=ln.quantity,
                    unit_amount=ln.unit_amount,
                    calc_note=ln.calc_note,
                    subject_to_insurance=ln.subject_to_insurance,
                    subject_to_tax=ln.subject_to_tax,
                    sort_order=ln.sort_order,
                )
            )
        db.commit()

    db.refresh(run)
    run.status = "calculated"
    run.calculated_at = datetime.now(timezone.utc)
    db.commit()
    yield {
        "index": total,
        "total": total,
        "percent": 100,
        "name": "",
        "user_id": "",
        "done": True,
    }


def set_manual_entry(
    db: Session,
    run_id: int,
    user_id: str,
    amount: Decimal,
    *,
    component_code: str = "SHIFT",
    note: Optional[str] = None,
) -> PayrollManualEntry:
    run = get_run(db, run_id)
    if run.status not in EDITABLE_STATUSES:
        raise PayrollRunError("فقط در پیش‌نویس/محاسبه‌شده قابل ویرایش است")
    row = (
        db.query(PayrollManualEntry)
        .filter(
            PayrollManualEntry.run_id == run_id,
            PayrollManualEntry.user_id == user_id,
            PayrollManualEntry.component_code == component_code,
        )
        .first()
    )
    if row is None:
        row = PayrollManualEntry(
            run_id=run_id,
            user_id=user_id,
            component_code=component_code,
        )
        db.add(row)
    row.amount = amount
    row.note = note
    db.commit()
    db.refresh(row)
    return row


def delete_run(db: Session, run_id: int) -> None:
    run = get_run(db, run_id)
    db.delete(run)
    db.commit()


def approve_run(db: Session, run_id: int, user_id: str) -> PayrollRun:
    run = get_run(db, run_id)
    if run.status != "calculated":
        raise PayrollRunError("فقط اجرای محاسبه‌شده قابل تأیید است")
    run.status = "approved"
    run.approved_at = datetime.now(timezone.utc)
    run.approved_by = user_id
    db.commit()
    return get_run(db, run_id)


def publish_run(db: Session, run_id: int, user_id: str) -> PayrollRun:
    run = get_run(db, run_id)
    if run.status != "approved":
        raise PayrollRunError("فقط اجرای تأییدشده قابل انتشار است")
    run.status = "published"
    run.published_at = datetime.now(timezone.utc)
    run.published_by = user_id
    db.commit()
    return get_run(db, run_id)


def get_published_result_for_user(
    db: Session, user_id: str, year_j: int, month_j: int
) -> Optional[PayrollResult]:
    return (
        db.query(PayrollResult)
        .join(PayrollRun)
        .join(PayrollPeriod)
        .filter(
            PayrollResult.user_id == user_id,
            PayrollRun.status == "published",
            PayrollPeriod.year_j == year_j,
            PayrollPeriod.month_j == month_j,
        )
        .options(joinedload(PayrollResult.items), joinedload(PayrollResult.run))
        .order_by(PayrollRun.id.desc())
        .first()
    )


def get_result(db: Session, result_id: int) -> PayrollResult:
    result = (
        db.query(PayrollResult)
        .options(
            joinedload(PayrollResult.items),
            joinedload(PayrollResult.run).joinedload(PayrollRun.period),
        )
        .filter(PayrollResult.id == result_id)
        .first()
    )
    if not result:
        raise PayrollRunError("فیش یافت نشد")
    return result
