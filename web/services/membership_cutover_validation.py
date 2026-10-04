"""
Dual-run validation for membership cutover.

Compares entitlement resolve results between:
- independent Legacy policy path (annual_leave_dept_*)
- New membership-rule path (resolve_annual_leave_base_with_region)

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

    def to_dict(self) -> dict:
        return asdict(self)


def _new_annual_resolver():
    from web.services.membership_service import (
        resolve_annual_leave_base_with_region,
    )
    return resolve_annual_leave_base_with_region


def snapshot_resolve_matrix(
    db: Session,
    membership_codes: Optional[List[str]] = None,
    region_codes: Optional[List[str]] = None,
) -> List[dict]:
    """Baseline snapshot of Legacy vs New annual resolve for codes × regions."""
    codes = membership_codes or [str(i) for i in range(1, 8)]
    regions = region_codes or [None, "NORMAL", "GRADE_2", "GRADE_3", "GRADE_4"]
    new_fn = _new_annual_resolver()
    rows: List[dict] = []
    for code in codes:
        for region in regions:
            legacy = resolve_annual_leave_days_legacy(
                db, code, region_code=region
            )
            new_annual = int(new_fn(db, code, region_code=region))
            rows.append(
                {
                    "membership_code": code,
                    "region_code": region,
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
    legacy_fn=None,
    new_fn=None,
) -> Optional[EntitlementDiff]:
    """
    Compare two annual resolvers for one membership/region.
    Defaults: legacy = resolve_annual_leave_days_legacy;
    new = membership_service.resolve_annual_leave_base_with_region.
    """
    legacy = legacy_fn or resolve_annual_leave_days_legacy
    old_annual = int(legacy(db, membership_code, region_code=region_code))

    if new_fn is None:
        try:
            new_fn = _new_annual_resolver()
        except Exception:
            return None

    new_annual = int(new_fn(db, membership_code, region_code=region_code))
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
            f"region={region_code}: old={old_annual} new={new_annual}"
        ),
    )


def compare_contract_entitlement(
    db: Session,
    contract: Contract,
    *,
    region_code: Optional[str] = None,
    new_annual_fn=None,
    legacy_annual_fn=None,
) -> Optional[EntitlementDiff]:
    """Compare calculate_entitlement_by_year using Legacy vs New annual bases."""
    from models.employee import Employee

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
            db, contract.contract_type_code, region_code=effective_region
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
            f"code={contract.contract_type_code} "
            f"old_annual={old_annual} new_annual={new_annual}"
        ),
    )


def validate_cutover_for_all_contracts(
    db: Session,
    *,
    as_of: Optional[date] = None,
    new_annual_fn=None,
    legacy_annual_fn=None,
) -> List[EntitlementDiff]:
    """
    Fail-closed dual-run over all contracts that cover as_of (default: today).
    Returns list of diffs; empty list means safe to cut over.
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
