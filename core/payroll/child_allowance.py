"""حق اولاد — قواعد از Policy می‌آید؛ این ماژول فقط آن‌ها را اعمال می‌کند."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from core.payroll.money import D, money_round


@dataclass(frozen=True)
class ChildFact:
    birth_date: Optional[date]
    death_date: Optional[date] = None
    is_studying: Optional[bool] = None
    study_start_date: Optional[date] = None
    study_end_date: Optional[date] = None
    status: str = "VERIFIED"


@dataclass(frozen=True)
class ChildAllowanceRule:
    applies_to_female: bool
    age_limit_years: int
    require_study_above_age: bool
    wage_day_multiplier: Decimal
    count_only_verified: bool = False


def completed_age_years(birth_date: date, on_date: date) -> int:
    if on_date < birth_date:
        return 0
    years = on_date.year - birth_date.year
    try:
        anniversary = date(birth_date.year + years, birth_date.month, birth_date.day)
    except ValueError:
        anniversary = date(birth_date.year + years, birth_date.month, 28)
    if on_date < anniversary:
        years -= 1
    return max(0, years)


def _is_alive(child: ChildFact, on_date: date) -> bool:
    if child.death_date is None:
        return True
    return child.death_date > on_date


def _is_studying(child: ChildFact, on_date: date) -> bool:
    if not child.is_studying:
        return False
    if child.study_start_date and on_date < child.study_start_date:
        return False
    if child.study_end_date and on_date > child.study_end_date:
        return False
    return True


def child_is_eligible(child: ChildFact, on_date: date, rule: ChildAllowanceRule) -> bool:
    if rule.count_only_verified and (child.status or "").upper() != "VERIFIED":
        return False
    if (child.status or "").upper() == "REJECTED":
        return False
    if not _is_alive(child, on_date):
        return False
    if child.birth_date is None:
        return False
    age = completed_age_years(child.birth_date, on_date)
    if age < int(rule.age_limit_years):
        return True
    if rule.require_study_above_age and _is_studying(child, on_date):
        return True
    return False


def count_eligible_children(
    children: Sequence[ChildFact],
    on_date: date,
    rule: ChildAllowanceRule,
) -> int:
    return sum(1 for child in children if child_is_eligible(child, on_date, rule))


def resolve_minimum_daily(
    entries: Sequence[tuple[Optional[str], Decimal]],
    membership_code: Optional[str],
) -> Decimal:
    """اول ردیف همان عضویت، وگرنه ردیف پیش‌فرض (عضویت خالی)."""
    by_code = {(code or ""): D(amount) for code, amount in entries}
    if membership_code and membership_code in by_code:
        return by_code[membership_code]
    return by_code.get("", D(0))


def child_allowance_monthly(
    eligible_count: int,
    minimum_daily_wage: Decimal,
    wage_day_multiplier: Decimal,
    coverage_ratio: Decimal,
) -> Decimal:
    """مبلغ ماهانه = تعداد فرزند واجد شرایط × (ضریب × حداقل مزد روزانه) × نسبت پوشش قرارداد."""
    unit = D(minimum_daily_wage) * D(wage_day_multiplier)
    return money_round(unit * D(eligible_count) * D(coverage_ratio))
