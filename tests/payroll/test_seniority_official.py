"""تطبیق پایه سنوات با جداول رسمی و مثال علی."""
from __future__ import annotations

import jdatetime

from core.payroll.money import D
from core.payroll.official_seniority_laws import OFFICIAL_SENIORITY_LAWS
from core.payroll.seniority import (
    AnnualSeniorityPolicy,
    calculate_accumulated_seniority_daily,
    jalali_completed_years,
)


def _official_policies():
    return [
        AnnualSeniorityPolicy(y, D(n), D(r))
        for y, n, r, _src in OFFICIAL_SENIORITY_LAWS
    ]


def test_ali_shahrivar_1405_monthly_seniority():
    """علی استخدام ۱۳۹۷/۱۲/۰۱ — شهریور ۱۴۰۵ (۳۱ روز) = ۳۵٬۴۶۱٬۰۸۶ ریال."""
    hire = jdatetime.date(1397, 12, 1).togregorian()
    payroll = jdatetime.date(1405, 6, 15).togregorian()
    assert jalali_completed_years(hire, payroll) == 7

    daily = calculate_accumulated_seniority_daily(
        hire, payroll, _official_policies()
    )
    assert daily == D("1143906")
    assert daily * 31 == D("35461086")


def test_official_table_1405_selected_rows():
    """چند ردیف جدول ۱۴۰۵ برای سابقه کامل تا پایان سال."""
    policies = _official_policies()
    # استخدام ۱/۱ با k سال در نیمه سال ۱۴۰۵ (بعد از سالگرد فروردین)
    expected = {
        1: D("166667"),
        2: D("302967"),
        7: D("1143906"),
    }
    for k, exp in expected.items():
        hire_year = 1405 - k
        hire = jdatetime.date(hire_year, 1, 1).togregorian()
        payroll = jdatetime.date(1405, 6, 15).togregorian()
        assert jalali_completed_years(hire, payroll) == k
        daily = calculate_accumulated_seniority_daily(hire, payroll, policies)
        assert daily == exp, f"k={k}: got {daily} expected {exp}"
