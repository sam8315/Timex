"""پایه سنوات تجمیعی — پارامترهای سالانه از Policy، هم‌تراز جداول رسمی.

فرمول برای k سال سابقه در سال شمسی Y:
  سال‌های سیاست: (Y - k + 1) … Y
  S = N[y0]
  S = round(S × R[y] + N[y])  برای هر سال بعدی

گرد کردن میانی هر سال (ریال صحیح، ROUND_HALF_UP) برای تطبیق با جداول
منتشرشده تأمین اجتماعی / محاسبات رایج بخشنامه مزد لازم است.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Mapping, Optional, Sequence

import jdatetime

from core.payroll.money import D, money_round


@dataclass(frozen=True)
class AnnualSeniorityPolicy:
    year_j: int
    new_seniority_daily: Decimal
    wage_increase_factor: Decimal


def jalali_completed_years(hire_date: date, payroll_date: date) -> int:
    """سال‌های کامل سابقه بر اساس سالگرد جلالی استخدام."""
    if payroll_date < hire_date:
        return 0
    hire_j = jdatetime.date.fromgregorian(date=hire_date)
    pay_j = jdatetime.date.fromgregorian(date=payroll_date)
    years = pay_j.year - hire_j.year
    try:
        anniversary = jdatetime.date(hire_j.year + years, hire_j.month, hire_j.day)
    except ValueError:
        anniversary = jdatetime.date(hire_j.year + years, hire_j.month, 29)
    if pay_j < anniversary:
        years -= 1
    return max(0, years)


# سازگاری با نام قبلی
def completed_years(hire_date: date, payroll_date: date) -> int:
    return jalali_completed_years(hire_date, payroll_date)


def first_eligible_jalali_year(hire_date: date) -> int:
    """اولین سال شمسی استحقاق = سال شمسی اولین سالگرد استخدام (جلالی)."""
    hire_j = jdatetime.date.fromgregorian(date=hire_date)
    try:
        ann_j = jdatetime.date(hire_j.year + 1, hire_j.month, hire_j.day)
    except ValueError:
        ann_j = jdatetime.date(hire_j.year + 1, hire_j.month, 29)
    return ann_j.year


def _policy_map(
    annual_policies: Sequence[AnnualSeniorityPolicy] | Mapping[int, AnnualSeniorityPolicy],
) -> Dict[int, AnnualSeniorityPolicy]:
    if isinstance(annual_policies, Mapping):
        return dict(annual_policies)
    return {p.year_j: p for p in annual_policies}


def calculate_accumulated_seniority_daily(
    hire_date: Optional[date],
    payroll_date: date,
    annual_policies: Sequence[AnnualSeniorityPolicy] | Mapping[int, AnnualSeniorityPolicy],
    *,
    final_round: bool = True,
) -> Decimal:
    """
    S[Y] برای کارمند با k سال سابقه کامل:
      start = Y - k + 1
      S = N[start]
      برای y در (start+1)..Y: S = round(S × R[y] + N[y])
    """
    if hire_date is None:
        return D(0)

    k = jalali_completed_years(hire_date, payroll_date)
    if k < 1:
        return D(0)

    policies = _policy_map(annual_policies)
    if not policies:
        return D(0)

    payroll_year_j = jdatetime.date.fromgregorian(date=payroll_date).year
    start_year = payroll_year_j - k + 1

    accumulated = D(0)
    for year in range(start_year, payroll_year_j + 1):
        policy = policies.get(year)
        if policy is None:
            n = D(0)
            r = D(1)
        else:
            n = D(policy.new_seniority_daily)
            r = D(policy.wage_increase_factor)

        if accumulated == 0:
            accumulated = n
        else:
            accumulated = (accumulated * r) + n
        # گرد کردن سالانه برای تطبیق با جداول رسمی
        accumulated = money_round(accumulated)

    if final_round:
        return money_round(accumulated)
    return accumulated
