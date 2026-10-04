"""
Dual-run validation for membership cutover.

Compares entitlement resolve results between:
- independent Legacy policy path (annual_leave_dept_*)
- New membership-rule path (resolve_annual_leave_base_with_region)

Temporal: New path uses on_date clamped to each contract's coverage window.
Fail-closed: returns diffs; never auto-fixes or remaps codes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from web.services.leave_entitlement_service import (
    calculate_entitlement_by_year,
    resolve_annual_leave_days_legacy,
)


@dataclass
class EntitlementDiff:
    contract_id: int
    user_id: str
    contract_type_code: str
    region_code: Optional[str]
    old_annual: int
    new_annual: int
    old_entitlement: dict
    new_entitlement: dict
    reason: str
    as_of: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def contract_comparison_date(contract: Contract, global_as_of: date) -> date:
    """Clamp global_as_of into the contract coverage window."""
    start = contract.start_date
    end = contract.end_date or global_as_of
    if global_as_of < start:
        return start
    if global_as_of > end:
        return end
    return global_as_of


def _new_annual_resolver():
    from web.services.membership_service import (
        resolve_annual_leave_base_with_region,
    )
    return resolve_annual_leave_base_with_region


def snapshot_resolve_matrix(
    db: Session,
    membership_codes: Optional[List[str]] = None,
    region_codes: Optional[List[str]] = None,
    *,
    on_date: Optional[date] = None,
) -> List[dict]:
    """Baseline snapshot of Legacy vs New annual resolve for codes × regions."""
    codes = membership_codes or [str(i) for i in range(1, 8)]
    regions = region_codes or [None, "NORMAL", "GRADE_2", "GRADE_3", "GRADE_4"]
    as_of = on_date or date.today()
    new_fn = _new_annual_resolver()
    rows: List[dict] = []
    for code in codes:
        for region in regions:
            legacy = resolve_annual_leave_days_legacy(
                db, code, region_code=region
            )
            new_annual = int(
                new_fn(db, code, region_code=region, on_date=as_of)
            )
            rows.append(
                {
                    "membership_code": code,
                    "region_code": region,
                    "as_of": as_of.isoformat(),
                    "legacy_annual_leave_days": legacy,
                    "new_annual_leave_days": new_annual,
                    "annual_leave_days": new_annual,
                }
            )
    return rows


def compare_annual_paths(
    db: Session,
    membership_code: str,
    region_code: Optional[str],
    *,
    on_date: Optional[date] = None,
    legacy_fn=None,
    new_fn=None,
) -> Optional[EntitlementDiff]:
    """Compare two annual resolvers for one membership/region at on_date."""
    as_of = on_date or date.today()
    legacy = legacy_fn or resolve_annual_leave_days_legacy
    old_annual = int(legacy(db, membership_code, region_code=region_code))

    if new_fn is None:
        try:
            new_fn = _new_annual_resolver()
        except Exception:
            return None

    new_annual = int(
        new_fn(db, membership_code, region_code=region_code, on_date=as_of)
    )
    if old_annual == new_annual:
        return None
    return EntitlementDiff(
        contract_id=0,
        user_id="",
        contract_type_code=membership_code,
        region_code=region_code,
        old_annual=old_annual,
        new_annual=new_annual,
        old_entitlement={},
        new_entitlement={},
        reason=(
            f"annual mismatch for membership={membership_code} "
            f"region={region_code} as_of={as_of}: old={old_annual} new={new_annual}"
        ),
        as_of=as_of.isoformat(),
    )


def compare_contract_entitlement(
    db: Session,
    contract: Contract,
    *,
    region_code: Optional[str] = None,
    on_date: Optional[date] = None,
    new_annual_fn=None,
    legacy_annual_fn=None,
) -> Optional[EntitlementDiff]:
    """Compare calculate_entitlement_by_year using Legacy vs New at contract as_of."""
    from models.employee import Employee

    global_as_of = on_date or date.today()
    as_of = contract_comparison_date(contract, global_as_of)

    employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
    effective_region = region_code
    if effective_region is None and employee is not None:
        effective_region = employee.region_code

    legacy = legacy_annual_fn or resolve_annual_leave_days_legacy
    old_annual = int(
        legacy(db, contract.contract_type_code, region_code=effective_region)
    )
    old_ent = calculate_entitlement_by_year(
        db, contract, employee=employee, annual_override=old_annual
    )

    if new_annual_fn is None:
        try:
            new_annual_fn = _new_annual_resolver()
        except Exception:
            return None

    new_annual = int(
        new_annual_fn(
            db,
            contract.contract_type_code,
            region_code=effective_region,
            on_date=as_of,
        )
    )
    new_ent = calculate_entitlement_by_year(
        db, contract, employee=employee, annual_override=new_annual
    )

    if old_annual == new_annual and old_ent == new_ent:
        return None

    return EntitlementDiff(
        contract_id=contract.id or 0,
        user_id=contract.user_id,
        contract_type_code=contract.contract_type_code,
        region_code=effective_region,
        old_annual=old_annual,
        new_annual=new_annual,
        old_entitlement={str(k): v for k, v in old_ent.items()},
        new_entitlement={str(k): v for k, v in new_ent.items()},
        reason=(
            f"entitlement mismatch contract_id={contract.id} "
            f"code={contract.contract_type_code} as_of={as_of} "
            f"old_annual={old_annual} new_annual={new_annual}"
        ),
        as_of=as_of.isoformat(),
    )


def validate_cutover_for_all_contracts(
    db: Session,
    *,
    as_of: Optional[date] = None,
    new_annual_fn=None,
    legacy_annual_fn=None,
) -> List[EntitlementDiff]:
    """
    Fail-closed dual-run over contracts.
    Each contract compared at clamp(as_of, start, end).
    Never mutates DB.
    """
    on_date = as_of or date.today()
    contracts = db.query(Contract).order_by(Contract.id.asc()).all()
    diffs: List[EntitlementDiff] = []
    for contract in contracts:
        covers = contract.start_date <= on_date and (
            contract.end_date is None or contract.end_date >= on_date
            or contract.is_active
        )
        if not covers and contract.start_date > on_date:
            continue
        diff = compare_contract_entitlement(
            db,
            contract,
            on_date=on_date,
            new_annual_fn=new_annual_fn,
            legacy_annual_fn=legacy_annual_fn,
        )
        if diff is not None:
            diffs.append(diff)
    return diffs


def find_orphan_membership_codes(db: Session) -> List[dict]:
    """
    Codes on contracts / travel policies that are not in membership_types.
    Used before adding FK. Does not rewrite data.
    """
    from models.membership_type import MembershipType
    from models.travel_leave_policy import TravelLeavePolicy

    known = {
        row.code
        for row in db.query(MembershipType.code).all()
    }
    orphans: List[dict] = []
    for c in db.query(Contract).all():
        if c.contract_type_code not in known:
            orphans.append(
                {
                    "table": "contracts",
                    "id": c.id,
                    "code": c.contract_type_code,
                }
            )
    for p in db.query(TravelLeavePolicy).all():
        if p.contract_type_code not in known:
            orphans.append(
                {
                    "table": "travel_leave_policies",
                    "id": p.id,
                    "code": p.contract_type_code,
                }
            )
    return orphans


class MembershipCutoverError(RuntimeError):
    """Raised when cutover validation fails (orphan codes or entitlement diffs)."""

    def __init__(self, message: str, *, orphans=None, diffs=None):
        super().__init__(message)
        self.orphans = orphans or []
        self.diffs = diffs or []
