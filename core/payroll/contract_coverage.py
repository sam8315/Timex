"""پوشش قرارداد در ماه حقوق."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

from core.payroll.money import D


def _effective_end(contract_end: Optional[date], actual_end: Optional[date] = None) -> Optional[date]:
    if actual_end is not None:
        return actual_end
    return contract_end


def contract_covered_days(
    month_start: date,
    month_end: date,
    contract_start: date,
    contract_end: Optional[date],
    *,
    actual_end: Optional[date] = None,
) -> int:
    """تعداد روزهای ماه که قرارداد پوشش می‌دهد (شامل ابتدا و انتها)."""
    end = _effective_end(contract_end, actual_end)
    overlap_start = max(month_start, contract_start)
    overlap_end = min(month_end, end) if end is not None else month_end
    if overlap_start > overlap_end:
        return 0
    return (overlap_end - overlap_start).days + 1


def best_contract_coverage(
    month_start: date,
    month_end: date,
    contracts: Sequence[object],
) -> tuple[int, Optional[object]]:
    """بیشترین پوشش میان قراردادها؛ برمی‌گرداند (covered_days, contract)."""
    best_days = 0
    best = None
    for c in contracts:
        start = getattr(c, "start_date")
        end = getattr(c, "end_date", None)
        actual = None
        if hasattr(c, "actual_end_date"):
            try:
                actual = c.actual_end_date
            except Exception:
                actual = end
        days = contract_covered_days(
            month_start, month_end, start, end, actual_end=actual
        )
        if days > best_days:
            best_days = days
            best = c
    return best_days, best


def coverage_ratio(covered_days: int, month_days: int) -> Decimal:
    if month_days <= 0:
        return D(0)
    if covered_days >= month_days:
        return D(1)
    return D(covered_days) / D(month_days)
