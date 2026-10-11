"""قواعد قلم استعلاجی از covered_days جدا هستند و اختصاصی‌ترین قانون برنده است."""
from datetime import date
from decimal import Decimal

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.day_adjustment import (
    DayAdjustmentRule,
    adjust_amount,
    guarded_deficit_hours,
    select_rule,
)
from core.payroll.money import D


def _rule(code, scope, sick="keep", absence="keep", basis="fixed_30", start=date(2020, 1, 1)):
    return DayAdjustmentRule(code, sick, absence, basis, start, scope)


def test_most_specific_rule_wins_and_old_rule_stays_for_past_dates():
    rules = [
        _rule("DAILY_WAGE", "default", sick="exclude"),
        _rule("DAILY_WAGE", "membership", sick="prorate"),
        _rule("DAILY_WAGE", "employee", sick="keep", start=date(2026, 1, 1)),
    ]
    chosen = select_rule(rules, "DAILY_WAGE", date(2026, 6, 1))
    assert chosen.scope == "employee"
    assert chosen.sick_mode == "keep"
    past = select_rule(rules, "DAILY_WAGE", date(2025, 6, 1))
    assert past.scope == "membership"
    assert past.sick_mode == "prorate"


def test_missing_rule_keeps_amount_and_does_not_touch_covered_days():
    amount, note = adjust_amount(
        D("3000000"),
        None,
        excluded_sick_days=10,
        absence_days=2,
        month_days=30,
        scheduled_work_days=22,
    )
    assert amount == D("3000000")
    assert note == ""


def test_exclude_removes_only_unpaid_sick_share():
    rule = _rule("DAILY_WAGE", "default", sick="exclude", basis="fixed_30")
    amount, note = adjust_amount(
        D("3000"),
        rule,
        excluded_sick_days=10,
        absence_days=0,
        month_days=31,
        scheduled_work_days=22,
    )
    assert amount == D("2000")
    assert "10" in note


def test_absence_proration_guards_deficit_hours_once():
    rules = [
        _rule("DAILY_WAGE", "default", absence="prorate"),
        _rule("WORK_DEFICIT", "default", absence="ignore"),
    ]
    assert guarded_deficit_hours(D("16"), D("8"), rules) == D("8")


def test_payslip_without_rules_matches_current_formula():
    components = [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, False, 10),
        ComponentDef(2, "SENIORITY", "سنوات", "earning", "seniority_chain", False, False, 20),
        ComponentDef(3, "HOUSING", "مزایای ثابت", "earning", "fixed_monthly_prorata", False, False, 25),
        ComponentDef(4, "CHILD_ALLOWANCE", "حق اولاد", "earning", "child_allowance", False, False, 26),
        ComponentDef(5, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 30),
    ]
    emp = EmployeeCalcInput(
        user_id="u",
        employee_name="افسانه",
        membership_type_code="1",
        hire_date=None,
        marital_status="S",
        covered_days=30,
        month_days=30,
        year_j=1404,
        month_j=7,
        payroll_date=date(2025, 10, 22),
        amounts={"DAILY_WAGE": D("100"), "HOUSING": D("900")},
        excluded_sick_days=10,
    )
    draft = calculate_employee_payslip(emp, components, RateSettingsInput(insurance_employee_pct=D("7")), [])
    wage = next(item for item in draft.items if item.component_code == "DAILY_WAGE")
    seniority = next(item for item in draft.items if item.component_code == "SENIORITY")
    housing = next(item for item in draft.items if item.component_code == "HOUSING")
    child = next(item for item in draft.items if item.component_code == "CHILD_ALLOWANCE")
    insurance = next(item for item in draft.items if item.component_code == "INSURANCE_EMPLOYEE")
    codes = {item.component_code for item in draft.items}
    assert wage.amount == D("3000")
    assert seniority.amount == D("0")
    assert housing.amount == D("900")
    assert child.amount == D("0")
    assert insurance.amount == D("210")
    assert "SSO" not in codes


