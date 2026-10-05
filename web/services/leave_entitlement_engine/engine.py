"""
Pure Annual Leave Entitlement Engine.

Phase 1: independent reimplementation of Current Behavior segment math
matching leave_entitlement_service.charge_amount_for_segment.

No DB, no Session, no date.today(), no LeaveBalance/Transaction mutation.
"""
from __future__ import annotations

from web.services.leave_entitlement_engine.context import (
    AnnualLeaveContext,
    EntitlementResult,
)

# Membership codes mirrored as literals to avoid coupling engine purity to
# production imports beyond what is needed. Values match leave_glossary.
_MEMBERSHIP_PERMANENT = '1'
_MEMBERSHIP_PHYSICIAN = '5'


def compute_annual_entitlement(ctx: AnnualLeaveContext) -> EntitlementResult:
    """
    Compute raw AL entitlement for one membership coverage segment in one Jalali year.

    Current Behavior parity: same branching and formula as
    charge_amount_for_segment(membership_code, annual_days, year_j, seg_start, seg_end).
    """
    y_start = ctx.year_start_g
    y_end = ctx.year_end_g
    year_days = ctx.year_days

    seg_start = ctx.coverage.start
    seg_end = ctx.coverage.end

    start = max(seg_start, y_start)
    end = min(seg_end, y_end)
    if end < start:
        return EntitlementResult(
            year_j=ctx.year_j,
            raw_amount=0.0,
            covered_days=0,
            year_days=year_days,
            membership_code=ctx.membership_code,
            notes=('empty_coverage',),
        )

    duration = (end - start).days + 1
    annual_days = float(ctx.annual_days)
    code = ctx.membership_code

    if code == _MEMBERSHIP_PERMANENT:
        if start <= y_start and end >= y_end:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)
    elif code == _MEMBERSHIP_PHYSICIAN:
        if duration >= year_days:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)
    else:
        # Contractual, conscript, purchased-service, other — Current Behavior
        if duration >= year_days:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)

    return EntitlementResult(
        year_j=ctx.year_j,
        raw_amount=float(raw),
        covered_days=duration,
        year_days=year_days,
        membership_code=code,
    )


def build_context_for_segment(
    *,
    membership_code: str,
    annual_days: float,
    year_j: int,
    seg_start,
    seg_end,
    as_of_date=None,
) -> AnnualLeaveContext:
    """
    Helper to build Context for parity tests against charge_amount_for_segment.

    If seg_end is None, uses year end (Current Behavior of charge_amount_for_segment).
    """
    from web.services.leave_entitlement_engine.calendar import (
        get_jalali_year_days,
        jalali_year_bounds_g,
    )
    from web.services.leave_entitlement_engine.context import CoverageInterval

    y_start, y_end = jalali_year_bounds_g(year_j)
    end = y_end if seg_end is None else seg_end
    as_of = as_of_date if as_of_date is not None else y_start
    return AnnualLeaveContext(
        year_j=year_j,
        year_days=get_jalali_year_days(year_j),
        year_start_g=y_start,
        year_end_g=y_end,
        as_of_date=as_of,
        membership_code=membership_code,
        annual_days=float(annual_days),
        coverage=CoverageInterval(start=seg_start, end=end),
    )
