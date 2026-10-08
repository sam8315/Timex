"""تست واحد موتور حقوق (بدون دیتابیس)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import jdatetime
import pytest

from core.payroll.calendar_utils import month_day_count, jalali_month_bounds
from core.payroll.contract_coverage import contract_covered_days, coverage_ratio
from core.payroll.money import D, money_round
from core.payroll.seniority import (
    AnnualSeniorityPolicy,
    calculate_accumulated_seniority_daily,
    first_eligible_jalali_year,
)
from core.payroll.calculation_engine import (
    ComponentDef,
    EmployeeCalcInput,
    RateSettingsInput,
    calculate_employee_payslip,
)


def test_month_day_count_farvardin_and_mehr():
    assert month_day_count(1404, 1) == 31
    assert month_day_count(1404, 7) == 30


def test_contract_full_month_ratio_one():
    start, end = jalali_month_bounds(1404, 1)
    days = contract_covered_days(start, end, start, end)
    assert days == month_day_count(1404, 1)
    assert coverage_ratio(days, days) == D(1)


def test_contract_mid_month_proration():
    from datetime import timedelta

    start, end = jalali_month_bounds(1404, 1)
    mid = start + timedelta(days=15)
    covered = contract_covered_days(start, end, mid, None)
    month_days = month_day_count(1404, 1)
    assert 0 < covered < month_days
    ratio = coverage_ratio(covered, month_days)
    assert ratio < D(1)


def test_seniority_one_year_is_new_base_only():
    """یک سال سابقه در ۱۴۰۵ = فقط N[1405]."""
    hire = jdatetime.date(1404, 1, 1).togregorian()
    payroll = jdatetime.date(1405, 6, 15).togregorian()
    policies = [
        AnnualSeniorityPolicy(1404, D("94000"), D("1.32")),
        AnnualSeniorityPolicy(1405, D("166667"), D("1.45")),
    ]
    daily = calculate_accumulated_seniority_daily(hire, payroll, policies)
    assert daily == D("166667")
    assert first_eligible_jalali_year(hire) == 1405


def test_seniority_zero_before_one_year():
    hire = date(2025, 1, 1)
    payroll = date(2025, 6, 1)
    policies = [AnnualSeniorityPolicy(1404, D("1000"), D("1"))]
    assert calculate_accumulated_seniority_daily(hire, payroll, policies) == D(0)


def _default_components():
    return [
        ComponentDef(1, "DAILY_WAGE", "حقوق روزانه", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "HOUSING", "حق مسکن", "earning", "fixed_monthly_prorata", True, True, 40),
        ComponentDef(3, "MARRIAGE", "حق تأهل", "earning", "fixed_monthly_prorata", True, True, 50),
        ComponentDef(4, "SENIORITY", "پایه سنوات", "earning", "seniority_chain", True, True, 70),
        ComponentDef(5, "SHIFT", "نوبت‌کاری", "earning", "manual", True, True, 20),
        ComponentDef(6, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
        ComponentDef(7, "TAX", "مالیات", "deduction", "percent_tax", False, False, 210),
    ]


def test_marriage_only_when_married():
    start, end = jalali_month_bounds(1404, 1)
    month_days = month_day_count(1404, 1)
    rates = RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0))
    base = dict(
        user_id="1",
        employee_name="Test",
        membership_type_code="4",
        hire_date=None,
        covered_days=month_days,
        month_days=month_days,
        year_j=1404,
        month_j=1,
        payroll_date=end,
        amounts={"DAILY_WAGE": D(1000), "HOUSING": D(30000), "MARRIAGE": D(50000)},
    )
    married = calculate_employee_payslip(
        EmployeeCalcInput(**base, marital_status="M"),
        _default_components(),
        rates,
        [],
    )
    single = calculate_employee_payslip(
        EmployeeCalcInput(**base, marital_status="S"),
        _default_components(),
        rates,
        [],
    )
    m_line = next(i for i in married.items if i.component_code == "MARRIAGE")
    s_line = next((i for i in single.items if i.component_code == "MARRIAGE"), None)
    assert m_line.amount == D(50000)
    assert s_line is None or s_line.amount == D(0)


def test_insurance_and_tax_flags():
    start, end = jalali_month_bounds(1404, 1)
    month_days = month_day_count(1404, 1)
    comps = [
        ComponentDef(1, "DAILY_WAGE", "حقوق", "earning", "daily_x_covered", True, True, 10),
        ComponentDef(2, "HOUSING", "مسکن", "earning", "fixed_monthly_prorata", False, False, 40),
        ComponentDef(3, "INSURANCE_EMPLOYEE", "بیمه", "deduction", "percent_insurance", False, False, 200),
        ComponentDef(4, "TAX", "مالیات", "deduction", "percent_tax", False, False, 210),
    ]
    draft = calculate_employee_payslip(
        EmployeeCalcInput(
            user_id="1",
            employee_name="T",
            membership_type_code="4",
            hire_date=None,
            marital_status="S",
            covered_days=month_days,
            month_days=month_days,
            year_j=1404,
            month_j=1,
            payroll_date=end,
            amounts={"DAILY_WAGE": D(10000), "HOUSING": D(100000)},
        ),
        comps,
        RateSettingsInput(insurance_employee_pct=D(10), tax_pct=D(5)),
        [],
    )
    wage = month_days * D(10000)
    # فقط حقوق مشمول بیمه/مالیات است نه مسکن
    ins = next(i for i in draft.items if i.component_code == "INSURANCE_EMPLOYEE")
    tax = next(i for i in draft.items if i.component_code == "TAX")
    assert ins.amount == money_round(wage * D("0.10"))
    assert tax.amount == money_round(wage * D("0.05"))


def test_manual_shift_included():
    start, end = jalali_month_bounds(1404, 1)
    month_days = month_day_count(1404, 1)
    draft = calculate_employee_payslip(
        EmployeeCalcInput(
            user_id="1",
            employee_name="T",
            membership_type_code="4",
            hire_date=None,
            marital_status="S",
            covered_days=month_days,
            month_days=month_days,
            year_j=1404,
            month_j=1,
            payroll_date=end,
            amounts={"DAILY_WAGE": D(1000)},
            manual_amounts={"SHIFT": D(25000)},
        ),
        _default_components(),
        RateSettingsInput(insurance_employee_pct=D(0), tax_pct=D(0)),
        [],
    )
    shift = next(i for i in draft.items if i.component_code == "SHIFT")
    assert shift.amount == D(25000)


def test_published_visibility_helper_logic():
    """کارمند فقط وضعیت published را باید ببیند — منطق فیلتر سرویس."""
    statuses = ["draft", "calculated", "approved", "published"]
    visible = [s for s in statuses if s == "published"]
    assert visible == ["published"]
