"""پنل مدیریت مناطق خدمت وظیفه (مدت ماه دقیق)."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_db, require_super_admin
from web.permissions import has_permission
from web.services.service_duty_region_service import (
    ServiceDutyRegionError,
    create_duty_region,
    delete_duty_region,
    list_duty_regions,
    region_as_dict,
    toggle_duty_region,
    update_duty_region,
)

router = APIRouter(tags=["Admin Service Duty Regions"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _bool_form(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "on", "yes")


@router.get("/admin/policies/service-duty-regions", response_class=HTMLResponse)
async def service_duty_regions_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)

    rows = [region_as_dict(r) for r in list_duty_regions(db, active_only=False)]
    return templates.TemplateResponse(
        request,
        "admin/policy_service_duty_regions.html",
        {
            "user": user,
            "is_admin": True,
            "is_super_admin": True,
            "regions": rows,
        },
    )


@router.post("/admin/policies/service-duty-regions/add")
async def add_service_duty_region(
    request: Request,
    name: str = Form(...),
    code: str = Form(""),
    native_affects: str = Form(""),
    duration_months: str = Form(""),
    duration_months_native: str = Form(""),
    duration_months_non_native: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    referer = "/admin/policies/service-duty-regions"
    try:
        create_duty_region(
            db,
            name=name,
            code=code or None,
            native_affects=_bool_form(native_affects),
            duration_months=int(duration_months) if duration_months.strip() else None,
            duration_months_native=(
                int(duration_months_native) if duration_months_native.strip() else None
            ),
            duration_months_non_native=(
                int(duration_months_non_native)
                if duration_months_non_native.strip()
                else None
            ),
            sort_order=sort_order,
            is_active=True,
        )
        db.commit()
        return RedirectResponse(url=f"{referer}?success=added", status_code=302)
    except (ServiceDutyRegionError, ValueError) as e:
        db.rollback()
        return RedirectResponse(url=f"{referer}?error={e}", status_code=302)


@router.post("/admin/policies/service-duty-regions/{code}/edit")
async def edit_service_duty_region(
    code: str,
    name: str = Form(...),
    native_affects: str = Form(""),
    duration_months: str = Form(""),
    duration_months_native: str = Form(""),
    duration_months_non_native: str = Form(""),
    sort_order: int = Form(0),
    is_active: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    referer = "/admin/policies/service-duty-regions"
    try:
        update_duty_region(
            db,
            code,
            name=name,
            native_affects=_bool_form(native_affects),
            duration_months=int(duration_months) if duration_months.strip() else None,
            duration_months_native=(
                int(duration_months_native) if duration_months_native.strip() else None
            ),
            duration_months_non_native=(
                int(duration_months_non_native)
                if duration_months_non_native.strip()
                else None
            ),
            sort_order=sort_order,
            is_active=_bool_form(is_active) if is_active != "" else True,
        )
        db.commit()
        return RedirectResponse(url=f"{referer}?success=updated", status_code=302)
    except (ServiceDutyRegionError, ValueError) as e:
        db.rollback()
        return RedirectResponse(url=f"{referer}?error={e}", status_code=302)


@router.post("/admin/policies/service-duty-regions/{code}/toggle")
async def toggle_service_duty_region(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    referer = "/admin/policies/service-duty-regions"
    try:
        toggle_duty_region(db, code)
        db.commit()
        return RedirectResponse(url=f"{referer}?success=toggled", status_code=302)
    except ServiceDutyRegionError as e:
        db.rollback()
        return RedirectResponse(url=f"{referer}?error={e}", status_code=302)


@router.post("/admin/policies/service-duty-regions/{code}/delete")
async def delete_service_duty_region(
    code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    referer = "/admin/policies/service-duty-regions"
    try:
        delete_duty_region(db, code)
        db.commit()
        return RedirectResponse(url=f"{referer}?success=deleted", status_code=302)
    except ServiceDutyRegionError as e:
        db.rollback()
        return RedirectResponse(url=f"{referer}?error={e}", status_code=302)
