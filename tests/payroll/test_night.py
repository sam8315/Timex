"""شب‌کاری: ۳۵ درصد مزد ساعتی برای ساعات ۲۲ تا ۶، مگر نوع نوبت حذف‌شده در سیاست."""
from datetime import date

from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)
from core.payroll.money import D
from core.payroll.night import NightRule, parse_excluded_patterns
from core.payroll.payslip_present import line_detail, payslip_sort_key
from core.payroll.shift import PATTERN_MORNING_EVENING, PATTERN_NIGHT_PAIR, PATTERN_NONE


ON = date(2026, 8, 22)


def _rule(**kwargs):
    base = dict(premium_percent=D("35"))
    base.update(kwargs)
    return NightRule(**base)


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
        amounts={"DAILY_WAGE": D("800000")},
        night_hours=D("10"),
        shift_pattern=PATTERN_NONE,
        night_rule=_rule(),
    )
    base.update(kwargs)
    return EmployeeCalcInput(**base)


def _comps():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "NIGHT_WORK", "شب‌کاری", "earning", "night_work", True, True, 85),
        ComponentDef(3, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
    ]


def _night(draft):
    return next(item for item in draft.items if item.component_code == "NIGHT_WORK")


def _rates():
    return RateSettingsInput(hours_per_day=D("8"), insurance_employee_pct=D("7"))


def test_non_shift_worker_gets_percent_of_hourly_wage():
    draft = calculate_employee_payslip(_emp(), _comps(), _rates(), [])
    line = _night(draft)
    assert line.amount == D("350000")
    assert line.unit_amount == D("100000")
    assert line.quantity == D("10")
    assert "ساعت شب" in line_detail(line)
    assert "۳۵" in line_detail(line)
    wage = D("800000") * 30
    insurance = next(item for item in draft.items if item.component_code == "INSURANCE_EMPLOYEE")
    assert insurance.amount == (wage + line.amount) * D("7") / D(100)


def test_excluded_shift_pattern_omits_line():
    draft = calculate_employee_payslip(
        _emp(shift_pattern=PATTERN_MORNING_EVENING),
        _comps(),
        _rates(),
        [],
    )
    assert all(item.component_code != "NIGHT_WORK" for item in draft.items)


def test_morning_evening_still_paid_when_only_night_shifts_are_excluded():
    draft = calculate_employee_payslip(
        _emp(
            shift_pattern=PATTERN_MORNING_EVENING,
            night_rule=_rule(excluded_patterns=(PATTERN_NIGHT_PAIR,)),
        ),
        _comps(),
        _rates(),
        [],
    )
    assert _night(draft).amount == D("350000")


def test_zero_night_hours_omits_line():
    draft = calculate_employee_payslip(_emp(night_hours=D(0)), _comps(), _rates(), [])
    assert all(item.component_code != "NIGHT_WORK" for item in draft.items)


def test_missing_policy_omits_line():
    draft = calculate_employee_payslip(_emp(night_rule=None), _comps(), _rates(), [])
    assert all(item.component_code != "NIGHT_WORK" for item in draft.items)


def test_assignment_overrides_hourly_rate():
    draft = calculate_employee_payslip(
        _emp(amounts={"DAILY_WAGE": D("800000"), "NIGHT_WORK": D("50000")}),
        _comps(),
        _rates(),
        [],
    )
    line = _night(draft)
    assert line.amount == D("175000")
    assert line.unit_amount == D("50000")


def test_payslip_order_is_after_friday_and_before_shift():
    class _Item:
        def __init__(self, code):
            self.kind = "earning"
            self.component_code = code
            self.sort_order = 100

    friday = _Item("FRIDAY_WORK")
    night = _Item("NIGHT_WORK")
    shift = _Item("SHIFT")
    assert payslip_sort_key(friday) < payslip_sort_key(night) < payslip_sort_key(shift)


def test_parse_excluded_patterns_drops_unknown_and_none():
    assert parse_excluded_patterns("none,morning_evening,nope,night_pair") == (
        PATTERN_MORNING_EVENING,
        PATTERN_NIGHT_PAIR,
    )
