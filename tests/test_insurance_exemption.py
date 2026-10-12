"""معافیت بیمه سهم کارمند فقط همان نفر را صفر می‌کند."""
from datetime import date
from types import SimpleNamespace

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.money import D
from core.payroll.payslip_present import line_detail
from web.services.payroll.policy_service import exemption_applies


def _emp(*, exempt: bool) -> EmployeeCalcInput:
    return EmployeeCalcInput(
        user_id="u",
        employee_name="ن",
        membership_type_code="4",
        hire_date=None,
        marital_status="S",
        covered_days=30,
        month_days=30,
        year_j=1405,
        month_j=7,
        payroll_date=date(2026, 10, 22),
        amounts={"DAILY_WAGE": D("100")},
        insurance_exempt=exempt,
    )


def _components():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
    ]


def test_exempt_employee_pays_zero_while_colleague_pays_seven_percent():
    rates = RateSettingsInput(insurance_employee_pct=D("7"), tax_pct=D(0))
    exempt = calculate_employee_payslip(_emp(exempt=True), _components(), rates, [])
    plain = calculate_employee_payslip(_emp(exempt=False), _components(), rates, [])
    exempt_line = next(i for i in exempt.items if i.component_code == "INSURANCE_EMPLOYEE")
    plain_line = next(i for i in plain.items if i.component_code == "INSURANCE_EMPLOYEE")
    assert exempt_line.amount == D(0)
    assert exempt_line.quantity == D(3000)
    assert "معاف از بیمه سهم کارمند" in line_detail(exempt_line)
    assert "۳٬۰۰۰" in line_detail(exempt_line)
    assert plain_line.amount == D(210)


def test_exemption_stops_after_effective_to():
    row = SimpleNamespace(
        user_id="274",
        is_active=True,
        effective_from=date(2026, 9, 23),
        effective_to=date(2026, 10, 22),
    )
    assert exemption_applies([row], "274", date(2026, 10, 22)) is True
    assert exemption_applies([row], "274", date(2026, 10, 23)) is False
    assert exemption_applies([row], "275", date(2026, 10, 1)) is False
    row.is_active = False
    assert exemption_applies([row], "274", date(2026, 10, 1)) is False
