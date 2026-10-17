"""کارمندان فعال که امروز قرارداد پوشش‌دهنده ندارند."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import jdatetime
from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.membership_type import MembershipType


def _jalali(value: date) -> str:
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")


def _missing_reason(contracts: list[Contract], today: date) -> str:
    if not contracts:
        return "بدون قرارداد"

    started = [c for c in contracts if c.start_date <= today]
    if started:
        latest = max(
            started,
            key=lambda c: (c.actual_end_date or date.min, c.start_date, c.id or 0),
        )
        end = latest.actual_end_date
        if end is None:
            return "منقضی"
        return f"منقضی ({_jalali(end)})"

    upcoming = min(contracts, key=lambda c: (c.start_date, c.id or 0))
    return f"هنوز شروع نشده ({_jalali(upcoming.start_date)})"


def list_active_employees_missing_contract(
    db: Session,
    today: date | None = None,
) -> list[dict]:
    """کارمندان فعال بدون قرارداد فعال امروز.

    قرارداد فعال همان Contract.is_active است: شروع شده و یا باز است،
    یا actual_end_date هنوز نرسیده.
    """
    today = today or date.today()
    employees = (
        db.query(Employee)
        .filter(Employee.is_active == True)  # noqa: E712
        .all()
    )
    if not employees:
        return []

    user_ids = [emp.user_id for emp in employees]
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id.in_(user_ids))
        .all()
    )
    by_user: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        by_user[contract.user_id].append(contract)

    rows = []
    for emp in employees:
        owned = by_user.get(emp.user_id, [])
        if any(contract.is_active for contract in owned):
            continue
        rows.append({
            "user_id": emp.user_id,
            "full_name": emp.full_name,
            "reason": _missing_reason(owned, today),
            "profile_url": f"/admin/profile/{emp.user_id}",
            "contract_url": f"/admin/contracts/user/{emp.user_id}",
        })

    rows.sort(key=lambda row: row["full_name"])
    return rows


def list_expiring_contracts(
    db: Session,
    today: date | None = None,
    within_days: int = 30,
) -> list[dict]:
    """قراردادهایی که پایان‌شان در بازه امروز تا within_days روز بعد است.

    همان فیلتر کارت داشبورد: end_date بین امروز و امروز+within_days.
    """
    today = today or date.today()
    deadline = today + timedelta(days=within_days)
    contracts = (
        db.query(Contract)
        .filter(
            Contract.end_date.isnot(None),
            Contract.end_date <= deadline,
            Contract.end_date >= today,
        )
        .order_by(Contract.end_date.asc(), Contract.id.asc())
        .all()
    )
    if not contracts:
        return []

    user_ids = {contract.user_id for contract in contracts}
    employees = (
        db.query(Employee)
        .filter(Employee.user_id.in_(user_ids))
        .all()
    )
    names = {employee.user_id: employee.full_name for employee in employees}

    codes = {contract.contract_type_code for contract in contracts}
    memberships = (
        db.query(MembershipType)
        .filter(MembershipType.code.in_(codes))
        .all()
    )
    type_names = {row.code: row.name for row in memberships}

    rows = []
    for contract in contracts:
        end = contract.end_date
        rows.append({
            "contract_id": contract.id,
            "user_id": contract.user_id,
            "full_name": names.get(contract.user_id) or contract.user_id,
            "contract_type": type_names.get(contract.contract_type_code) or contract.contract_type_code,
            "end_date_j": _jalali(end),
            "days_left": (end - today).days,
            "profile_url": f"/admin/profile/{contract.user_id}",
            "contract_url": f"/admin/contracts/user/{contract.user_id}",
        })
    return rows
