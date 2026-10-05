"""
پنل ثبت تعدیل خدمت (بدون موتور پایان خدمت).
"""
from datetime import date
from pathlib import Path
from typing import Optional

import jdatetime
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.service_adjustment import ServiceAdjustment
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from web.services.service_adjustment_service import (
    ServiceAdjustmentError,
    correct_adjustment,
    create_adjustment,
    void_adjustment,
)

router = APIRouter(tags=["Admin Service Adjustments"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = "&" if "?" in referer else "?"
    return f"{referer}{separator}{key}={value}"


def _parse_jalali(date_str: str) -> date:
    j = jdatetime.datetime.strptime((date_str or "").strip(), "%Y/%m/%d").date()
    return j.togregorian()


@router.get("/service-adjustments", response_class=HTMLResponse)
async def service_adjustments_page(
    request: Request,
    employee_id: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_service_adjustments")
    has_filter = bool(employee_id or show_all)
    rows = []
    if has_filter:
        q = db.query(ServiceAdjustment).order_by(ServiceAdjustment.id.desc())
        if employee_id:
            q = q.filter(ServiceAdjustment.employee_id == employee_id.strip())
        for row in q.limit(200).all():
            rows.append(
                {
                    "row": row,
                    "effective_j": jdatetime.date.fromgregorian(
                        date=row.effective_date
                    ).strftime("%Y/%m/%d"),
                }
            )
    return templates.TemplateResponse(
        request,
        "admin/service_adjustments.html",
        {
            "user": user,
            "rows": rows,
            "has_filter": has_filter,
            "employee_id": employee_id or "",
            "show_all": show_all,
            "is_admin": True,
        },
    )


@router.post("/service-adjustments/add")
async def add_service_adjustment(
    request: Request,
    employee_id: str = Form(...),
    adjustment_type: str = Form(...),
    effective_date_str: str = Form(...),
    years: int = Form(0),
    months: int = Form(0),
    days: int = Form(0),
    title: str = Form(""),
    reason: str = Form(""),
    description: str = Form(""),
    contract_id: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_service_adjustments")
    referer = request.headers.get("referer", "/admin/service-adjustments")
    try:
        cid = int(contract_id) if (contract_id or "").strip() else None
        create_adjustment(
            db,
            employee_id=employee_id.strip(),
            adjustment_type=adjustment_type,
            effective_date=_parse_jalali(effective_date_str),
            years=years,
            months=months,
            days=days,
            title=title.strip() or None,
            reason=reason.strip() or None,
            description=description.strip() or None,
            contract_id=cid,
            created_by=user.user_id,
        )
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "تعدیل ثبت شد"),
            status_code=302,
        )
    except (ServiceAdjustmentError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/service-adjustments/{adjustment_id}/correct")
async def correct_service_adjustment(
    request: Request,
    adjustment_id: int,
    years: int = Form(0),
    months: int = Form(0),
    days: int = Form(0),
    title: str = Form(""),
    reason: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_service_adjustments")
    referer = request.headers.get("referer", "/admin/service-adjustments")
    try:
        correct_adjustment(
            db,
            original_id=adjustment_id,
            years=years,
            months=months,
            days=days,
            title=title.strip() or None,
            reason=reason.strip() or None,
            created_by=user.user_id,
        )
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "اصلاح با رکورد correction ثبت شد"),
            status_code=302,
        )
    except (ServiceAdjustmentError, ValueError) as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )


@router.post("/service-adjustments/{adjustment_id}/void")
async def void_service_adjustment(
    request: Request,
    adjustment_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_service_adjustments")
    referer = request.headers.get("referer", "/admin/service-adjustments")
    try:
        void_adjustment(db, adjustment_id, created_by=user.user_id)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "رکورد ابطال شد"),
            status_code=302,
        )
    except ServiceAdjustmentError as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )
