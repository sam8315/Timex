"""صف یکپارچه تأیید مدارک پرسنلی، بستگان و مدارک تحصیلی."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

import jdatetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.education import Education
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission, has_permission
from web.services.employee_document_service import (
    EmployeeDocumentError,
    get_document,
    reject_document,
    verify_document,
)
from web.services.employee_relative_service import (
    EmployeeRelativeServiceError,
    get_relative,
    reject_relative,
    verify_relative,
)
from web.services.storage_activation import delete_media_file
from web.services.verification_inbox_service import (
    KIND_DOCUMENT,
    KIND_EDUCATION,
    KIND_RELATIVE,
    count_pending_by_kind,
    list_pending_items,
)

router = APIRouter(tags=["Admin Verifications"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _allowed_kinds(db: Session, user: User) -> list[str]:
    kinds: list[str] = []
    if has_permission(db, user, "verify_employee_documents"):
        kinds.append(KIND_DOCUMENT)
    if has_permission(db, user, "verify_employee_relatives"):
        kinds.append(KIND_RELATIVE)
    if has_permission(db, user, "view_dashboard"):
        kinds.append(KIND_EDUCATION)
    return kinds


def _inbox_url(
    *,
    kind: str = "all",
    search: str = "",
    success: str = "",
    error: str = "",
) -> str:
    params: dict[str, str] = {}
    if kind and kind != "all":
        params["kind"] = kind
    if search:
        params["search"] = search
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    qs = urlencode(params, quote_via=quote)
    return f"/admin/verifications?{qs}" if qs else "/admin/verifications"


def _redirect_inbox(
    *,
    kind: str = "all",
    search: str = "",
    success: str = "",
    error: str = "",
) -> RedirectResponse:
    return RedirectResponse(
        url=_inbox_url(kind=kind, search=search, success=success, error=error),
        status_code=302,
    )


def _fmt_created_at(dt) -> str:
    if not dt:
        return "—"
    try:
        if hasattr(dt, "hour"):
            return jdatetime.datetime.fromgregorian(datetime=dt).strftime(
                "%Y/%m/%d %H:%M"
            )
        return jdatetime.date.fromgregorian(date=dt).strftime("%Y/%m/%d")
    except Exception:
        return str(dt)


@router.get("/admin/verifications", response_class=HTMLResponse)
async def admin_verifications_inbox(
    request: Request,
    kind: str = "all",
    search: Optional[str] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    allowed = _allowed_kinds(db, user)
    if not allowed:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")

    kind_key = (kind or "all").strip().lower()
    if kind_key == "all":
        selected_kinds = allowed
    elif kind_key in allowed:
        selected_kinds = [kind_key]
    else:
        return _redirect_inbox(error="نوع انتخاب‌شده در دسترس نیست")

    search_term = (search or "").strip()
    items = list_pending_items(
        db, kinds=selected_kinds, search=search_term or None, limit=200
    )
    counts = count_pending_by_kind(db, allowed)
    total_pending = sum(counts.values())

    rows = [
        {
            "item": it,
            "created_at_j": _fmt_created_at(it.created_at),
        }
        for it in items
    ]

    from web.routes.admin import _admin_nav_flags

    nav = _admin_nav_flags(db, user)
    return templates.TemplateResponse(
        request,
        "admin/verifications.html",
        {
            "user": user,
            "is_admin": True,
            "rows": rows,
            "counts": counts,
            "total_pending": total_pending,
            "allowed_kinds": allowed,
            "kind": kind_key if kind_key in ("all", *allowed) else "all",
            "search": search_term,
            **nav,
        },
    )


@router.post("/admin/verifications/documents/{document_id}/verify")
async def inbox_verify_document(
    document_id: int,
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_documents")
    try:
        verify_document(db, document_id, verified_by=user.user_id)
        return _redirect_inbox(kind=kind, search=search, success="مدرک تأیید شد")
    except EmployeeDocumentError as exc:
        return _redirect_inbox(kind=kind, search=search, error=str(exc))


@router.post("/admin/verifications/documents/{document_id}/reject")
async def inbox_reject_document(
    document_id: int,
    rejection_reason: str = Form(...),
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_documents")
    try:
        get_document(db, document_id)
        reject_document(
            db,
            document_id,
            verified_by=user.user_id,
            rejection_reason=rejection_reason,
        )
        return _redirect_inbox(kind=kind, search=search, success="مدرک رد شد")
    except EmployeeDocumentError as exc:
        return _redirect_inbox(kind=kind, search=search, error=str(exc))


@router.post("/admin/verifications/relatives/{relative_id}/verify")
async def inbox_verify_relative(
    relative_id: int,
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_relatives")
    try:
        rel = get_relative(db, relative_id)
        verify_relative(
            db,
            user_id=rel.user_id,
            relative_id=relative_id,
            verified_by=user.user_id,
        )
        return _redirect_inbox(
            kind=kind, search=search, success="فرد وابسته تأیید شد"
        )
    except EmployeeRelativeServiceError as exc:
        return _redirect_inbox(kind=kind, search=search, error=str(exc))


@router.post("/admin/verifications/relatives/{relative_id}/reject")
async def inbox_reject_relative(
    relative_id: int,
    rejection_reason: str = Form(...),
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_relatives")
    try:
        rel = get_relative(db, relative_id)
        reject_relative(
            db,
            user_id=rel.user_id,
            relative_id=relative_id,
            rejected_by=user.user_id,
            reason=rejection_reason,
        )
        return _redirect_inbox(kind=kind, search=search, success="فرد وابسته رد شد")
    except EmployeeRelativeServiceError as exc:
        return _redirect_inbox(kind=kind, search=search, error=str(exc))


@router.post("/admin/verifications/education/{edu_id}/verify")
async def inbox_verify_education(
    edu_id: int,
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "view_dashboard")
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()
        if not edu:
            raise ValueError("مدرک یافت نشد")
        edu.verified = True
        edu.verification_date = date.today()
        edu.verified_by = user.user_id
        db.commit()
        return _redirect_inbox(
            kind=kind, search=search, success="مدرک تحصیلی تأیید شد"
        )
    except Exception as exc:
        db.rollback()
        return _redirect_inbox(kind=kind, search=search, error=f"خطا: {exc}")


@router.post("/admin/verifications/education/{edu_id}/reject")
async def inbox_reject_education(
    edu_id: int,
    kind: str = Form("all"),
    search: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """رد مدرک تحصیلی = حذف رکورد (همان رفتار /admin/education)."""
    enforce_permission(db, user, "view_dashboard")
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()
        if not edu:
            raise ValueError("مدرک یافت نشد")
        old_path = edu.certificate_path
        db.delete(edu)
        db.commit()
        if old_path:
            delete_media_file(old_path)
        return _redirect_inbox(
            kind=kind, search=search, success="مدرک تحصیلی رد و حذف شد"
        )
    except Exception as exc:
        db.rollback()
        return _redirect_inbox(kind=kind, search=search, error=f"خطا: {exc}")
