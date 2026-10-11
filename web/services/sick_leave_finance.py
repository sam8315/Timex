"""سابقه مرخصی و دستور مالی. نتیجه حقوق تا اعمال صریح عوض نمی‌شود."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import jdatetime
from sqlalchemy.orm import Session

from models.leave_financial_order import LeaveFinancialOrder
from models.leave_request import LeaveRequest
from models.leave_request_audit import LeaveRequestAudit
from models.payroll import PayrollPeriod, PayrollResult, PayrollRun


def snapshot_leave(leave: LeaveRequest) -> dict:
    return {
        "id": leave.id,
        "user_id": leave.user_id,
        "leave_type": leave.leave_type,
        "from_date": leave.from_date.isoformat() if leave.from_date else None,
        "to_date": leave.to_date.isoformat() if leave.to_date else None,
        "days_count": leave.days_count,
        "status": leave.status,
        "employer_pays_wages": leave.employer_pays_wages,
    }


def write_leave_audit(
    db: Session,
    leave: LeaveRequest,
    action: str,
    before: Optional[dict],
    after: Optional[dict],
    actor: Optional[str],
    reason: Optional[str] = None,
) -> LeaveRequestAudit:
    row = LeaveRequestAudit(
        leave_request_id=leave.id,
        action=action,
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
        actor=actor,
        reason=reason,
    )
    db.add(row)
    return row


def _months_in_range(start, end) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    cursor = start
    from datetime import timedelta
    while cursor <= end:
        j = jdatetime.date.fromgregorian(date=cursor)
        key = (j.year, j.month)
        if key not in seen:
            seen.add(key)
            months.append(key)
        cursor += timedelta(days=1)
    return months


def queue_financial_orders(
    db: Session,
    leave: LeaveRequest,
    order_type: str,
    actor: Optional[str],
    reason: Optional[str] = None,
    date_from=None,
    date_to=None,
) -> list[LeaveFinancialOrder]:
    """برای هر اجرای حقوق موجود که این بازه را پوشش می‌دهد یک دستور معلق می‌سازد."""
    if leave.id is None:
        return []
    start = date_from or leave.from_date
    end = date_to or leave.to_date
    if start is None or end is None:
        return []
    created: list[LeaveFinancialOrder] = []
    for year_j, month_j in _months_in_range(start, end):
        runs = (
            db.query(PayrollRun)
            .join(PayrollPeriod, PayrollRun.period_id == PayrollPeriod.id)
            .join(PayrollResult, PayrollResult.run_id == PayrollRun.id)
            .filter(
                PayrollPeriod.year_j == year_j,
                PayrollPeriod.month_j == month_j,
                PayrollResult.user_id == leave.user_id,
            )
            .all()
        )
        for run in runs:
            existing = (
                db.query(LeaveFinancialOrder)
                .filter(
                    LeaveFinancialOrder.leave_request_id == leave.id,
                    LeaveFinancialOrder.run_id == run.id,
                    LeaveFinancialOrder.status == "pending",
                )
                .first()
            )
            if existing is not None:
                continue
            resolution = "recalc" if run.status in ("draft", "calculated") else "unspecified"
            order = LeaveFinancialOrder(
                leave_request_id=leave.id,
                user_id=leave.user_id,
                order_type=order_type,
                year_j=year_j,
                month_j=month_j,
                run_id=run.id,
                resolution=resolution,
                status="pending",
                actor=actor,
                reason=reason,
            )
            db.add(order)
            created.append(order)
    if created:
        write_leave_audit(
            db,
            leave,
            "financial_order",
            None,
            {"orders": len(created), "order_type": order_type},
            actor,
            reason,
        )
    return created


def orders_for_request(db: Session, leave_request_id: int) -> list[LeaveFinancialOrder]:
    return (
        db.query(LeaveFinancialOrder)
        .filter(LeaveFinancialOrder.leave_request_id == leave_request_id)
        .order_by(LeaveFinancialOrder.id.desc())
        .all()
    )


def pending_orders_for_period(
    db: Session, year_j: int, month_j: int
) -> list[LeaveFinancialOrder]:
    return (
        db.query(LeaveFinancialOrder)
        .filter(
            LeaveFinancialOrder.year_j == year_j,
            LeaveFinancialOrder.month_j == month_j,
            LeaveFinancialOrder.status == "pending",
        )
        .order_by(LeaveFinancialOrder.id)
        .all()
    )


def choose_resolution(
    db: Session,
    order_id: int,
    resolution: str,
    actor: Optional[str],
    reason: str,
) -> LeaveFinancialOrder:
    if resolution not in ("recalc", "next_period", "reopen"):
        raise ValueError("مسیر اصلاح مالی نامعتبر است")
    if not (reason or "").strip():
        raise ValueError("دلیل اعمال اثر مالی الزامی است")
    order = db.query(LeaveFinancialOrder).filter(LeaveFinancialOrder.id == order_id).first()
    if order is None:
        raise ValueError("دستور مالی یافت نشد")
    if order.status != "pending":
        raise ValueError("این دستور قبلاً اعمال یا رد شده است")
    order.resolution = resolution
    order.reason = reason.strip()
    order.actor = actor
    db.flush()
    return order


def mark_applied(
    db: Session,
    order: LeaveFinancialOrder,
    actor: Optional[str],
    before_amounts: Optional[dict] = None,
    after_amounts: Optional[dict] = None,
) -> None:
    order.status = "applied"
    order.applied_at = datetime.now(timezone.utc)
    order.applied_by = actor
    if before_amounts is not None:
        order.before_amounts_json = json.dumps(before_amounts, ensure_ascii=False)
    if after_amounts is not None:
        order.after_amounts_json = json.dumps(after_amounts, ensure_ascii=False)


def carry_deltas_for_user(
    db: Session, user_id: str, year_j: int, month_j: int
) -> tuple[dict[str, dict], list[LeaveFinancialOrder]]:
    """دلتاهای دوره بعد که هنوز روی این ماه اعمال نشده‌اند."""
    orders = (
        db.query(LeaveFinancialOrder)
        .filter(
            LeaveFinancialOrder.user_id == user_id,
            LeaveFinancialOrder.year_j == year_j,
            LeaveFinancialOrder.month_j == month_j,
            LeaveFinancialOrder.resolution == "next_period",
            LeaveFinancialOrder.status == "pending",
        )
        .all()
    )
    merged: dict[str, dict] = {}
    for order in orders:
        if not order.after_amounts_json:
            continue
        payload = json.loads(order.after_amounts_json)
        for code, item in payload.items():
            delta = Decimal(str(item.get("delta", "0")))
            current = merged.get(code)
            if current is None:
                merged[code] = {
                    "delta": delta,
                    "kind": item.get("kind") or "earning",
                    "name": item.get("name") or code,
                }
            else:
                current["delta"] = Decimal(current["delta"]) + delta
    return merged, orders


def result_amount_map(result: Optional[PayrollResult]) -> dict[str, str]:
    if result is None:
        return {}
    return {
        item.component_code: str(item.amount)
        for item in (result.items or [])
    }
