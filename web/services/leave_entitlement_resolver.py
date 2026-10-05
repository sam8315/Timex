"""
Phase 2 DB Resolver: Existing Timex data → AnnualLeaveContext → Pure Engine.

Read-only. No LeaveBalance/Transaction mutation, no region sync, no policy seed,
no Contract rewrite. Current Behavior compatible (not Target Rule cutover).

Compatibility notes (Current Behavior couplings deliberately NOT copied):
1. Production ``split_contract_coverage_by_year`` uses ``jdatetime.date.today().year``.
   This Resolver takes explicit ``year_j``.
2. Production ``resolve_annual_leave_base`` defaults ``on_date`` to ``date.today()``.
   This Resolver requires ``as_of_date`` for live annual resolve.
3. Production charge uses contract ``annual_leave_days`` snapshot; live resolve /
   permanent history use MembershipTypeRule (+ region). Both modes are available
   via ``annual_source`` ('live' default / 'snapshot').
4. Contract create syncs ESL → ``Employee.region_code`` before snapshotting annual.
   This Resolver never writes; live annual uses stored ``employee.region_code``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Literal, Optional, Tuple

from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.membership_type_rule import MembershipTypeRule
from web.services import membership_semantics as msem
from web.services.leave_entitlement_engine.calendar import (
    get_jalali_year_days,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_engine.context import (
    AnnualLeaveContext,
    CoverageInterval,
)
from web.services.leave_entitlement_service import (
    contract_effective_end,
    resolve_annual_leave_days_legacy,
    resolve_membership_code_for_policy,
)

AnnualSource = Literal['live', 'snapshot']


def _has_membership_rule(db: Session, membership_code: str) -> bool:
    """Same gate as leave_entitlement_service.resolve_annual_leave_days."""
    return (
        db.query(MembershipTypeRule.id)
        .filter(MembershipTypeRule.membership_type_code == membership_code)
        .first()
        is not None
    )


def _coverage_mode(db: Optional[Session], membership_code: str) -> str:
    if db is not None:
        return msem.coverage_mode(db, membership_code)
    from web.services.membership_semantics import SEED_BEHAVIOR_BY_CODE
    from models.membership_type import (
        BEHAVIOR_CONSCRIPT,
        BEHAVIOR_PERMANENT,
        BEHAVIOR_STANDARD_PRORATE,
    )

    profile = SEED_BEHAVIOR_BY_CODE.get(str(membership_code), BEHAVIOR_STANDARD_PRORATE)
    if profile == BEHAVIOR_PERMANENT:
        return msem.COVERAGE_OPEN_YEAR
    if profile == BEHAVIOR_CONSCRIPT:
        return msem.COVERAGE_ACTUAL_END
    return msem.COVERAGE_CONTRACT_END


def coverage_for_contract_year(
    contract: Contract,
    year_j: int,
    db: Optional[Session] = None,
) -> Optional[Tuple[date, date]]:
    """
    Current Behavior coverage for an explicit Jalali year.

    Mirrors ``split_contract_coverage_by_year`` modes, but uses ``year_j``
    instead of ``jdatetime.date.today().year``.
    """
    code = contract.contract_type_code
    start_g = contract.start_date
    y_start, y_end = jalali_year_bounds_g(year_j)

    if start_g > y_end:
        return None

    mode = _coverage_mode(db, code)

    if mode == msem.COVERAGE_OPEN_YEAR:
        if contract.end_date is not None and contract.end_date < y_start:
            return None
        seg_start = max(start_g, y_start)
        return seg_start, y_end

    if mode == msem.COVERAGE_ACTUAL_END:
        end_g = contract_effective_end(contract)
        if end_g is None:
            seg_start = max(start_g, y_start)
            return seg_start, y_end
        if end_g < start_g or end_g < y_start:
            return None
        seg_start = max(start_g, y_start)
        seg_end = min(end_g, y_end)
        if seg_start <= seg_end:
            return seg_start, seg_end
        return None

    # contract_end (standard_prorate / physician)
    end_g = contract.end_date
    if end_g is None:
        seg_start = max(start_g, y_start)
        return seg_start, y_end

    if end_g < start_g or end_g < y_start:
        return None
    seg_start = max(start_g, y_start)
    seg_end = min(end_g, y_end)
    if seg_start <= seg_end:
        return seg_start, seg_end
    return None


def _resolve_live_annual_days(
    db: Session,
    membership_code: str,
    region_code: Optional[str],
    as_of_date: date,
) -> float:
    policy_code = resolve_membership_code_for_policy(membership_code)
    if _has_membership_rule(db, policy_code):
        from web.services.membership_service import (
            resolve_annual_leave_base_with_region,
        )

        return float(
            resolve_annual_leave_base_with_region(
                db,
                policy_code,
                region_code=region_code,
                on_date=as_of_date,
            )
        )
    return float(
        resolve_annual_leave_days_legacy(db, policy_code, region_code=region_code)
    )


def resolve_annual_leave_context_for_contract(
    db: Session,
    contract: Contract,
    year_j: int,
    *,
    as_of_date: date,
    annual_source: AnnualSource = 'live',
) -> Optional[AnnualLeaveContext]:
    """
    Build a single immutable AnnualLeaveContext for one contract / Jalali year.

    Returns None when Current Behavior coverage for ``year_j`` is empty.
    """
    if as_of_date is None:
        raise ValueError('as_of_date is required for deterministic resolve')
    if annual_source not in ('live', 'snapshot'):
        raise ValueError("annual_source must be 'live' or 'snapshot'")

    coverage = coverage_for_contract_year(contract, year_j, db=db)
    if coverage is None:
        return None

    seg_start, seg_end = coverage
    membership_code = resolve_membership_code_for_policy(contract.contract_type_code)

    if annual_source == 'snapshot':
        annual_days = float(contract.annual_leave_days)
    else:
        employee = (
            db.query(Employee)
            .filter(Employee.user_id == contract.user_id)
            .first()
        )
        region_code = employee.region_code if employee else None
        annual_days = _resolve_live_annual_days(
            db, membership_code, region_code, as_of_date
        )

    y_start, y_end = jalali_year_bounds_g(year_j)
    return AnnualLeaveContext(
        year_j=year_j,
        year_days=get_jalali_year_days(year_j),
        year_start_g=y_start,
        year_end_g=y_end,
        as_of_date=as_of_date,
        membership_code=membership_code,
        annual_days=annual_days,
        coverage=CoverageInterval(start=seg_start, end=seg_end),
        charge_mode=msem.charge_mode(db, membership_code),
    )


def resolve_annual_leave_contexts(
    db: Session,
    user_id: str,
    year_j: int,
    *,
    as_of_date: date,
    annual_source: AnnualSource = 'live',
) -> List[AnnualLeaveContext]:
    """
    One Context per contract with non-empty Current Behavior coverage in year_j.

    Order: contract start_date ascending, then id ascending (stable).
    Does not invent Target Rule union coverage.
    """
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.asc(), Contract.id.asc())
        .all()
    )
    contexts: List[AnnualLeaveContext] = []
    for contract in contracts:
        ctx = resolve_annual_leave_context_for_contract(
            db,
            contract,
            year_j,
            as_of_date=as_of_date,
            annual_source=annual_source,
        )
        if ctx is not None:
            contexts.append(ctx)
    return contexts


def membership_rule_timeline_for_year(
    db: Session,
    membership_code: str,
    year_j: int,
) -> List[Tuple[date, date, MembershipTypeRule]]:
    """
    Inclusive Gregorian intervals inside Jalali ``year_j`` for each Rule
    version that applies. Read-only; no Target Rule invention.

    If no rules exist, returns empty list (caller falls back to single-slice).
    """
    y_start, y_end = jalali_year_bounds_g(year_j)
    code = resolve_membership_code_for_policy(membership_code)
    rules = (
        db.query(MembershipTypeRule)
        .filter(
            MembershipTypeRule.membership_type_code == code,
            MembershipTypeRule.status.in_(('active', 'superseded', 'scheduled')),
            MembershipTypeRule.effective_from <= y_end,
        )
        .order_by(MembershipTypeRule.effective_from.asc())
        .all()
    )
    if not rules:
        return []

    # Clip to year; each rule applies until the day before the next rule.
    intervals: List[Tuple[date, date, MembershipTypeRule]] = []
    for idx, rule in enumerate(rules):
        start = max(y_start, rule.effective_from)
        if idx + 1 < len(rules):
            next_from = rules[idx + 1].effective_from
            end = min(y_end, next_from - timedelta(days=1))
        else:
            end = y_end
        if end < start:
            continue
        intervals.append((start, end, rule))
    return intervals


def resolve_sliced_contexts_for_contract(
    db: Session,
    contract: Contract,
    year_j: int,
    *,
    as_of_date: date,
) -> List[AnnualLeaveContext]:
    """
    Target-ready: split contract coverage by MembershipTypeRule effective dates
    and build one Context per non-empty intersection (live annual per slice).

    Does **not** replace Current Behavior snapshot charge path.
    Empty when base coverage is empty.
    """
    base = coverage_for_contract_year(contract, year_j, db=db)
    if base is None:
        return []
    cov_start, cov_end = base
    membership_code = resolve_membership_code_for_policy(contract.contract_type_code)
    timeline = membership_rule_timeline_for_year(db, membership_code, year_j)
    charge = msem.charge_mode(db, membership_code)
    y_start, y_end = jalali_year_bounds_g(year_j)
    year_days = get_jalali_year_days(year_j)

    employee = (
        db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    )
    region_code = employee.region_code if employee else None

    if not timeline:
        # Single live slice — same as Current Behavior live resolve
        ctx = resolve_annual_leave_context_for_contract(
            db,
            contract,
            year_j,
            as_of_date=as_of_date,
            annual_source='live',
        )
        return [ctx] if ctx is not None else []

    slices: List[AnnualLeaveContext] = []
    for slice_start, slice_end, rule in timeline:
        seg_start = max(cov_start, slice_start)
        seg_end = min(cov_end, slice_end)
        if seg_end < seg_start:
            continue
        # Live annual as-of slice start (region + effective rule via existing resolver)
        annual_days = float(
            _resolve_live_annual_days(
                db, membership_code, region_code, max(as_of_date, slice_start)
            )
        )
        slices.append(
            AnnualLeaveContext(
                year_j=year_j,
                year_days=year_days,
                year_start_g=y_start,
                year_end_g=y_end,
                as_of_date=as_of_date,
                membership_code=membership_code,
                annual_days=annual_days,
                coverage=CoverageInterval(start=seg_start, end=seg_end),
                charge_mode=charge,
            )
        )
    return slices
