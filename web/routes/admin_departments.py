"""پنل مدیریت دپارتمان‌های سازمانی."""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
import jdatetime

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from models.user import User
from models.employee import Employee
from models.department import Department

router = APIRouter(tags=["Admin Departments"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = "&" if "?" in referer else "?"
    return f"{referer}{separator}{key}={value}"


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام دپارتمان الزامی است")
    if len(name) > 100:
        raise ValueError("نام دپارتمان نباید بیشتر از ۱۰۰ کاراکتر باشد")
    return name


def resolve_department_id(
    db: Session,
    raw: Optional[str],
    *,
    allow_current_id: Optional[int] = None,
) -> Optional[int]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        did = int(text)
    except (TypeError, ValueError):
        raise ValueError("دپارتمان انتخاب‌شده نامعتبر است")
    row = db.query(Department).filter(Department.id == did).first()
    if not row:
        raise ValueError("دپارتمان انتخاب‌شده یافت نشد")
    if not row.is_active and row.id != allow_current_id:
        raise ValueError("دپارتمان انتخاب‌شده غیرفعال است")
    return row.id


@router.get("/departments", response_class=HTMLResponse)
async def departments_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_departments")
    search_term = (search or "").strip()
    has_filter = any([search_term, status_filter, show_all])
    rows = []
    if has_filter:
        query = db.query(Department)
        if search_term:
            query = query.filter(Department.name.ilike(f"%{search_term}%"))
        if status_filter == "active":
            query = query.filter(Department.is_active == True)
        elif status_filter == "inactive":
            query = query.filter(Department.is_active == False)
        for row in query.order_by(
            Department.is_active.desc(), Department.sort_order, Department.name
        ).all():
            rows.append({
                "department": row,
                "created_j": jdatetime.datetime.fromgregorian(
                    datetime=row.created_at
                ).strftime("%Y/%m/%d %H:%M") if row.created_at else "-",
            })
    return templates.TemplateResponse(request, "admin/departments.html", {
        "user": user,
        "departments": rows,
        "total_count": len(rows),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search_term,
        "status_filter": status_filter or "",
        "is_admin": True,
    })


@router.post("/departments/add")
async def add_department(
    request: Request,
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_departments")
    referer = request.headers.get("referer", "/admin/departments")
    try:
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError:
            raise ValueError("ترتیب نمایش باید عدد باشد")
        duplicate = db.query(Department).filter(
            func.lower(Department.name) == clean_name.lower()
        ).first()
        if duplicate:
            raise ValueError("دپارتمانی با همین نام قبلاً ثبت شده است")
        db.add(Department(
            name=clean_name,
            sort_order=order,
            is_active=(is_active == "on"),
        ))
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"دپارتمان «{clean_name}» ثبت شد"),
            status_code=302,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(exc)),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {exc}"),
            status_code=302,
        )


@router.post("/departments/{department_id}/edit")
async def edit_department(
    request: Request,
    department_id: int,
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_departments")
    referer = request.headers.get("referer", "/admin/departments")
    row = db.query(Department).filter(Department.id == department_id).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "دپارتمان یافت نشد"),
            status_code=302,
        )
    try:
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError:
            raise ValueError("ترتیب نمایش باید عدد باشد")
        duplicate = db.query(Department).filter(
            func.lower(Department.name) == clean_name.lower(),
            Department.id != department_id,
        ).first()
        if duplicate:
            raise ValueError("دپارتمانی با همین نام قبلاً ثبت شده است")
        row.name = clean_name
        row.sort_order = order
        row.is_active = (is_active == "on")
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"دپارتمان «{clean_name}» به‌روزرسانی شد"),
            status_code=302,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(exc)),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {exc}"),
            status_code=302,
        )


@router.post("/departments/{department_id}/toggle")
async def toggle_department(
    request: Request,
    department_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_departments")
    referer = request.headers.get("referer", "/admin/departments")
    row = db.query(Department).filter(Department.id == department_id).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "دپارتمان یافت نشد"),
            status_code=302,
        )
    row.is_active = not row.is_active
    db.commit()
    state = "فعال" if row.is_active else "غیرفعال"
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"دپارتمان «{row.name}» {state} شد"),
        status_code=302,
    )


@router.post("/departments/{department_id}/delete")
async def delete_department(
    request: Request,
    department_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_departments")
    referer = request.headers.get("referer", "/admin/departments")
    row = db.query(Department).filter(Department.id == department_id).first()
    if not row:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "دپارتمان یافت نشد"),
            status_code=302,
        )
    in_use = db.query(Employee).filter(Employee.department_id == department_id).count()
    if in_use:
        return RedirectResponse(
            url=build_redirect_url(
                referer,
                "error",
                f"دپارتمان «{row.name}» به {in_use} کارمند متصل است و قابل حذف نیست",
            ),
            status_code=302,
        )
    name = row.name
    db.delete(row)
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"دپارتمان «{name}» حذف شد"),
        status_code=302,
    )
