"""تعدیل مبلغ قلم بر اساس روز استعلاجی و غیبت، جدا از covered_days."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from core.payroll.money import D, money_round

SICK_KEEP = "keep"
SICK_PRORATE = "prorate"
SICK_EXCLUDE = "exclude"
ABSENCE_KEEP = "keep"
ABSENCE_PRORATE = "prorate"
ABSENCE_IGNORE = "ignore"
BASIS_FIXED_30 = "fixed_30"
BASIS_CALENDAR = "calendar_month"
BASIS_SCHEDULED = "scheduled_work"

HOUR_CALC_MODES = frozenset({
    "overtime_policy",
    "holiday_work",
    "friday_attendance",
    "night_work",
    "shift_policy",
    "work_deficit",
})


@dataclass(frozen=True)
class DayAdjustmentRule:
    component_code: str
    sick_mode: str
    absence_mode: str
    basis: str
    effective_from: date
    scope: str


def rule_is_active(rule: DayAdjustmentRule, on_date: date, effective_to: Optional[date] = None) -> bool:
    if rule.effective_from > on_date:
        return False
    if effective_to is not None and effective_to < on_date:
        return False
    return True


def select_rule(
    rules: Sequence[DayAdjustmentRule],
    component_code: str,
    on_date: date,
) -> Optional[DayAdjustmentRule]:
    """اختصاصی‌ترین قانون معتبر: کارمند، سپس عضویت، سپس پیش‌فرض قلم."""
    rank = {"employee": 0, "membership": 1, "default": 2}
    matching = [
        rule for rule in rules
        if rule.component_code == component_code and rule_is_active(rule, on_date)
    ]
    if not matching:
        return None
    matching.sort(key=lambda rule: (rank.get(rule.scope, 9), -rule.effective_from.toordinal()))
    return matching[0]


def basis_day_count(
    basis: str,
    *,
    month_days: int,
    scheduled_work_days: int,
) -> int:
    if basis == BASIS_CALENDAR:
        return max(int(month_days or 0), 1)
    if basis == BASIS_SCHEDULED:
        return max(int(scheduled_work_days or 0), 1)
    return 30


def adjust_amount(
    amount: Decimal,
    rule: Optional[DayAdjustmentRule],
    *,
    excluded_sick_days: int,
    absence_days: int,
    month_days: int,
    scheduled_work_days: int,
) -> tuple[Decimal, str]:
    """مبلغ فعلی قلم را فقط وقتی قانون دارد تعدیل می‌کند. covered_days را عوض نمی‌کند."""
    if rule is None or rule.sick_mode == SICK_KEEP and rule.absence_mode == ABSENCE_KEEP:
        return amount, ""
    days = basis_day_count(
        rule.basis,
        month_days=month_days,
        scheduled_work_days=scheduled_work_days,
    )
    basis = D(days)
    result = D(amount)
    notes: list[str] = []
    excluded = max(int(excluded_sick_days or 0), 0)
    absent = max(int(absence_days or 0), 0)

    if rule.sick_mode == SICK_PRORATE and excluded:
        eligible = max(days - excluded, 0)
        result = result * D(eligible) / basis
        notes.append(f"استعلاجی خارج از پرداخت کارفرما {excluded} از {days}")
    elif rule.sick_mode == SICK_EXCLUDE and excluded:
        share = D(amount) * D(excluded) / basis
        result = result - share
        notes.append(f"کسر سهم {excluded} روز استعلاجی از {days}")

    if rule.absence_mode == ABSENCE_PRORATE and absent:
        eligible = max(days - absent, 0)
        result = result * D(eligible) / basis
        notes.append(f"غیبت عادی {absent} از {days}")

    if result < 0:
        result = D(0)
    return money_round(result), " | ".join(notes)


def guarded_deficit_hours(
    deficit_hours: Decimal,
    absence_duty_hours: Decimal,
    rules: Sequence[DayAdjustmentRule],
) -> Decimal:
    """اگر غیبت روزانه جای دیگری کسر شده، یا کسر کار نسبت به غیبت بی‌اثر است، همان دقیقه‌ها دوباره کم نمی‌شوند."""
    prorated = any(rule.absence_mode == ABSENCE_PRORATE for rule in rules)
    ignored = any(
        rule.component_code == "WORK_DEFICIT" and rule.absence_mode == ABSENCE_IGNORE
        for rule in rules
    )
    if not prorated and not ignored:
        return D(deficit_hours)
    return max(D(0), D(deficit_hours) - D(absence_duty_hours or 0))
