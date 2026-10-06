"""
پنل مدیریت انواع عضویت و قواعد نسخه‌دار.
"""
from datetime import date
from pathlib import Path
from typing import Optional

import jdatetime
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.membership_type_rule import (
    LEAVE_START_BASIS_CHOICES,
    LEAVE_START_BASIS_LABELS,
    LEAVE_START_DISPATCH,
    MembershipTypeRule,
)
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission, has_permission
from web.services import membership_semantics as msem
from web.services.membership_retroactive_service import (
    confirm_and_recalculate,
    create_preview_request,
)
from web.services.membership_service import (
    MembershipError,
    activate_membership,
    apply_conscript_leave_start_basis_change,
    count_business_dependencies,
    create_membership_type,
    create_rule_snapshot,
    deactivate_membership,
    delete_membership,
    delete_scheduled_rule,
    get_membership_type,
    list_membership_types,
    update_scheduled_rule,
)

router = APIRouter(tags=["Admin Membership Types"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = "&" if "?" in referer else "?"
    return f"{referer}{separator}{key}={value}"


def _parse_jalali(date_str: str) -> date:
    text = (date_str or "").strip()
    if not text:
        raise ValueError("تاریخ الزامی است")
    j = jdatetime.datetime.strptime(text, "%Y/%m/%d").date()
    return j.togregorian()


@router.get("/membership-types", response_class=HTMLResponse)
async def membership_types_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    search_term = (search or "").strip()
    has_filter = any([search_term, status_filter, show_all])

    rows = []
    if has_filter:
        items = list_membership_types(db, active_only=False)
        for mt in items:
            if search_term:
                like = search_term.lower()
                if like not in mt.code.lower() and like not in mt.name.lower():
                    continue
            if status_filter == "active" and not mt.is_active:
                continue
            if status_filter == "inactive" and mt.is_active:
                continue
            deps = count_business_dependencies(db, mt.code)
            rows.append({"mt": mt, "deps": deps})

    return templates.TemplateResponse(
        request,
        "admin/membership_types.html",
        {
            "user": user,
            "membership_types": rows,
            "total_count": len(rows),
            "has_filter": has_filter,
            "show_all": show_all,
            "search": search_term,
            "status_filter": status_filter or "",
            "is_admin": True,
            "can_manage_rules": has_permission(db, user, "manage_membership_rules"),
        },
    )


@router.post("/membership-types/add")
async def add_membership_type(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    referer = request.headers.get("referer", "/admin/membership-types")
    try:
        order = int((sort_order or "0").strip() or "0")
        create_membership_type(
            db,
            code=code,
            name=name,
            description=description.strip() or None,
            sort_order=order,
            is_active=(is_active == "on"),
            created_by=user.user_id,
        )
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"نوع عضویت «{name}» ثبت شد"),
            status_code=302,
        )
    except (MembershipError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/edit")
async def edit_membership_type(
    request: Request,
    code: str,
    name: str = Form(...),
    description: str = Form(""),
    sort_order: str = Form("0"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    referer = request.headers.get("referer", "/admin/membership-types")
    mt = get_membership_type(db, code)
    if not mt:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "نوع عضویت یافت نشد"),
            status_code=302,
        )
    try:
        clean_name = (name or "").strip()
        if not clean_name:
            raise MembershipError("نام الزامی است")
        mt.name = clean_name
        mt.description = description.strip() or None
        mt.sort_order = int((sort_order or "0").strip() or "0")
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "به‌روزرسانی شد"),
            status_code=302,
        )
    except (MembershipError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/toggle")
async def toggle_membership_type(
    request: Request,
    code: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    referer = request.headers.get("referer", "/admin/membership-types")
    mt = get_membership_type(db, code)
    if not mt:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "نوع عضویت یافت نشد"),
            status_code=302,
        )
    try:
        if mt.is_active:
            deactivate_membership(db, code)
            state = "غیرفعال"
        else:
            activate_membership(db, code)
            state = "فعال"
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"نوع عضویت {state} شد"),
            status_code=302,
        )
    except MembershipError as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/delete")
async def delete_membership_type(
    request: Request,
    code: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    referer = request.headers.get("referer", "/admin/membership-types")
    try:
        delete_membership(db, code, reserved_by=user.user_id)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "نوع عضویت حذف و کد رزرو شد"),
            status_code=302,
        )
    except MembershipError as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.get("/membership-types/{code}", response_class=HTMLResponse)
async def membership_type_detail(
    request: Request,
    code: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_types")
    mt = get_membership_type(db, code)
    if not mt:
        return RedirectResponse(url="/admin/membership-types?error=یافت نشد", status_code=302)
    rules = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == code)
        .order_by(MembershipTypeRule.effective_from.desc())
        .all()
    )
    rule_rows = []
    for r in rules:
        rule_rows.append(
            {
                "rule": r,
                "effective_j": jdatetime.date.fromgregorian(
                    date=r.effective_from
                ).strftime("%Y/%m/%d"),
                "editable": (
                    r.status == "scheduled" and r.effective_from > date.today()
                ),
                "is_pending": r.status == "pending",
            }
        )
    return templates.TemplateResponse(
        request,
        "admin/membership_type_detail.html",
        {
            "user": user,
            "mt": mt,
            "rules": rule_rows,
            "deps": count_business_dependencies(db, code),
            "is_admin": True,
            "can_manage_rules": has_permission(db, user, "manage_membership_rules"),
            "is_conscript": msem.is_conscript(db, code),
            "leave_start_basis_choices": LEAVE_START_BASIS_CHOICES,
            "leave_start_basis_labels": LEAVE_START_BASIS_LABELS,
            "leave_start_default": LEAVE_START_DISPATCH,
        },
    )


