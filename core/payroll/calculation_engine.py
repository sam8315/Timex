"""موتور محاسبه فیش یک کارمند برای یک ماه."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence

from core.payroll.money import D, money_round
from core.payroll.contract_coverage import coverage_ratio
from core.payroll.child_allowance import (
    ChildAllowanceRule,
    ChildFact,
    child_allowance_monthly,
    count_eligible_children,
)
from core.payroll.overtime import (
    DeficitRule,
    OvertimeRule,
    ordinary_hour_pay,
    overtime_basis_amount,
    overtime_pay,
)
from core.payroll.friday import FridayRule, friday_hourly, friday_pay
from core.payroll.night import NightRule, night_premium
from core.payroll.shift import (
    PATTERN_LABELS,
    PATTERN_NONE,
    ShiftRule,
    detect_shift_pattern,
    shift_pay,
)
from core.payroll.seniority import (
    AnnualSeniorityPolicy,
    calculate_accumulated_seniority_daily,
)


@dataclass(frozen=True)
class ComponentDef:
    id: Optional[int]
    code: str
    name: str
    kind: str
    calc_mode: str
    subject_to_insurance: bool
    subject_to_tax: bool
    sort_order: int = 100


@dataclass(frozen=True)
class RateSettingsInput:
    insurance_employee_pct: Decimal = D("7")
    tax_pct: Decimal = D("0")
    friday_coefficient: Decimal = D("1.96")
    eidi_payment_month: int = 12
    bonus_payment_month: int = 12
    eidi_day_factor: Decimal = D("60")
    bonus_day_factor: Decimal = D("0")
    hours_per_day: Decimal = D("7.3333")


@dataclass
class EmployeeCalcInput:
    user_id: str
    employee_name: str
    membership_type_code: Optional[str]
    hire_date: Optional[date]
    marital_status: Optional[str]
    covered_days: int
    month_days: int
    year_j: int
    month_j: int
    payroll_date: date
    # component_code -> assigned amount (daily wage, monthly housing, friday hourly override, ...)
    amounts: Mapping[str, Decimal] = field(default_factory=dict)
    manual_amounts: Mapping[str, Decimal] = field(default_factory=dict)
    friday_hours: Decimal = D(0)
    gender: Optional[str] = None
    children: Sequence[ChildFact] = field(default_factory=tuple)
    child_rule: Optional[ChildAllowanceRule] = None
    minimum_daily_wage: Decimal = D(0)
    deficit_hours: Decimal = D(0)
    overtime_hours: Decimal = D(0)
    holiday_hours: Decimal = D(0)
    overtime_rule: Optional[OvertimeRule] = None
    deficit_rule: Optional[DeficitRule] = None
    morning_hours: Decimal = D(0)
    evening_hours: Decimal = D(0)
    night_hours: Decimal = D(0)
    shift_rule: Optional[ShiftRule] = None
    shift_pattern: Optional[str] = None
    night_rule: Optional[NightRule] = None
    friday_rule: Optional[FridayRule] = None


@dataclass
class LineItem:
    component_id: Optional[int]
    component_code: str
    component_name: str
    kind: str
    amount: Decimal
    quantity: Optional[Decimal] = None
    unit_amount: Optional[Decimal] = None
    calc_note: str = ""
    subject_to_insurance: bool = False
    subject_to_tax: bool = False
    sort_order: int = 100


@dataclass
class PayslipDraft:
    user_id: str
    employee_name: str
    membership_type_code: Optional[str]
    covered_days: int
    month_days: int
    items: List[LineItem]
    gross_earnings: Decimal
    total_deductions: Decimal
    net_pay: Decimal


def _policy_basis(
    components: Sequence[ComponentDef],
    lines: List[LineItem],
    rule: OvertimeRule | DeficitRule,
    fixed_days: Decimal | None = None,
) -> Decimal:
    codes = set(rule.basis_codes)
    modes = {c.code: c.calc_mode for c in components}
    method = getattr(rule, "method", "")
    return sum(
        (
            overtime_basis_amount(
                method,
                modes.get(ln.component_code, ""),
                ln.amount,
                ln.unit_amount,
                fixed_days,
            )
            for ln in lines
            if ln.kind == "earning" and ln.component_code in codes
        ),
        D(0),
    )


def _append_overtime_lines(
    emp: EmployeeCalcInput,
    components: Sequence[ComponentDef],
    lines: List[LineItem],
) -> None:
    rule = emp.overtime_rule
    for comp in sorted(components, key=lambda c: c.sort_order):
        if comp.kind != "earning" or comp.calc_mode not in ("overtime_policy", "holiday_work"):
            continue
        if rule is None:
            lines.append(
                LineItem(
                    component_id=comp.id,
                    component_code=comp.code,
                    component_name=comp.name,
                    kind="earning",
                    amount=D(0),
                    quantity=D(0),
                    calc_note="سیاست اضافه‌کار برای این عضویت نیست",
                    subject_to_insurance=comp.subject_to_insurance,
                    subject_to_tax=comp.subject_to_tax,
                    sort_order=comp.sort_order,
                )
            )
            continue
        hours = emp.holiday_hours if comp.calc_mode == "holiday_work" else emp.overtime_hours
        basis = _policy_basis(components, lines, rule)
        amount, rate, note = overtime_pay(basis, hours, rule)
        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="earning",
                amount=amount,
                quantity=D(hours),
                unit_amount=rate,
                calc_note=note,
                subject_to_insurance=comp.subject_to_insurance,
                subject_to_tax=comp.subject_to_tax,
                sort_order=comp.sort_order,
            )
        )


def _append_shift_line(
    emp: EmployeeCalcInput,
    components: Sequence[ComponentDef],
    lines: List[LineItem],
) -> None:
    comps = [
        comp for comp in components
        if comp.kind == "earning" and comp.calc_mode == "shift_policy"
    ]
    if not comps:
        return
    rule = emp.shift_rule
    amount = D(0)
    percent = D(0)
    basis = D(0)
    label = "بدون نوبت‌کاری"
    pattern = emp.shift_pattern
    if rule is None or not rule.basis_codes:
        label = "سیاست نوبت‌کاری برای این عضویت نیست"
    elif pattern != PATTERN_NONE:
        pattern = pattern or detect_shift_pattern(
            emp.morning_hours, emp.evening_hours, emp.night_hours
        )
        if pattern and pattern != PATTERN_NONE:
            percent = rule.percent_for(pattern)
            codes = set(rule.basis_codes)
            basis = sum(
                (ln.amount for ln in lines if ln.kind == "earning" and ln.component_code in codes),
                D(0),
            )
            amount = shift_pay(basis, percent)
            label = PATTERN_LABELS.get(pattern, "نوبت‌کاری")
    for comp in comps:
        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="earning",
                amount=amount,
                quantity=percent if percent else None,
                unit_amount=basis if basis else None,
                calc_note=label,
                subject_to_insurance=comp.subject_to_insurance,
                subject_to_tax=comp.subject_to_tax,
                sort_order=comp.sort_order,
            )
        )


def _append_night_line(
    emp: EmployeeCalcInput,
    components: Sequence[ComponentDef],
    lines: List[LineItem],
    rates: RateSettingsInput,
) -> None:
    comps = [
        comp for comp in components
        if comp.kind == "earning" and comp.calc_mode == "night_work"
    ]
    if not comps:
        return
    rule = emp.night_rule
    hours = D(emp.night_hours)
    pattern = emp.shift_pattern or PATTERN_NONE
    hours_per_day = D(rates.hours_per_day) or D("7.3333")
    note = "سیاست شب‌کاری برای این عضویت نیست"
    hourly = D(0)
    amount = D(0)
    if rule is not None and pattern in rule.excluded_patterns:
        note = "نوبت‌کار — بدون فوق‌العاده شب‌کاری"
    elif rule is not None and not rule.basis_codes:
        note = "هیچ آیتمی در مبنای شب‌کاری انتخاب نشده"
    elif rule is not None and hours <= 0:
        override = _amt(emp, "NIGHT_WORK")
        hourly = override if override > 0 else friday_hourly(
            components, lines, rule.basis_codes, hours_per_day
        )
        note = "ساعت شب صفر"
    elif rule is not None:
        override = _amt(emp, "NIGHT_WORK")
        hourly = override if override > 0 else friday_hourly(
            components, lines, rule.basis_codes, hours_per_day
        )
        amount = night_premium(hourly, hours, rule.premium_percent)
        note = str(rule.premium_percent)
    for comp in comps:
        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="earning",
                amount=money_round(amount),
                quantity=hours,
                unit_amount=hourly,
                calc_note=note,
                subject_to_insurance=comp.subject_to_insurance,
                subject_to_tax=comp.subject_to_tax,
                sort_order=comp.sort_order,
            )
        )


def _append_friday_line(
    emp: EmployeeCalcInput,
    components: Sequence[ComponentDef],
    lines: List[LineItem],
    rates: RateSettingsInput,
) -> None:
    comps = [
        comp for comp in components
        if comp.kind == "earning" and comp.calc_mode == "friday_attendance"
    ]
    if not comps:
        return
    rule = emp.friday_rule
    hours = D(emp.friday_hours)
    pattern = emp.shift_pattern or PATTERN_NONE
    hours_per_day = D(rates.hours_per_day) or D("7.3333")
    note = "سیاست جمعه‌کاری برای این عضویت نیست"
    hourly = D(0)
    amount = D(0)
    if rule is not None and pattern in rule.excluded_patterns:
        note = "نوبت‌کار — بدون فوق‌العاده جمعه‌کاری"
    elif rule is not None and not rule.basis_codes:
        note = "هیچ آیتمی در مبنای جمعه‌کاری انتخاب نشده"
    elif rule is not None and hours <= 0:
        hourly = friday_hourly(components, lines, rule.basis_codes, hours_per_day)
        note = "ساعت جمعه صفر"
    elif rule is not None:
        hourly = friday_hourly(components, lines, rule.basis_codes, hours_per_day)
        amount = friday_pay(hourly, hours, rule.premium_percent)
        note = str(rule.premium_percent)
    for comp in comps:
        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="earning",
                amount=money_round(amount),
                quantity=hours,
                unit_amount=hourly,
                calc_note=note,
                subject_to_insurance=comp.subject_to_insurance,
                subject_to_tax=comp.subject_to_tax,
                sort_order=comp.sort_order,
            )
        )


def _ratio(emp: EmployeeCalcInput) -> Decimal:
    return coverage_ratio(emp.covered_days, emp.month_days)


def _amt(emp: EmployeeCalcInput, code: str, default: Decimal = D(0)) -> Decimal:
    return D(emp.amounts.get(code, default))


def calculate_employee_payslip(
    emp: EmployeeCalcInput,
    components: Sequence[ComponentDef],
    rates: RateSettingsInput,
    annual_seniority: Sequence[AnnualSeniorityPolicy] | Mapping[int, AnnualSeniorityPolicy],
) -> PayslipDraft:
    ratio = _ratio(emp)
    lines: List[LineItem] = []

    daily_wage = _amt(emp, "DAILY_WAGE")

    for comp in sorted(components, key=lambda c: c.sort_order):
        if comp.kind != "earning" or comp.calc_mode in (
            "overtime_policy",
            "holiday_work",
            "shift_policy",
            "friday_attendance",
            "night_work",
        ):
            continue
        amount = D(0)
        qty = None
        unit = None
        note = ""

        if comp.calc_mode == "daily_x_covered":
            unit = daily_wage if comp.code == "DAILY_WAGE" else _amt(emp, comp.code)
            qty = D(emp.covered_days)
            amount = unit * qty
            note = f"{unit} × {emp.covered_days} روز پوشش"

        elif comp.calc_mode == "fixed_monthly_prorata":
            monthly = _amt(emp, comp.code)
            if comp.code == "MARRIAGE" and (emp.marital_status or "").upper() != "M":
                amount = D(0)
                note = "مجرد — بدون حق تأهل"
            else:
                amount = monthly * ratio
                note = f"{monthly} × نسبت {ratio}"
                qty = ratio
                unit = monthly

        elif comp.calc_mode == "seniority_chain":
            daily_s = calculate_accumulated_seniority_daily(
                emp.hire_date, emp.payroll_date, annual_seniority, final_round=True
            )
            unit = daily_s
            qty = D(emp.month_days)
            amount = daily_s * qty * ratio
            note = f"{daily_s} × {emp.month_days} روز × نسبت {ratio}"

        elif comp.calc_mode == "manual":
            amount = D(emp.manual_amounts.get(comp.code, 0))
            note = "ورود دستی"

        elif comp.calc_mode == "policy_eidi":
            if emp.month_j == int(rates.eidi_payment_month) and daily_wage > 0:
                factor = D(rates.eidi_day_factor)
                amount = daily_wage * factor * ratio
                qty = factor
                unit = daily_wage
                note = f"{daily_wage} × {factor} روز × نسبت {ratio}"
            else:
                note = "خارج از ماه پرداخت عیدی"

        elif comp.calc_mode == "child_allowance":
            rule = emp.child_rule
            if rule is None:
                note = "سیاست حق اولاد برای این عضویت نیست"
                amount = D(0)
            elif (emp.gender or "").upper() == "F" and not rule.applies_to_female:
                note = "طبق سیاست این عضویت، حق اولاد شامل کارکنان زن نمی‌شود"
            else:
                eligible = count_eligible_children(emp.children, emp.payroll_date, rule)
                per_child = D(emp.minimum_daily_wage) * D(rule.wage_day_multiplier)
                amount = child_allowance_monthly(
                    eligible,
                    emp.minimum_daily_wage,
                    rule.wage_day_multiplier,
                    ratio,
                )
                qty = D(eligible)
                unit = per_child
                if D(emp.minimum_daily_wage) <= 0:
                    amount = D(0)
                    note = "حداقل مزد روزانه این سال در سیاست ثبت نشده"
                else:
                    note = (
                        f"{eligible} فرزند × {rule.wage_day_multiplier} × "
                        f"حداقل مزد {emp.minimum_daily_wage} × نسبت {ratio}"
                    )

        elif comp.calc_mode == "policy_bonus":
            if emp.month_j == int(rates.bonus_payment_month) and daily_wage > 0:
                factor = D(rates.bonus_day_factor)
                amount = daily_wage * factor * ratio
                qty = factor
                unit = daily_wage
                note = f"{daily_wage} × {factor} روز × نسبت {ratio}"
            else:
                note = "خارج از ماه پرداخت پاداش / ضریب صفر"

        amount = money_round(amount)

        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="earning",
                amount=amount,
                quantity=qty,
                unit_amount=unit,
                calc_note=note,
                subject_to_insurance=comp.subject_to_insurance,
                subject_to_tax=comp.subject_to_tax,
                sort_order=comp.sort_order,
            )
        )

    _append_overtime_lines(emp, components, lines)
    _append_shift_line(emp, components, lines)
    _append_night_line(emp, components, lines, rates)
    _append_friday_line(emp, components, lines, rates)

    insurance_base = sum(
        (ln.amount for ln in lines if ln.subject_to_insurance), D(0)
    )
    tax_base = sum((ln.amount for ln in lines if ln.subject_to_tax), D(0))

    for comp in sorted(components, key=lambda c: c.sort_order):
        if comp.kind != "deduction":
            continue
        amount = D(0)
        note = ""
        qty = None
        unit = None
        if comp.calc_mode == "percent_insurance":
            pct = D(rates.insurance_employee_pct)
            amount = money_round(insurance_base * pct / D(100))
            unit = pct
            qty = insurance_base
            note = f"{pct}% از مبنای مشمول بیمه ({insurance_base})"
        elif comp.calc_mode == "percent_tax":
            pct = D(rates.tax_pct)
            amount = money_round(tax_base * pct / D(100))
            unit = pct
            qty = tax_base
            note = f"{pct}% از مبنای مشمول مالیات ({tax_base})"
        elif comp.calc_mode == "work_deficit":
            rule = emp.deficit_rule
            qty = D(emp.deficit_hours)
            if rule is None:
                amount = D(0)
                note = "سیاست کسر کار برای این عضویت نیست"
            else:
                basis = _policy_basis(components, lines, rule, rule.basis_days)
                amount, unit, note = ordinary_hour_pay(basis, emp.deficit_hours, rule)
        elif comp.calc_mode == "manual":
            amount = money_round(D(emp.manual_amounts.get(comp.code, 0)))
            note = "ورود دستی"
        else:
            amount = D(0)
            note = ""

        if amount == 0 and comp.calc_mode.startswith("percent") and D(
            getattr(rates, "tax_pct" if "tax" in comp.calc_mode else "insurance_employee_pct", 0)
        ) == 0:
            # هنوز خط صفر مالیات را نشان بده اگر درصد صفر است؟ برای شفافیت نگه می‌داریم اگر کد TAX/INSURANCE باشد
            pass

        lines.append(
            LineItem(
                component_id=comp.id,
                component_code=comp.code,
                component_name=comp.name,
                kind="deduction",
                amount=amount,
                quantity=qty,
                unit_amount=unit,
                calc_note=note,
                subject_to_insurance=False,
                subject_to_tax=False,
                sort_order=comp.sort_order,
            )
        )

    gross = money_round(sum((ln.amount for ln in lines if ln.kind == "earning"), D(0)))
    deductions = money_round(
        sum((ln.amount for ln in lines if ln.kind == "deduction"), D(0))
    )
    net = money_round(gross - deductions)

    return PayslipDraft(
        user_id=emp.user_id,
        employee_name=emp.employee_name,
        membership_type_code=emp.membership_type_code,
        covered_days=emp.covered_days,
        month_days=emp.month_days,
        items=lines,
        gross_earnings=gross,
        total_deductions=deductions,
        net_pay=net,
    )
