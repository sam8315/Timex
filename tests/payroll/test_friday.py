"""جمعه‌کاری: درصد مزد ساعتی اقلام مبنا، مگر نوع نوبت حذف‌شده."""
from datetime import date

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.friday import FridayRule
from core.payroll.money import D
from core.payroll.payslip_present import line_detail
from core.payroll.shift import PATTERN_MORNING_EVENING, PATTERN_NONE


ON = date(2026, 8, 22)


def _rule(**kwargs):
    base = dict(premium_percent=D("96"), basis_codes=("DAILY_WAGE",))
    base.update(kwargs)
    return FridayRule(**base)


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
        amounts={"DAILY_WAGE": D("800000"), "HOUSING": D("9000000")},
        friday_hours=D("8"),
        shift_pattern=PATTERN_NONE,
        friday_rule=_rule(),
    )
    base.update(kwargs)
    return EmployeeCalcInput(**base)


def _comps():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "HOUSING", "مسکن", "earning", "fixed_monthly_prorata", False, False, 30),
        ComponentDef(3, "FRIDAY_WORK", "جمعه‌کاری", "earning", "friday_attendance", True, True, 80),
    ]


def _friday(draft):
    return next(item for item in draft.items if item.component_code == "FRIDAY_WORK")


def _rates():
    return RateSettingsInput(hours_per_day=D("8"), friday_coefficient=D("1.96"))


def test_daily_wage_basis_is_percent_of_hourly():
    draft = calculate_employee_payslip(_emp(), _comps(), _rates(), [])
    line = _friday(draft)
    # 800000 / 8 = 100000؛ ۹۶ درصد × ۸ ساعت
    assert line.unit_amount == D("100000")
    assert line.amount == D("768000")
    assert line_detail(line) == "۸ ساعت، نرخ هر ساعت ۹۶٬۰۰۰ ریال"


def test_extra_basis_item_raises_hourly_wage():
    draft = calculate_employee_payslip(
        _emp(friday_rule=_rule(basis_codes=("DAILY_WAGE", "HOUSING"))),
        _comps(),
        _rates(),
        [],
    )
    # ماهانه = 800000×30 + 9000000 = 33000000؛ ساعتی = 33000000 / 240 = 137500
    line = _friday(draft)
    assert line.unit_amount == D("137500")
    assert line.amount == D("137500") * D("96") / D("100") * D("8")


def test_excluded_shift_and_zero_hours_stay_on_payslip():
    excluded = calculate_employee_payslip(
        _emp(shift_pattern=PATTERN_MORNING_EVENING),
        _comps(),
        _rates(),
        [],
    )
    quiet = calculate_employee_payslip(_emp(friday_hours=D(0)), _comps(), _rates(), [])
    missing = calculate_employee_payslip(_emp(friday_rule=None), _comps(), _rates(), [])
    assert _friday(excluded).amount == D(0)
    assert _friday(quiet).amount == D(0)
    assert _friday(missing).amount == D(0)


def test_global_friday_coefficient_is_not_used():
    draft = calculate_employee_payslip(
        _emp(),
        _comps(),
        RateSettingsInput(hours_per_day=D("8"), friday_coefficient=D("9")),
        [],
    )
    assert _friday(draft).amount == D("768000")
