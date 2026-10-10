"""اضافه‌کار قراردادی: مبنای قابل انتخاب و دو روش نرخ."""
from datetime import date

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.money import D, money_round
from core.payroll.overtime import METHOD_HOURLY_X_FACTOR, METHOD_MONTHLY_DIV, DeficitRule, OvertimeRule


ON = date(2026, 8, 22)


def _emp(**kwargs):
    base = dict(
        user_id="1",
        employee_name="ن",
        membership_type_code="4",
        hire_date=None,
        marital_status="S",
        covered_days=30,
        month_days=30,
        year_j=1405,
        month_j=6,
        payroll_date=ON,
        amounts={"DAILY_WAGE": D("100000"), "HOUSING": D("3000000")},
        overtime_hours=D("2"),
    )
    base.update(kwargs)
    return EmployeeCalcInput(**base)


def _comps():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "HOUSING", "مسکن", "earning", "fixed_monthly_prorata", True, False, 40),
        ComponentDef(3, "OVERTIME", "اضافه‌کار", "earning", "overtime_policy", True, True, 35),
        ComponentDef(4, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
    ]


def test_monthly_div_uses_only_selected_items():
    # حقوق روزانه = 100000 × 30 = 3_000_000؛ مسکن انتخاب نشده
    rule = OvertimeRule(METHOD_MONTHLY_DIV, ("DAILY_WAGE",), divisor=D("157"))
    draft = calculate_employee_payslip(
        _emp(overtime_rule=rule),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    line = next(i for i in draft.items if i.component_code == "OVERTIME")
    expected = D("3000000") / D("157") * D("2")
    assert line.amount == money_round(expected)


def test_hourly_factor_uses_sum_of_selected_items():
    rule = OvertimeRule(
        METHOD_HOURLY_X_FACTOR,
        ("DAILY_WAGE", "HOUSING"),
        premium_factor=D("1.4"),
        ordinary_month_hours=D("220"),
    )
    draft = calculate_employee_payslip(
        _emp(overtime_rule=rule),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D("10"), tax_pct=D(0)),
        [],
    )
    # 3_000_000 + 3_000_000 = 6_000_000؛ ساعت عادی = 6_000_000/220؛ نرخ = × 1.4؛ × 2 ساعت
    basis = D("6000000")
    rate = (basis / D("220")) * D("1.4")
    line = next(i for i in draft.items if i.component_code == "OVERTIME")
    assert line.amount == money_round(rate * D("2"))
    ins = next(i for i in draft.items if i.component_code == "INSURANCE_EMPLOYEE")
    wage = D("3000000")
    housing = D("3000000")
    assert ins.quantity == wage + housing + line.amount


def test_monthly_div_basis_uses_thirty_days_not_month_work_days():
    rule = OvertimeRule(METHOD_MONTHLY_DIV, ("DAILY_WAGE",), divisor=D("157"))
    draft = calculate_employee_payslip(
        _emp(overtime_rule=rule, covered_days=31, month_days=31),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    wage = next(i for i in draft.items if i.component_code == "DAILY_WAGE")
    assert wage.amount == D("3100000")
    line = next(i for i in draft.items if i.component_code == "OVERTIME")
    expected = D("100000") * D("30") / D("157") * D("2")
    assert line.amount == money_round(expected)
    draft = calculate_employee_payslip(
        _emp(),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    line = next(i for i in draft.items if i.component_code == "OVERTIME")
    assert line.amount == D(0)


def test_holiday_work_uses_the_same_rate_as_overtime():
    rule = OvertimeRule(METHOD_MONTHLY_DIV, ("DAILY_WAGE",), divisor=D("157"))
    comps = _comps() + [
        ComponentDef(5, "HOLIDAY_WORK", "تعطیل‌کاری", "earning", "holiday_work", True, True, 75),
    ]
    draft = calculate_employee_payslip(
        _emp(overtime_rule=rule, overtime_hours=D("2"), holiday_hours=D("5")),
        comps,
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    overtime = next(i for i in draft.items if i.component_code == "OVERTIME")
    holiday = next(i for i in draft.items if i.component_code == "HOLIDAY_WORK")
    assert overtime.unit_amount == holiday.unit_amount
    assert holiday.amount == money_round(D(overtime.unit_amount) * D("5"))


def test_deficit_rate_is_one_ordinary_hour_without_overtime_premium():
    rule = OvertimeRule(
        METHOD_MONTHLY_DIV,
        ("DAILY_WAGE",),
        divisor=D("157"),
        ordinary_month_hours=D("220"),
    )
    comps = _comps() + [
        ComponentDef(6, "WORK_DEFICIT", "کسر کار", "deduction", "work_deficit", False, False, 190),
    ]
    draft = calculate_employee_payslip(
        _emp(
            overtime_rule=rule,
            deficit_rule=DeficitRule(("DAILY_WAGE",), ordinary_month_hours=D("220"), basis_days=D(30)),
            overtime_hours=D("2"),
            deficit_hours=D("3"),
        ),
        comps,
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    overtime = next(i for i in draft.items if i.component_code == "OVERTIME")
    deficit = next(i for i in draft.items if i.component_code == "WORK_DEFICIT")
    ordinary = D("100000") * D("30") / D("220")
    assert deficit.kind == "deduction"
    assert deficit.amount == money_round(ordinary * D("3"))
    assert deficit.unit_amount != overtime.unit_amount
