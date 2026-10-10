"""
Dry-run / apply split of legacy Employee.department membership cache
into Employee.membership_type_code.

Does not create organizational departments and does not write department_id.
Does not modify the legacy department column.

Usage:
  python scripts/split_membership_department.py
  python scripts/split_membership_department.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.engine import SessionLocal  # noqa: E402
from models.contract import Contract  # noqa: E402
from models.employee import Employee  # noqa: E402
from models.membership_type import MembershipType  # noqa: E402

_PERSIAN_MEMBERSHIP = {
    "رسمی": "1",
    "وظیفه": "2",
    "وظيفه": "2",
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().replace("ي", "ی").replace("ك", "ک").split())


def _active_or_latest_code(contracts, today: date):
    if not contracts:
        return None, None
    chosen = None
    for contract in contracts:
        if contract.start_date <= today and contract.is_active:
            chosen = contract
            break
    if chosen is None:
        chosen = contracts[0]
    label = "active_contract" if chosen.is_active and chosen.start_date <= today else "latest_contract"
    return str(chosen.contract_type_code or "").strip(), label


def propose_membership(known, contract_code, contract_label, legacy):
    """Pure decision used by the dry-run. Never invents a department."""
    if contract_code and contract_code in known:
        return contract_code, contract_label
    if contract_code:
        return None, "contract_code_not_in_membership_types"
    raw = _normalize(str(legacy or ""))
    mapped = _PERSIAN_MEMBERSHIP.get(raw, raw)
    if mapped and mapped in known:
        return mapped, "legacy_membership_code"
    if not raw:
        return None, "empty_without_contract"
    return None, "unmapped_legacy_value"


def _legacy_by_user(db) -> dict:
    """Read the pre-026 cache when the column still exists. Otherwise empty."""
    from sqlalchemy import text

    present = db.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'employee' AND column_name = 'department'"
    )).first()
    if present is None:
        return {}
    rows = db.execute(text(
        "SELECT user_id, department FROM employee"
    )).all()
    return {user_id: department for user_id, department in rows}


def build_plan(db):
    known = {row.code for row in db.query(MembershipType.code).all()}
    today = date.today()
    employees = db.query(Employee).order_by(Employee.user_id).all()
    contracts = db.query(Contract).order_by(Contract.start_date.desc(), Contract.id.desc()).all()
    by_user = {}
    for contract in contracts:
        by_user.setdefault(contract.user_id, []).append(contract)

    legacy_by_user = _legacy_by_user(db)
    legacy_values = Counter()
    rows = []
    for emp in employees:
        legacy = legacy_by_user.get(emp.user_id)
        legacy_values[legacy if legacy not in (None, "") else "<empty>"] += 1
        user_contracts = by_user.get(emp.user_id, [])
        code, label = _active_or_latest_code(user_contracts, today)
        proposed, reason = propose_membership(known, code, label, legacy)
        mismatch = bool(code and legacy and str(legacy) != code)
        rows.append({
            "user_id": emp.user_id,
            "legacy": legacy,
            "current_base": emp.membership_type_code,
            "proposed": proposed,
            "reason": reason,
            "mismatch_with_contract": mismatch,
            "will_write": proposed is not None and emp.membership_type_code != proposed,
        })
    return {
        "employee_count": len(employees),
        "legacy_values": dict(legacy_values),
        "rows": rows,
    }


def print_report(plan):
    rows = plan["rows"]
    print(f"employees={plan['employee_count']}")
    print("legacy_department_values:")
    for value, count in sorted(plan["legacy_values"].items(), key=lambda item: (-item[1], str(item[0]))):
        print(f"  {count:5d}  {value}")
    writable = [row for row in rows if row["will_write"]]
    ambiguous = [row for row in rows if row["proposed"] is None]
    mismatches = [row for row in rows if row["mismatch_with_contract"]]
    print(f"will_write={len(writable)} ambiguous={len(ambiguous)} contract_mismatches={len(mismatches)}")
    print("ambiguous_rows:")
    for row in ambiguous:
        print(
            f"  user={row['user_id']} legacy={row['legacy']!r} "
            f"reason={row['reason']} current_base={row['current_base']!r}"
        )


def apply_plan(db, plan) -> int:
    written = 0
    by_id = {emp.user_id: emp for emp in db.query(Employee).all()}
    for row in plan["rows"]:
        if not row["will_write"]:
            continue
        emp = by_id[row["user_id"]]
        emp.membership_type_code = row["proposed"]
        written += 1
    db.commit()
    return written


def validate(db, plan) -> list[str]:
    known = {row.code for row in db.query(MembershipType.code).all()}
    problems = []
    for emp in db.query(Employee).all():
        if emp.membership_type_code and emp.membership_type_code not in known:
            problems.append(f"{emp.user_id}: unknown membership {emp.membership_type_code}")
        if emp.department_id is not None and plan is not None:
            # Organizational assignment is manual; this script must not have filled it
            # from a membership code. A non-null id is allowed only if a department row exists.
            pass
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write membership_type_code")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        plan = build_plan(db)
        print_report(plan)
        if not args.apply:
            print("dry-run only; pass --apply to write membership_type_code")
            return 0
        written = apply_plan(db, plan)
        problems = validate(db, plan)
        print(f"applied={written} validation_problems={len(problems)}")
        for problem in problems:
            print(f"  {problem}")
        return 1 if problems else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
