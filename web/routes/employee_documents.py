"""Employee Documents — employee self-service + admin management."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import jdatetime
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.employee_document import DOCUMENT_STATUSES, DOCUMENT_TYPES, EmployeeDocument
from models.user import User
from web.dependencies import check_password_change, get_db, require_admin
from web.permissions import enforce_permission, has_permission
from web.services.employee_document_service import (
    EmployeeDocumentError,
    create_document,
    get_document,
    list_documents,
    reject_document,
    resolve_document_file,
    soft_delete_document,
    verify_document,
)

router = APIRouter(tags=["Employee Documents"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=302)


def _q(url: str, *, success: str = "", error: str = "") -> RedirectResponse:
    if success:
        return _redirect(f"{url}?success={quote(success)}")
    if error:
        return _redirect(f"{url}?error={quote(error)}")
    return _redirect(url)


def _parse_jalali_optional(value: str, field_label: str) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return jdatetime.datetime.strptime(text, "%Y/%m/%d").date().togregorian()
    except (ValueError, TypeError) as exc:
        raise EmployeeDocumentError(f"تاریخ {field_label} نامعتبر است") from exc


def _decorate(doc: EmployeeDocument) -> EmployeeDocument:
    try:
        doc.issue_date_j = (
            jdatetime.date.fromgregorian(date=doc.issue_date).strftime("%Y/%m/%d")
            if doc.issue_date
            else ""
        )
    except Exception:
        doc.issue_date_j = ""
    try:
        doc.expiry_date_j = (
            jdatetime.date.fromgregorian(date=doc.expiry_date).strftime("%Y/%m/%d")
            if doc.expiry_date
            else ""
        )
    except Exception:
        doc.expiry_date_j = ""
    try:
        doc.uploaded_at_j = jdatetime.datetime.fromgregorian(
            datetime=doc.uploaded_at
        ).strftime("%Y/%m/%d %H:%M")
    except Exception:
        doc.uploaded_at_j = ""
    return doc


def _can_access_file(db: Session, user: User, doc: EmployeeDocument) -> bool:
    if doc.user_id == user.user_id:
        return True
    return has_permission(db, user, "view_employee_documents") or has_permission(
        db, user, "manage_employee_documents"
    )


async def _read_upload_bytes(upload: Optional[UploadFile]) -> tuple[bytes, str]:
    if not upload or not upload.filename:
        raise EmployeeDocumentError("انتخاب فایل الزامی است")
    content = await upload.read()
    return content, upload.filename


# ---------------------------------------------------------------------------
# Employee self-service
# ---------------------------------------------------------------------------

@router.get("/employee-documents", response_class=HTMLResponse)
async def employee_documents_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    docs = [_decorate(d) for d in list_documents(db, user.user_id)]
    return templates.TemplateResponse(
        request,
        "employee_documents/list.html",
        {
            "user": user,
            "documents": docs,
            "document_types": DOCUMENT_TYPES,
            "document_statuses": DOCUMENT_STATUSES,
            "is_admin": user.is_admin,
        },
    )


@router.post("/employee-documents/add")
async def employee_add_document(
    request: Request,
    document_type: str = Form(...),
    title: str = Form(...),
    document_number: str = Form(""),
    issue_date_str: str = Form(""),
    expiry_date_str: str = Form(""),
    notes: str = Form(""),
    document_file: Optional[UploadFile] = File(None),
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    base = "/employee-documents"
    try:
        content, filename = await _read_upload_bytes(document_file)
        create_document(
            db,
            user_id=user.user_id,
            uploaded_by=user.user_id,
            document_type=document_type,
            title=title,
            file_bytes=content,
            original_filename=filename,
            document_number=document_number,
            issue_date=_parse_jalali_optional(issue_date_str, "صدور"),
            expiry_date=_parse_jalali_optional(expiry_date_str, "انقضا"),
            notes=notes,
        )
        return _q(base, success="مدرک با موفقیت ثبت شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))
    except Exception as exc:
        return _q(base, error=f"خطا: {exc}")


@router.post("/employee-documents/{document_id}/delete")
async def employee_delete_document(
    document_id: int,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    base = "/employee-documents"
    try:
        doc = get_document(db, document_id)
        if doc.user_id != user.user_id:
            return _q(base, error="دسترسی غیرمجاز")
        soft_delete_document(
            db, document_id, deleted_by=user.user_id, allow_verified=False
        )
        return _q(base, success="مدرک حذف شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))


@router.get("/employee-documents/{document_id}/file")
async def download_document_file(
    document_id: int,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    try:
        doc = get_document(db, document_id)
    except EmployeeDocumentError:
        return _q("/employee-documents", error="مدرک یافت نشد")

    if not _can_access_file(db, user, doc):
        if user.is_admin:
            return _redirect("/admin/")
        return _q("/employee-documents", error="دسترسی غیرمجاز")

    try:
        disk = resolve_document_file(doc)
    except EmployeeDocumentError:
        return _q("/employee-documents", error="فایل مدرک روی دیسک موجود نیست")

    if not disk.is_file():
        return _q("/employee-documents", error="فایل مدرک روی دیسک موجود نیست")

    return FileResponse(
        path=str(disk),
        filename=doc.original_filename,
        media_type=doc.mime_type,
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# Admin — profile-scoped management
# ---------------------------------------------------------------------------

@router.post("/admin/profile/{target_user_id}/documents/add")
async def admin_add_document(
    target_user_id: str,
    document_type: str = Form(...),
    title: str = Form(...),
    document_number: str = Form(""),
    issue_date_str: str = Form(""),
    expiry_date_str: str = Form(""),
    notes: str = Form(""),
    document_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_documents")
    base = f"/admin/profile/{target_user_id}"
    try:
        content, filename = await _read_upload_bytes(document_file)
        create_document(
            db,
            user_id=target_user_id,
            uploaded_by=user.user_id,
            document_type=document_type,
            title=title,
            file_bytes=content,
            original_filename=filename,
            document_number=document_number,
            issue_date=_parse_jalali_optional(issue_date_str, "صدور"),
            expiry_date=_parse_jalali_optional(expiry_date_str, "انقضا"),
            notes=notes,
        )
        return _q(base, success="مدرک با موفقیت ثبت شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))
    except Exception as exc:
        return _q(base, error=f"خطا: {exc}")


@router.post("/admin/profile/{target_user_id}/documents/{document_id}/delete")
async def admin_delete_document(
    target_user_id: str,
    document_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_documents")
    base = f"/admin/profile/{target_user_id}"
    try:
        doc = get_document(db, document_id)
        if doc.user_id != target_user_id:
            return _q(base, error="مدرک متعلق به این کاربر نیست")
        soft_delete_document(
            db, document_id, deleted_by=user.user_id, allow_verified=True
        )
        return _q(base, success="مدرک حذف شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))


@router.post("/admin/profile/{target_user_id}/documents/{document_id}/verify")
async def admin_verify_document(
    target_user_id: str,
    document_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_documents")
    base = f"/admin/profile/{target_user_id}"
    try:
        doc = get_document(db, document_id)
        if doc.user_id != target_user_id:
            return _q(base, error="مدرک متعلق به این کاربر نیست")
        verify_document(db, document_id, verified_by=user.user_id)
        return _q(base, success="مدرک تأیید شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))


@router.post("/admin/profile/{target_user_id}/documents/{document_id}/reject")
async def admin_reject_document(
    target_user_id: str,
    document_id: int,
    rejection_reason: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_documents")
    base = f"/admin/profile/{target_user_id}"
    try:
        doc = get_document(db, document_id)
        if doc.user_id != target_user_id:
            return _q(base, error="مدرک متعلق به این کاربر نیست")
        reject_document(
            db,
            document_id,
            verified_by=user.user_id,
            rejection_reason=rejection_reason,
        )
        return _q(base, success="مدرک رد شد")
    except EmployeeDocumentError as exc:
        return _q(base, error=str(exc))