@router.post("/membership-types/{code}/rules/add")
async def add_membership_rule(
    request: Request,
    code: str,
    effective_from_str: str = Form(...),
    annual_leave_base: int = Form(0),
    supports_service_deduction: str = Form("off"),
    supports_extra_service: str = Form("off"),
    supports_positive_seniority: str = Form("off"),
    leave_start_date_basis: str = Form("dispatch"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_rules")
    referer = request.headers.get("referer", f"/admin/membership-types/{code}")
    try:
        eff = _parse_jalali(effective_from_str)
        rule = create_rule_snapshot(
            db,
            membership_type_code=code,
            effective_from=eff,
            annual_leave_base=annual_leave_base,
            supports_service_deduction=supports_service_deduction == "on",
            supports_extra_service=supports_extra_service == "on",
            supports_positive_seniority=supports_positive_seniority == "on",
            leave_start_date_basis=leave_start_date_basis,
            created_by=user.user_id,
        )
        db.commit()
        # If past/current, create impact preview request automatically
        msg = f"Rule ثبت شد (#{rule.id})"
        if eff <= date.today():
            preview_req = create_preview_request(
                db, rule_id=rule.id, created_by=user.user_id
            )
            db.commit()
            msg += (
                f" — تأثیر روی {preview_req.affected_count} نفر؛ "
                f"برای اعمال به تأیید نیاز است (درخواست #{preview_req.id})"
            )
        return RedirectResponse(
            url=build_redirect_url(referer, "success", msg),
            status_code=302,
        )
    except (MembershipError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/rules/{rule_id}/edit")
async def edit_membership_rule(
    request: Request,
    code: str,
    rule_id: int,
    annual_leave_base: int = Form(0),
    supports_service_deduction: str = Form("off"),
    supports_extra_service: str = Form("off"),
    supports_positive_seniority: str = Form("off"),
    leave_start_date_basis: str = Form("dispatch"),
    effective_from_str: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_rules")
    referer = request.headers.get("referer", f"/admin/membership-types/{code}")
    try:
        eff = _parse_jalali(effective_from_str) if effective_from_str.strip() else None
        update_scheduled_rule(
            db,
            rule_id,
            annual_leave_base=annual_leave_base,
            supports_service_deduction=supports_service_deduction == "on",
            supports_extra_service=supports_extra_service == "on",
            supports_positive_seniority=supports_positive_seniority == "on",
            leave_start_date_basis=leave_start_date_basis,
            effective_from=eff,
        )
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "Rule آینده به‌روز شد"),
            status_code=302,
        )
    except (MembershipError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/leave-start-basis")
async def update_leave_start_basis(
    request: Request,
    code: str,
    leave_start_date_basis: str = Form("dispatch"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Edit active conscript leave_start_date_basis and recalculate all contracts."""
    enforce_permission(db, user, "manage_membership_rules")
    referer = request.headers.get("referer", f"/admin/membership-types/{code}")
    try:
        result = apply_conscript_leave_start_basis_change(
            db,
            code,
            leave_start_date_basis,
            actor=user.user_id,
        )
        db.commit()
        if not result.get("changed"):
            msg = "مبنای شروع مرخصی تغییری نکرد"
        else:
            label = LEAVE_START_BASIS_LABELS.get(
                result["new_basis"], result["new_basis"]
            )
            msg = (
                f"مبنای شروع مرخصی به «{label}» تغییر کرد؛ "
                f"{result['contracts_adjusted']} از "
                f"{result['contracts_total']} قرارداد تعدیل شد"
            )
        return RedirectResponse(
            url=build_redirect_url(referer, "success", msg),
            status_code=302,
        )
    except (MembershipError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-types/{code}/rules/{rule_id}/delete")
async def delete_membership_rule(
    request: Request,
    code: str,
    rule_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_rules")
    referer = request.headers.get("referer", f"/admin/membership-types/{code}")
    try:
        delete_scheduled_rule(db, rule_id)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "Rule آینده حذف شد"),
            status_code=302,
        )
    except MembershipError as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/membership-rule-changes/{request_id}/confirm")
async def confirm_membership_rule_change(
    request: Request,
    request_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_membership_rules")
    referer = request.headers.get("referer", "/admin/membership-types")
    try:
        req = confirm_and_recalculate(db, request_id, confirmed_by=user.user_id)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(
                referer,
                "success",
                f"Recalculate برای درخواست #{req.id} انجام شد",
            ),
            status_code=302,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )
