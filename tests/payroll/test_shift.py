"""نوبت‌کاری: درصد ترکیب شیفت و آیتم‌های مبنا از سیاست می‌آیند."""
from datetime import date

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.money import D
from core.payroll.payslip_present import line_detail
from core.payroll.shift import ShiftRule


ON = date(2026, 8, 22)


def _rule(**kwargs):
    base = dict(
        basis_codes=("DAILY_WAGE",),
        pct_morning_evening=D("10"),
        pct_morning_evening_night=D("15"),
        pct_morning_night=D("22.5"),
        pct_evening_night=D("22.5"),
    )
    base.update(kwargs)
    return ShiftRule(**base)


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
        amounts={"DAILY_WAGE": D("100000"), "HOUSING": D("900000")},
        shift_rule=_rule(),
    )
    base.update(kwargs)
    return EmployeeCalcInput(**base)


def _comps():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "HOUSING", "مسکن", "earning", "fixed_monthly_prorata", False, False, 30),
        ComponentDef(3, "SHIFT", "نوبت‌کاری", "earning", "shift_policy", True, True, 90),
        ComponentDef(4, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
    ]


def _shift(draft):
    return next(item for item in draft.items if item.component_code == "SHIFT")


def test_morning_evening_uses_configured_percent_and_selected_items():
    draft = calculate_employee_payslip(
        _emp(morning_hours=D("40"), evening_hours=D("20"), night_hours=D(0)),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D("7")),
        [],
    )
    line = _shift(draft)
    wage = D("100000") * 30
    assert line.amount == wage * D("10") / D(100)
    assert line.unit_amount == wage
    assert "صبح و عصر" in line_detail(line)
    insurance = next(item for item in draft.items if item.component_code == "INSURANCE_EMPLOYEE")
    assert insurance.amount == (wage + line.amount) * D("7") / D(100)


def test_three_bands_and_extra_basis_item():
    draft = calculate_employee_payslip(
        _emp(
            morning_hours=D("10"),
            evening_hours=D("10"),
            night_hours=D("8"),
            shift_rule=_rule(basis_codes=("DAILY_WAGE", "HOUSING"), pct_morning_evening_night=D("12")),
        ),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0)),
        [],
    )
    wage = D("100000") * 30
    housing = D("900000")
    line = _shift(draft)
    assert line.amount == (wage + housing) * D("12") / D(100)
    assert line.calc_note == "صبح و عصر و شب"


def test_morning_night_and_evening_night_percents():
    morning_night = calculate_employee_payslip(
        _emp(morning_hours=D("5"), night_hours=D("5")),
        _comps(),
        RateSettingsInput(),
        [],
    )
    evening_night = calculate_employee_payslip(
        _emp(evening_hours=D("5"), night_hours=D("5")),
        _comps(),
        RateSettingsInput(),
        [],
    )
    wage = D("100000") * 30
    assert _shift(morning_night).amount == wage * D("22.5") / D(100)
    assert _shift(evening_night).amount == wage * D("22.5") / D(100)
    assert "صبح و شب" in line_detail(_shift(morning_night))
    assert "عصر و شب" in line_detail(_shift(evening_night))


def test_selected_codes_filter_and_legacy_means_all():
    from types import SimpleNamespace

    from web.services.payroll.run_service import selected_component_codes

    assert selected_component_codes(SimpleNamespace(component_codes=None)) is None
    assert selected_component_codes(SimpleNamespace(component_codes="")) is None
    assert selected_component_codes(SimpleNamespace(component_codes="DAILY_WAGE,OVERTIME")) == {
        "DAILY_WAGE",
        "OVERTIME",
    }
    chosen = calculate_employee_payslip(
        _emp(shift_pattern="morning_evening"),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0)),
        [],
    )
    blocked = calculate_employee_payslip(
        _emp(
            morning_hours=D("40"),
            evening_hours=D("20"),
            shift_pattern="none",
        ),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0)),
        [],
    )
    night_pair = calculate_employee_payslip(
        _emp(shift_pattern="night_pair"),
        _comps(),
        RateSettingsInput(insurance_employee_pct=D(0)),
        [],
    )
    wage = D("100000") * 30
    assert _shift(chosen).amount == wage * D("10") / D(100)
    assert _shift(chosen).calc_note == "صبح و عصر"
    assert _shift(blocked).amount == D(0)
    assert _shift(night_pair).amount == wage * D("22.5") / D(100)
    assert "صبح و شب یا عصر و شب" in line_detail(_shift(night_pair))
    only_morning = calculate_employee_payslip(
        _emp(morning_hours=D("80")),
        _comps(),
        RateSettingsInput(),
        [],
    )
    no_rule = calculate_employee_payslip(
        _emp(morning_hours=D("10"), evening_hours=D("10"), shift_rule=None),
        _comps(),
        RateSettingsInput(),
        [],
    )
    assert _shift(only_morning).amount == D(0)
    assert _shift(no_rule).amount == D(0)
