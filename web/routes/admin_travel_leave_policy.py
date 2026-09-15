"""Admin management for membership-scoped Travel Leave policies."""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.contract import CONTRACT_TYPES
from models.travel_leave_policy import TravelLeavePolicy
from models.travel_leave_policy_rules import TravelLeavePolicyRule, TravelLeaveQuotaSetting
from web.dependencies import get_db, require_super_admin
from web.permissions import has_permission
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

DISTANCE_METHODS = {
    "geographic": "فاصله مستقیم جغرافیایی",
    "road": "فاصله جاده‌ای",
    "table": "جدول فاصله شهرها",
}


def _guard(db: Session, user: User):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    return None


def _redirect(status: str):
    return RedirectResponse(url=f"/admin/policies/travel-leave?{status}=1", status_code=302)


@router.get("/admin/policies/travel-leave", response_class=HTMLResponse)
async def admin_travel_leave_policy(request: Request, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    denied = _guard(db, user)
    if denied:
        return denied

    rows = []
    for code, info in CONTRACT_TYPES.items():
        policy = db.query(TravelLeavePolicy).filter(TravelLeavePolicy.contract_type_code == code).first()
        if not policy:
            policy = TravelLeavePolicy(contract_type_code=code, is_enabled=False, distance_method="geographic")
            db.add(policy)
            db.flush()
        quotas = {q.marital_status: q for q in policy.quota_settings}
        rows.append({
            "code": code,
            "name": info["name"],
            "policy": policy,
            "single_quota": quotas.get("S"),
            "married_quota": quotas.get("M"),
            "rules": sorted(policy.rules, key=lambda r: r.min_km),
        })
    db.commit()

    return templates.TemplateResponse(request, "admin/policy_travel_leave.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "rows": rows,
        "distance_methods": DISTANCE_METHODS,
    })


@router.post("/admin/policies/travel-leave/{contract_type_code}/save")
async def save_travel_leave_policy(
    request: Request,
    contract_type_code: str,
    enabled: str = Form("off"),
    distance_method: str = Form("geographic"),
    single_quota: int = Form(3),
    married_quota: int = Form(3),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    denied = _guard(db, user)
    if denied:
        return denied
    if contract_type_code not in CONTRACT_TYPES or distance_method not in DISTANCE_METHODS:
        return _redirect("error")

    policy = db.query(TravelLeavePolicy).filter(TravelLeavePolicy.contract_type_code == contract_type_code).first()
    if not policy:
        policy = TravelLeavePolicy(contract_type_code=contract_type_code)
        db.add(policy)
        db.flush()
    policy.is_enabled = enabled in ("on", "true", "1")
    policy.distance_method = distance_method

    for status, value in (("S", single_quota), ("M", married_quota)):
        value = max(0, min(365, int(value)))
        quota = db.query(TravelLeaveQuotaSetting).filter(
            TravelLeaveQuotaSetting.policy_id == policy.id,
            TravelLeaveQuotaSetting.marital_status == status,
        ).first()
        if not quota:
            quota = TravelLeaveQuotaSetting(
                policy_id=policy.id,
                marital_status=status,
                annual_max_usage=value,
                description="سقف سالانه مرخصی توراهی",
                parameter_key=f"annual_max_usage_{status}",
                parameter_value=str(value),
            )
            db.add(quota)
        else:
            quota.annual_max_usage = value
            quota.parameter_value = str(value)
    db.commit()
    return _redirect("success")


@router.post("/admin/policies/travel-leave/{contract_type_code}/rules/add")
async def add_travel_leave_rule(
    request: Request,
    contract_type_code: str,
    min_km: float = Form(...),
    max_km: float = Form(...),
    travel_days: int = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    denied = _guard(db, user)
    if denied:
        return denied
    policy = db.query(TravelLeavePolicy).filter(TravelLeavePolicy.contract_type_code == contract_type_code).first()
    if not policy or min_km < 0 or max_km < min_km or travel_days < 0 or travel_days > 3:
        return _redirect("error")
    overlap = db.query(TravelLeavePolicyRule).filter(
        TravelLeavePolicyRule.policy_id == policy.id,
        TravelLeavePolicyRule.is_active == 1,
        TravelLeavePolicyRule.min_km <= max_km,
        TravelLeavePolicyRule.max_km >= min_km,
    ).first()
    if overlap:
        return _redirect("error")
    db.add(TravelLeavePolicyRule(
        policy_id=policy.id,
        min_km=min_km,
        max_km=max_km,
        travel_days=travel_days,
        description=description.strip() or None,
        is_active=1,
    ))
    db.commit()
    return _redirect("success")


@router.post("/admin/policies/travel-leave/rules/{rule_id}/delete")
async def delete_travel_leave_rule(
    request: Request,
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    denied = _guard(db, user)
    if denied:
        return denied
    rule = db.query(TravelLeavePolicyRule).filter(TravelLeavePolicyRule.id == rule_id).first()
    if not rule:
        return _redirect("error")
    db.delete(rule)
    db.commit()
    return _redirect("success")