def test_daily_wage_detail_uses_payable_days_not_covered_days():
    from core.payroll.payslip_present import line_detail

    components = [
        ComponentDef(
            1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, False, 10,
            "prorate", "prorate",
        ),
    ]
    emp = EmployeeCalcInput(
        user_id="u",
        employee_name="افسانه",
        membership_type_code="4",
        hire_date=None,
        marital_status="S",
        covered_days=30,
        month_days=30,
        year_j=1405,
        month_j=7,
        payroll_date=date(2026, 10, 22),
        amounts={"DAILY_WAGE": D("5541850")},
        excluded_sick_days=14,
        normal_absence_days=2,
        not_yet_days=11,
    )
    draft = calculate_employee_payslip(emp, components, RateSettingsInput(), [])
    wage = next(item for item in draft.items if item.component_code == "DAILY_WAGE")
    assert wage.quantity == D("14")
    assert wage.amount == D("77585900")
    assert "به مدت ۱۴ روز" in line_detail(wage)


def test_payable_days_apply_to_every_day_based_item():
    from core.payroll.payslip_present import line_detail

    components = [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, False, 10, "prorate", "prorate"),
        ComponentDef(2, "SENIORITY", "سنوات", "earning", "seniority_chain", False, False, 20, "prorate", "prorate"),
        ComponentDef(3, "HOUSING", "مسکن", "earning", "fixed_monthly_prorata", False, False, 30, None, None),
        ComponentDef(4, "MARRIAGE", "تأهل", "earning", "fixed_monthly_prorata", False, False, 40, None, None),
        ComponentDef(5, "WORKER_VOUCHER", "بن", "earning", "fixed_monthly_prorata", False, False, 50, None, None),
    ]
    emp = EmployeeCalcInput(
        user_id="u",
        employee_name="افسانه",
        membership_type_code="4",
        hire_date=None,
        marital_status="M",
        covered_days=30,
        month_days=30,
        year_j=1405,
        month_j=7,
        payroll_date=date(2026, 10, 22),
        amounts={
            "DAILY_WAGE": D("5541850"),
            "HOUSING": D("30000000"),
            "MARRIAGE": D("5000000"),
            "WORKER_VOUCHER": D("22000000"),
        },
        excluded_sick_days=14,
        normal_absence_days=2,
        not_yet_days=11,
    )
    draft = calculate_employee_payslip(emp, components, RateSettingsInput(), [])
    by_code = {item.component_code: item for item in draft.items}
    assert by_code["DAILY_WAGE"].quantity == D("14")
    assert by_code["DAILY_WAGE"].amount == D("77585900")
    assert by_code["SENIORITY"].quantity == D("14")
    assert by_code["HOUSING"].amount == D("14000000")
    assert by_code["MARRIAGE"].amount == D("2333333")
    assert by_code["WORKER_VOUCHER"].amount == D("10266667")
    for code in ("SENIORITY", "HOUSING", "MARRIAGE", "WORKER_VOUCHER"):
        assert "به مدت ۱۴ روز" in line_detail(by_code[code])


def test_payslip_prorates_wage_not_seniority_when_only_wage_has_a_rule():
    components = [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, False, 10, "exclude"),
        ComponentDef(2, "SENIORITY", "سنوات", "earning", "seniority_chain", False, False, 20),
        ComponentDef(3, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 30),
    ]
    emp = EmployeeCalcInput(
        user_id="u",
        employee_name="افسانه",
        membership_type_code="1",
        hire_date=None,
        marital_status="S",
        covered_days=30,
        month_days=30,
        year_j=1404,
        month_j=7,
        payroll_date=date(2025, 10, 22),
        amounts={"DAILY_WAGE": D("100")},
        excluded_sick_days=10,
    )
    draft = calculate_employee_payslip(emp, components, RateSettingsInput(insurance_employee_pct=D("7")), [])
    wage = next(item for item in draft.items if item.component_code == "DAILY_WAGE")
    seniority = next(item for item in draft.items if item.component_code == "SENIORITY")
    insurance = next(item for item in draft.items if item.component_code == "INSURANCE_EMPLOYEE")
    assert wage.amount == D("2000")
    assert seniority.amount == D("0")
    assert insurance.amount == D("140")
    assert emp.covered_days == 30
    assert all("غرامت" not in item.component_name for item in draft.items)
