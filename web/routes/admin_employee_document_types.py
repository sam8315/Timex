"""
پنل مدیریت انواع مدارک پرسنلی
"""
import re
from pathlib import Path
from typing import Optional

import jdatetime
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.employee_document import EmployeeDocument
from models.employee_document_type import EmployeeDocumentType
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission

router = APIRouter(tags=["Admin Employee Document Types"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = "&" if "?" in referer else "?"
    return f"{referer}{separator}{key}={value}"


def _validate_code(code: str) -> str:
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("کد نوع مدرک الزامی است")
    if not _CODE_RE.match(code):
        raise ValueError(
            "کد باید با حرف انگلیسی شروع شود و فقط شامل A-Z، رقم و _ باشد"
        )
    return code


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام نوع مدرک الزامی است")
    if len(name) > 100:
        raise ValueError("نام نوع مدرک نباید بیشتر از ۱۰۰ کاراکتر باشد")
    return name


@router.get("/employee-document-types", response_class=HTMLResponse)
async def document_types_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_document_types")
    search_term = (search or "").strip()
    has_filter = any([search_term, status_filter, show_all])

    types_data = []
    if has_filter:
        query = db.query(EmployeeDocumentType)
        if search_term:
            like = f"%{search_term}%"
            query = query.filter(
                (EmployeeDocumentType.name.ilike(like))
                | (EmployeeDocumentType.code.ilike(like))
            )
        if status_filter == "active":
            query = query.filter(EmployeeDocumentType.is_active.is_(True))
        elif status_filter == "inactive":
            query = query.filter(EmployeeDocumentType.is_active.is_(False))

        rows = query.order_by(
            EmployeeDocumentType.is_active.desc(),
            EmployeeDocumentType.sort_order,
            EmployeeDocumentType.name,
        ).all()
        for row in rows:
            types_data.append(
                {
                    "doc_type": row,
                    "created_j": (
                        jdatetime.datetime.fromgregorian(datetime=row.created_at).strftime(
                            "%Y/%m/%d %H:%M"
                        )
                        if row.created_at
                        else "-"
                    ),
                }
            )

    return templates.TemplateResponse(
        request,
        "admin/employee_document_types.html",
        {
            "user": user,
            "document_types": types_data,
            "total_count": len(types_data),
            "has_filter": has_filter,
            "show_all": show_all,
            "search": search_term,
            "status_filter": status_filter or "",
            "is_admin": True,
        },
    )


@router.post("/employee-document-types/add")
async def add_document_type(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_document_types")
    referer = request.headers.get("referer", "/admin/employee-document-types")
    try:
        clean_code = _validate_code(code)
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError as exc:
            raise ValueError("ترتیب نمایش باید عدد باشد") from exc

        duplicate = (
            db.query(EmployeeDocumentType)
            .filter(EmployeeDocumentType.code == clean_code)
            .first()
        )
        if duplicate:
            raise ValueError("نوع مدرکی با همین کد قبلاً ثبت شده است")

        row = EmployeeDocumentType(
            code=clean_code,
            name=clean_name,
            sort_order=order,
            is_active=(is_active == "on"),
        )
        db.add(row)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success", f"نوع مدرک «{clean_name}» ثبت شد"
            ),
            status_code=302,
        )
    except ValueError as e:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302,
        )


@router.post("/employee-document-types/{type_id}/edit")
async def edit_document_type(
    request: Request,
    type_id: int,
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_document_types")
    referer = request.headers.get("referer", "/admin/employee-document-types")
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.id == type_id)
        .first()
    )
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "نوع مدرک یافت نشد"),
            status_code=302,
        )
    try:
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError as exc:
            raise ValueError("ترتیب نمایش باید عدد باشد") from exc

        row.name = clean_name
        row.sort_order = order
        row.is_active = is_active == "on"
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success", f"نوع مدرک «{clean_name}» به‌روزرسانی شد"
            ),
            status_code=302,
        )
    except ValueError as e:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302,
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302,
        )


@router.post("/employee-document-types/{type_id}/toggle")
async def toggle_document_type(
    request: Request,
    type_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_document_types")
    referer = request.headers.get("referer", "/admin/employee-document-types")
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.id == type_id)
        .first()
    )
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "نوع مدرک یافت نشد"),
            status_code=302,
        )
    row.is_active = not row.is_active
    db.commit()
    state = "فعال" if row.is_active else "غیرفعال"
    return RedirectResponse(
        url=build_redirect_url(
            referer, "success", f"نوع مدرک «{row.name}» {state} شد"
        ),
        status_code=302,
    )


@router.post("/employee-document-types/{type_id}/delete")
async def delete_document_type(
    request: Request,
    type_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_document_types")
    referer = request.headers.get("referer", "/admin/employee-document-types")
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.id == type_id)
        .first()
    )
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "نوع مدرک یافت نشد"),
            status_code=302,
        )
    in_use = (
        db.query(EmployeeDocument)
        .filter(EmployeeDocument.document_type_id == type_id)
        .count()
    )
    if in_use:
        return RedirectResponse(
            url=build_redirect_url(
                referer,
                "error",
                f"نوع مدرک «{row.name}» به {in_use} مدرک متصل است و قابل حذف نیست",
            ),
            status_code=302,
        )
    name = row.name
    db.delete(row)
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"نوع مدرک «{name}» حذف شد"),
        status_code=302,
    )
