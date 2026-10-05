"""
Pure Annual Leave Entitlement Engine.

Deterministic Current Behavior segment math. No DB, no Session, no date.today(),
no LeaveBalance/Transaction mutation. Branching is by Context.charge_mode
(policy/behavior resolved outside the engine).
"""
from __future__ import annotations

from web.services.leave_entitlement_engine.context import (
    CHARGE_MODE_PERMANENT,
    CHARGE_MODE_PHYSICIAN,
    CHARGE_MODE_PRORATE,
    AnnualLeaveContext,
    EntitlementResult,
)


def compute_annual_entitlement(ctx: AnnualLeaveContext) -> EntitlementResult:
    """
    Compute raw AL entitlement for one membership coverage segment in one Jalali year.

    Current Behavior parity with leave_entitlement_service.charge_amount_for_segment
    when charge_mode matches membership_semantics.charge_mode for that membership.
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
    mode = (ctx.charge_mode or CHARGE_MODE_PRORATE).strip().lower()

    if mode == CHARGE_MODE_PERMANENT:
        if start <= y_start and end >= y_end:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)
    elif mode == CHARGE_MODE_PHYSICIAN:
        if duration >= year_days:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)
    else:
        # prorate and any unknown mode → Current Behavior prorate
        if duration >= year_days:
            raw = annual_days
        else:
            raw = annual_days * (duration / year_days)

    return EntitlementResult(
        year_j=ctx.year_j,
        raw_amount=float(raw),
        covered_days=duration,
        year_days=year_days,
        membership_code=ctx.membership_code,
    )


# Seed-only fallback for DB-free helpers/tests (mirrors SEED_BEHAVIOR_BY_CODE).
# Production callers must pass charge_mode from membership_semantics.charge_mode.
_SEED_CHARGE_MODE_BY_CODE = {
    '1': CHARGE_MODE_PERMANENT,
    '5': CHARGE_MODE_PHYSICIAN,
}


def build_context_for_segment(
    *,
    membership_code: str,
    annual_days: float,
    year_j: int,
    seg_start,
    seg_end,
    as_of_date=None,
    charge_mode: str | None = None,
) -> AnnualLeaveContext:
    """
    Helper to build Context for segment math / parity tests.

    If seg_end is None, uses year end (Current Behavior of charge_amount_for_segment).
    Prefer explicit ``charge_mode`` from Resolver / membership_semantics.
    """
    from web.services.leave_entitlement_engine.calendar import (
        get_jalali_year_days,
        jalali_year_bounds_g,
    )
    from web.services.leave_entitlement_engine.context import CoverageInterval

    y_start, y_end = jalali_year_bounds_g(year_j)
    end = y_end if seg_end is None else seg_end
    as_of = as_of_date if as_of_date is not None else y_start
    mode = (
        charge_mode
        if charge_mode is not None
        else _SEED_CHARGE_MODE_BY_CODE.get(
            str(membership_code), CHARGE_MODE_PRORATE
        )
    )
    return AnnualLeaveContext(
        year_j=year_j,
        year_days=get_jalali_year_days(year_j),
        year_start_g=y_start,
        year_end_g=y_end,
        as_of_date=as_of,
        membership_code=membership_code,
        annual_days=float(annual_days),
        coverage=CoverageInterval(start=seg_start, end=end),
        charge_mode=mode,
    )
