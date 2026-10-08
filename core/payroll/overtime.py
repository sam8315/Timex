"""محاسبه اضافه‌کار از سیاست عضویت. اعداد و روش داخل موتور ثابت نیستند."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.payroll.money import D, money_round

METHOD_MONTHLY_DIV = "monthly_div"
METHOD_HOURLY_X_FACTOR = "hourly_x_factor"
OVERTIME_METHODS = (METHOD_MONTHLY_DIV, METHOD_HOURLY_X_FACTOR)
OVERTIME_BASIS_DAYS = D(30)
_DAY_BASIS_MODES = frozenset({"daily_x_covered", "seniority_chain"})


@dataclass(frozen=True)
class OvertimeRule:
    method: str
    basis_codes: tuple[str, ...]
    divisor: Decimal = D("157")
    premium_factor: Decimal = D("1.4")
    ordinary_month_hours: Decimal = D("220")


@dataclass(frozen=True)
class DeficitRule:
    basis_codes: tuple[str, ...]
    ordinary_month_hours: Decimal = D("220")
    basis_days: Decimal = D(30)


def parse_basis_codes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen = []
    for part in str(raw).split(","):
        code = part.strip()
        if code and code not in seen and code not in ("OVERTIME", "HOLIDAY_WORK", "WORK_DEFICIT"):
            seen.append(code)
    return tuple(seen)


def overtime_basis_amount(
    method: str,
    calc_mode: str,
    amount: Decimal,
    unit_amount: Decimal | None,
    fixed_days: Decimal | None = None,
) -> Decimal:
    """در روش عدد ثابت، یا وقتی روز مبنا داده شده، آیتم روزشمار با آن تعداد روز می‌آید."""
    days = fixed_days if fixed_days is not None else (
        OVERTIME_BASIS_DAYS if method == METHOD_MONTHLY_DIV else None
    )
    if days is not None and calc_mode in _DAY_BASIS_MODES and unit_amount is not None:
        return D(unit_amount) * D(days)
    return D(amount)


def overtime_pay(
    basis_monthly: Decimal,
    hours: Decimal,
    rule: OvertimeRule,
) -> tuple[Decimal, Decimal, str]:
    """برمی‌گرداند (مبلغ, نرخ ساعت اضافه‌کار, توضیح).

    روش اول: نرخ = جمع آیتم‌های مبنا ÷ عدد ثابت.
    روش دوم: مزد ساعت عادی = جمع مبنا ÷ ساعت عادی ماه، سپس نرخ = مزد ساعت × ضریب.
    مبلغ = نرخ × ساعات اضافه‌کار گزارش حضور.
    """
    basis = D(basis_monthly)
    worked = D(hours)
    if not rule.basis_codes:
        return D(0), D(0), "هیچ آیتمی در مبنای اضافه‌کار انتخاب نشده"
    if rule.method == METHOD_HOURLY_X_FACTOR:
        denom = D(rule.ordinary_month_hours)
        if denom <= 0:
            return D(0), D(0), "ساعت عادی ماه در سیاست صفر است"
        ordinary = basis / denom
        rate = ordinary * D(rule.premium_factor)
        note = (
            f"{worked} ساعت × (({basis} ÷ {denom}) × {rule.premium_factor})"
        )
    else:
        denom = D(rule.divisor)
        if denom <= 0:
            return D(0), D(0), "عدد ثابت تقسیم در سیاست صفر است"
        rate = basis / denom
        note = f"{worked} ساعت × ({basis} ÷ {denom})"
    return money_round(rate * worked), rate, note


def ordinary_hour_pay(
    basis_monthly: Decimal,
    hours: Decimal,
    rule: OvertimeRule,
) -> tuple[Decimal, Decimal, str]:
    """نرخ کسر کار = یک ساعت عادی: جمع مبنا ÷ ساعت عادی ماه، بدون ضریب اضافه‌کار."""
    worked = D(hours)
    if not rule.basis_codes:
        return D(0), D(0), "هیچ آیتمی در مبنای ساعت عادی انتخاب نشده"
    denom = D(rule.ordinary_month_hours)
    if denom <= 0:
        return D(0), D(0), "ساعت عادی ماه در سیاست صفر است"
    rate = D(basis_monthly) / denom
    note = f"{worked} ساعت × ({basis_monthly} ÷ {denom})"
    return money_round(rate * worked), rate, note
