"""فوق‌العاده جمعه‌کاری. درصد، اقلام مبنا و نوع‌های حذف‌شده داخل موتور ثابت نیستند."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from core.payroll.money import D
from core.payroll.night import DEFAULT_EXCLUDED, night_premium, parse_excluded_patterns
from core.payroll.overtime import overtime_basis_amount

FRIDAY_BASIS_DAYS = D(30)


@dataclass(frozen=True)
class FridayRule:
    premium_percent: Decimal = D("96")
    basis_codes: tuple[str, ...] = ("DAILY_WAGE",)
    excluded_patterns: tuple[str, ...] = DEFAULT_EXCLUDED


def parse_friday_basis_codes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen: list[str] = []
    for part in str(raw).split(","):
        code = part.strip()
        if code and code not in seen and code not in ("FRIDAY_WORK", "WORK_DEFICIT"):
            seen.append(code)
    return tuple(seen)


def friday_hourly(
    components: Sequence,
    lines: Sequence,
    basis_codes: tuple[str, ...],
    hours_per_day: Decimal,
) -> Decimal:
    """جمع مبلغ ماهانه اقلام مبنا (روزانه و سنوات با ۳۰ روز) تقسیم بر ساعت روز ضربدر ۳۰."""
    denom = D(hours_per_day) * FRIDAY_BASIS_DAYS
    if denom <= 0 or not basis_codes:
        return D(0)
    modes = {c.code: c.calc_mode for c in components}
    codes = set(basis_codes)
    monthly = sum(
        (
            overtime_basis_amount(
                "monthly_div",
                modes.get(ln.component_code, ""),
                ln.amount,
                ln.unit_amount,
                FRIDAY_BASIS_DAYS,
            )
            for ln in lines
            if getattr(ln, "kind", "") == "earning" and ln.component_code in codes
        ),
        D(0),
    )
    return monthly / denom


def friday_pay(hourly: Decimal, hours: Decimal, percent: Decimal) -> Decimal:
    return night_premium(hourly, hours, percent)


__all__ = [
    "DEFAULT_EXCLUDED",
    "FridayRule",
    "friday_hourly",
    "friday_pay",
    "parse_excluded_patterns",
    "parse_friday_basis_codes",
]
