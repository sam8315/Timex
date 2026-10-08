"""حق اولاد از سیاست و واقعیت فرزندان — بدون شرط عضویت داخل کد."""
from datetime import date
from decimal import Decimal

from core.payroll.child_allowance import (
    ChildAllowanceRule,
    ChildFact,
    child_allowance_monthly,
    count_eligible_children,
)
from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.money import D


def _rule(**kwargs) -> ChildAllowanceRule:
    base = dict(
        applies_to_female=True,
        age_limit_years=18,
        require_study_above_age=True,
        wage_day_multiplier=D("3"),
        count_only_verified=False,
    )
    base.update(kwargs)
    return ChildAllowanceRule(**base)


ON = date(2026, 9, 22)  # شهریور ۱۴۰۵


def test_under_18_living_counts_deceased_and_adult_without_study_do_not():
    children = [
        ChildFact(birth_date=date(2015, 1, 1)),
        ChildFact(birth_date=date(2000, 1, 1), is_studying=False),
        ChildFact(birth_date=date(2016, 1, 1), death_date=date(2026, 1, 1)),
        ChildFact(birth_date=date(2004, 1, 1), is_studying=True),
    ]
    assert count_eligible_children(children, ON, _rule()) == 2


def test_minimum_wage_prefers_membership_then_default():
    from core.payroll.child_allowance import resolve_minimum_daily

    entries = [(None, D("100")), ("4", D("250"))]
    assert resolve_minimum_daily(entries, "4") == D("250")
    assert resolve_minimum_daily(entries, "1") == D("100")
    assert resolve_minimum_daily(entries, None) == D("100")


def test_amount_is_multiplier_times_minimum_wage_not_a_code_constant():
    amount = child_allowance_monthly(2, D("5541850"), D("3"), D("1"))
    assert amount == D("5541850") * 3 * 2
    other = child_allowance_monthly(2, D("1000"), D("2"), D("1"))
    assert other == D("4000")


def test_female_excluded_only_when_policy_says_so():
    comp = ComponentDef(1, "CHILD_ALLOWANCE", "حق اولاد", "earning", "child_allowance", True, True, 55)
    child = ChildFact(birth_date=date(2015, 1, 1))
    common = dict(
        user_id="1",
        employee_name="ن",
        membership_type_code="1",
        hire_date=None,
        marital_status="M",
        covered_days=31,
        month_days=31,
        year_j=1405,
        month_j=6,
        payroll_date=ON,
        children=(child,),
        minimum_daily_wage=D("100"),
    )
    excluded = calculate_employee_payslip(
        EmployeeCalcInput(**common, gender="F", child_rule=_rule(applies_to_female=False)),
        [comp],
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    included = calculate_employee_payslip(
        EmployeeCalcInput(**common, gender="F", child_rule=_rule(applies_to_female=True)),
        [comp],
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    ex_line = next(i for i in excluded.items if i.component_code == "CHILD_ALLOWANCE")
    in_line = next(i for i in included.items if i.component_code == "CHILD_ALLOWANCE")
    assert ex_line.amount == D(0)
    assert in_line.amount == D("300")
