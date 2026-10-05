"""Pure data objects for Annual Leave Entitlement Engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Charge modes (strings only — no DB / membership_semantics import in engine).
CHARGE_MODE_PERMANENT = 'permanent'
CHARGE_MODE_PHYSICIAN = 'physician'
CHARGE_MODE_PRORATE = 'prorate'


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
    charge_mode selects Current Behavior branching (permanent / physician / prorate).
    coverage is a single concrete interval for Current Behavior parity.
    """

    year_j: int
    year_days: int
    year_start_g: date
    year_end_g: date
    as_of_date: date
    membership_code: str
    annual_days: float
    coverage: CoverageInterval
    charge_mode: str = CHARGE_MODE_PRORATE


@dataclass(frozen=True)
class EntitlementResult:
    """Raw entitlement result. No rounding (rounding is mutation-layer)."""

    year_j: int
    raw_amount: float
    covered_days: int
    year_days: int
    membership_code: str
    notes: tuple[str, ...] = ()
