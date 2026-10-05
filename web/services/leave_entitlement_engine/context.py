"""Pure data objects for Annual Leave Entitlement Engine (Phase 1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CoverageInterval:
    """Inclusive Gregorian coverage interval already resolved by caller."""

    start: date
    end: date


@dataclass(frozen=True)
class AnnualLeaveContext:
    """
    Input to the Pure Engine.

    annual_days must already be resolved by the caller (Policy/Region/snapshot).
    coverage is a single concrete interval for Phase 1 parity with
    charge_amount_for_segment.
    """

    year_j: int
    year_days: int
    year_start_g: date
    year_end_g: date
    as_of_date: date
    membership_code: str
    annual_days: float
    coverage: CoverageInterval


@dataclass(frozen=True)
class EntitlementResult:
    """Raw entitlement result. No rounding (rounding is mutation-layer Current Behavior)."""

    year_j: int
    raw_amount: float
    covered_days: int
    year_days: int
    membership_code: str
    notes: tuple[str, ...] = ()
