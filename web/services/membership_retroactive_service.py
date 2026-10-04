"""
Workflow Rule گذشته‌نگر: preview → confirm → activate pending → recalculate.

Preview بدون اثر runtime؛ Confirm ابتدا Rule را active می‌کند سپس leave را به‌روز می‌کند.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.contract import Contract
from models.employee import Employee
from models.membership_rule_change import (
    MembershipRuleChangeAudit,
    MembershipRuleChangeRequest,
)
from models.membership_type_rule import MembershipTypeRule
from web.services.leave_entitlement_service import calculate_entitlement_by_year
from web.services.leave_service import update_leave_for_contract
from web.services.membership_service import (
    MembershipError,
    activate_pending_rule,
    get_effective_rule,
    resolve_annual_leave_base_with_region,
)


SAMPLE_LIMIT = 10


def _annual_from_rule_base(
    db: Session,
    membership_type_code: str,
    rule: MembershipTypeRule,
    region_code,
) -> int:
    """New value for preview: pending rule base + region policy layer (without activating)."""
    base = max(0, int(rule.annual_leave_base))
    from web.services.membership_service import _get_leave_policy, _region_applies, _get_policy_param
    from models.region import Region

    policy = _get_leave_policy(db)
    if not policy or not _region_applies(db, policy.id, membership_type_code):
        return base
    if not region_code:
        return base
    region = db.query(Region).filter(Region.code == region_code).first()
    if region is None:
        return base
    region_days = int(region.default_annual_leave_days)
    scoped = _get_policy_param(
        db, policy.id, "annual_leave_days", region_code=region_code
    )
    if scoped and scoped.parameter_value is not None:
        try:
            region_days = int(float(scoped.parameter_value))
        except (TypeError, ValueError):
            pass
    return max(0, region_days)


def build_impact_preview(
    db: Session,
    membership_type_code: str,
    rule: MembershipTypeRule,
) -> dict:
    """
    Compare old vs new for affected contracts (no writes to contracts/leave).
    old = effective rule excluding pending; new = pending rule values.
    """
    contracts = (
        db.query(Contract)
        .filter(Contract.contract_type_code == membership_type_code)
        .order_by(Contract.id.asc())
        .all()
    )
    samples = []
    affected = 0
    for contract in contracts:
        employee = (
            db.query(Employee)
            .filter(Employee.user_id == contract.user_id)
            .first()
        )
        region = employee.region_code if employee else None

        old_rule = get_effective_rule(
            db, membership_type_code, on_date=rule.effective_from
        )
        if old_rule:
            old_annual = resolve_annual_leave_base_with_region(
                db,
                membership_type_code,
                region_code=region,
                on_date=rule.effective_from,
            )
        else:
            old_annual = int(contract.annual_leave_days or 0)

        new_annual = _annual_from_rule_base(
            db, membership_type_code, rule, region
        )

        old_ent = calculate_entitlement_by_year(
            db, contract, employee=employee, annual_override=old_annual
        )
        new_ent = calculate_entitlement_by_year(
            db, contract, employee=employee, annual_override=new_annual
        )
        if old_annual == new_annual and old_ent == new_ent:
            continue
        affected += 1
        if len(samples) < SAMPLE_LIMIT:
            samples.append(
                {
                    "contract_id": contract.id,
                    "user_id": contract.user_id,
                    "old_annual": old_annual,
                    "new_annual": new_annual,
                    "old_entitlement": {str(k): v for k, v in old_ent.items()},
                    "new_entitlement": {str(k): v for k, v in new_ent.items()},
                }
            )
    return {
        "membership_type_code": membership_type_code,
        "rule_id": rule.id,
        "affected_count": affected,
        "samples": samples,
    }


def create_preview_request(
    db: Session,
    *,
    rule_id: int,
    created_by: str,
) -> MembershipRuleChangeRequest:
    """ثبت درخواست preview؛ contracts/leave را mutate نمی‌کند."""
    rule = db.query(MembershipTypeRule).filter(MembershipTypeRule.id == rule_id).first()
    if not rule:
        raise MembershipError("Rule یافت نشد")
    if rule.status != "pending":
        raise MembershipError("Preview فقط برای Rule در وضعیت pending مجاز است")
    preview = build_impact_preview(db, rule.membership_type_code, rule)
    req = MembershipRuleChangeRequest(
        membership_type_code=rule.membership_type_code,
        rule_id=rule.id,
        status="previewed",
        preview_json=json.dumps(preview, ensure_ascii=False),
        affected_count=preview["affected_count"],
        created_by=created_by,
    )
    db.add(req)
    db.flush()
    return req


def confirm_and_recalculate(
    db: Session,
    request_id: int,
    *,
    confirmed_by: str,
) -> MembershipRuleChangeRequest:
    """
    تأیید صریح: activate pending → recalculate تراکنشی.
    leave updates با commit=False؛ یک commit نهایی توسط caller.
    """
    req = (
        db.query(MembershipRuleChangeRequest)
        .filter(MembershipRuleChangeRequest.id == request_id)
        .first()
    )
    if not req:
        raise MembershipError("درخواست یافت نشد")
    if req.status not in ("previewed", "confirmed"):
        raise MembershipError("وضعیت درخواست برای recalculate معتبر نیست")
    if not req.rule_id:
        raise MembershipError("Rule مرتبط یافت نشد")

    rule = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.id == req.rule_id)
        .first()
    )
    if not rule:
        raise MembershipError("Rule یافت نشد")
    if rule.status != "pending":
        raise MembershipError("Rule مرتبط در وضعیت pending نیست")

    req.status = "confirmed"
    req.confirmed_by = confirmed_by
    req.confirmed_at = datetime.now(timezone.utc)
    db.flush()

    try:
        # Rule becomes effective only here
        activate_pending_rule(db, rule.id)

        contracts = (
            db.query(Contract)
            .filter(Contract.contract_type_code == req.membership_type_code)
            .order_by(Contract.id.asc())
            .all()
        )

        for contract in contracts:
            employee = (
                db.query(Employee)
                .filter(Employee.user_id == contract.user_id)
                .first()
            )
            region = employee.region_code if employee else None
            old_annual = contract.annual_leave_days
            old_sick = contract.sick_leave_days
            old_start = contract.start_date
            old_end = contract.end_date
            old_deduction = contract.service_deduction_days
            old_type = contract.contract_type_code
            new_annual = resolve_annual_leave_base_with_region(
                db,
                contract.contract_type_code,
                region_code=region,
                on_date=rule.effective_from,
            )
            if old_annual == new_annual:
                continue
            before = {
                "annual_leave_days": old_annual,
                "entitlement": calculate_entitlement_by_year(
                    db, contract, employee=employee, annual_override=old_annual
                ),
            }
            contract.annual_leave_days = new_annual
            update_leave_for_contract(
                db,
                contract,
                old_annual_leave=old_annual,
                old_sick_leave=old_sick,
                old_start_date=old_start,
                old_end_date=old_end,
                old_deduction=old_deduction,
                old_type_code=old_type,
                commit=False,
            )
            after = {
                "annual_leave_days": new_annual,
                "entitlement": calculate_entitlement_by_year(
                    db, contract, employee=employee, annual_override=new_annual
                ),
            }
            db.add(
                MembershipRuleChangeAudit(
                    request_id=req.id,
                    contract_id=contract.id,
                    user_id=contract.user_id,
                    before_json=json.dumps(before, ensure_ascii=False, default=str),
                    after_json=json.dumps(after, ensure_ascii=False, default=str),
                    actor=confirmed_by,
                )
            )
        req.status = "applied"
        req.applied_at = datetime.now(timezone.utc)
        db.flush()
    except Exception:
        db.rollback()
        raise

    return req
