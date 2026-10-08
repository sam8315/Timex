"""متن و اعداد نمایش فیش."""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import jdatetime

from core.payroll.money import D

EARNING_DISPLAY_ORDER = (
    "DAILY_WAGE",
    "SENIORITY",
    "HOUSING",
    "WORKER_VOUCHER",
    "MARRIAGE",
    "CHILD_ALLOWANCE",
    "OVERTIME",
    "HOLIDAY_WORK",
    "FRIDAY_WORK",
    "SHIFT",
)
_EARNING_RANK = {code: index for index, code in enumerate(EARNING_DISPLAY_ORDER)}

def payslip_sort_key(item: Any) -> tuple:
    kind = getattr(item, "kind", "")
    code = getattr(item, "component_code", "") or ""
    if kind == "deduction":
        return (2, int(getattr(item, "sort_order", 100) or 100), code)
    if code in _EARNING_RANK:
        return (0, _EARNING_RANK[code], code)
    return (1, int(getattr(item, "sort_order", 100) or 100), code)


def payslip_sort(items):
    return sorted(items, key=payslip_sort_key)


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value: Any) -> str:
    if value is None:
        return ""
    return str(value).translate(_FA_DIGITS)


def money_text(value: Any) -> str:
    """عدد فارسی با جداکننده هزارگان و حداکثر دو رقم اعشار."""
    if value is None or value == "":
        return ""
    number = D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "−" if number < 0 else ""
    number = abs(number)
    whole = int(number)
    frac = int((number - whole) * 100)
    body = f"{whole:,}".replace(",", "٬")
    if frac:
        frac_txt = f"{frac:02d}".rstrip("0")
        body = f"{body}٫{frac_txt}"
    return fa_digits(sign + body)


def jalali_text(value: Any) -> str:
    if not isinstance(value, date):
        return "—"
    return fa_digits(jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d"))


def line_detail(item: Any) -> str:
    """جزئیات هر قلم به صورت یک جمله فارسی، بدون علامت مخلوط‌کننده جهت."""
    code = getattr(item, "component_code", "") or ""
    unit = getattr(item, "unit_amount", None)
    qty = getattr(item, "quantity", None)
    amount = getattr(item, "amount", None)
    note = (getattr(item, "calc_note", None) or "").strip()

    if code in ("INSURANCE_EMPLOYEE", "TAX") and (unit is not None or qty is not None):
        return f"{money_text(unit)} درصد از مبنای {money_text(qty)} ریال"

    if code == "CHILD_ALLOWANCE" and unit is not None and qty is not None:
        return (
            f"{money_text(qty)} فرزند، هر فرزند {money_text(unit)} ریال"
            + _coverage_clause(unit, qty, amount)
        )

    if code == "DAILY_WAGE" and unit is not None and qty is not None:
        return f"هر روز {money_text(unit)} ریال، به مدت {money_text(qty)} روز"

    if code in ("HOUSING", "MARRIAGE", "WORKER_VOUCHER") and unit is not None:
        text = f"مبلغ ماهانه {money_text(unit)} ریال"
        return text + _coverage_clause(unit, qty if qty is not None else 1, amount)

    if code == "SENIORITY" and unit is not None and qty is not None:
        return (
            f"هر روز {money_text(unit)} ریال، به مدت {money_text(qty)} روز"
            + _coverage_clause(unit, qty, amount)
        )

    if code == "WORK_DEFICIT" and qty is not None:
        rate = money_text(unit) if unit is not None else "—"
        return f"{money_text(qty)} ساعت، هر ساعت عادی {rate} ریال"

    if code in ("FRIDAY_WORK", "OVERTIME", "HOLIDAY_WORK") and qty is not None:
        rate = money_text(unit) if unit is not None else "—"
        return f"{money_text(qty)} ساعت، نرخ هر ساعت {rate} ریال"

    if code in ("EIDI", "BONUS") and unit is not None and qty is not None:
        return (
            f"معادل {money_text(qty)} روز، هر روز {money_text(unit)} ریال"
            + _coverage_clause(unit, qty, amount)
        )

    if code == "SHIFT" and unit is not None and qty is not None:
        label = note or "نوبت‌کاری"
        return f"{label}، {money_text(qty)} درصد از مبنای {money_text(unit)} ریال"

    if unit is not None and qty is not None:
        return f"{money_text(unit)} در {money_text(qty)}" + _coverage_clause(unit, qty, amount)

    if code == "SHIFT":
        return "مبلغ واردشده به‌صورت دستی"

    return fa_digits(note)


def _coverage_clause(unit: Any, qty: Any, amount: Optional[Any]) -> str:
    if unit is None or qty is None or amount is None:
        return ""
    product = D(unit) * D(qty)
    if product == 0:
        return ""
    if product.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == D(amount).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ):
        return ""
    ratio = (D(amount) / product).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"، نسبت پوشش {money_text(ratio)}"
