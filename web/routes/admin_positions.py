"""
پنل مدیریت سمت‌های شغلی
"""
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
from models.position import Position

router = APIRouter(tags=["Admin Positions"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("نام سمت الزامی است")
    if len(name) > 100:
        raise ValueError("نام سمت نباید بیشتر از ۱۰۰ کاراکتر باشد")
    return name


def resolve_position_id(
    db: Session,
    raw: Optional[str],
    *,
    allow_current_id: Optional[int] = None,
) -> Optional[int]:
    """Parse and validate position_id from a form field.

    Empty → None.
    Invalid id → ValueError.
    Inactive position → ValueError unless it equals allow_current_id
    (so an already-assigned inactive position can be kept on edit).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        pid = int(text)
    except (TypeError, ValueError):
        raise ValueError("سمت انتخاب‌شده نامعتبر است")
    pos = db.query(Position).filter(Position.id == pid).first()
    if not pos:
        raise ValueError("سمت انتخاب‌شده یافت نشد")
    if not pos.is_active and pos.id != allow_current_id:
        raise ValueError("سمت انتخاب‌شده غیرفعال است")
    return pos.id


@router.get("/positions", response_class=HTMLResponse)
async def positions_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """لیست سمت‌ها با جستجو و فیلتر وضعیت"""
    enforce_permission(db, user, "manage_positions")
    search_term = (search or "").strip()
    has_filter = any([search_term, status_filter, show_all])

    positions_data = []
    if has_filter:
        query = db.query(Position)
        if search_term:
            query = query.filter(Position.name.ilike(f"%{search_term}%"))
        if status_filter == "active":
            query = query.filter(Position.is_active == True)
        elif status_filter == "inactive":
            query = query.filter(Position.is_active == False)

        positions = query.order_by(
            Position.is_active.desc(), Position.sort_order, Position.name
        ).all()
        for p in positions:
            positions_data.append({
                "position": p,
                "created_j": jdatetime.datetime.fromgregorian(
                    datetime=p.created_at
                ).strftime("%Y/%m/%d %H:%M") if p.created_at else "-",
            })

    return templates.TemplateResponse(request, "admin/positions.html", {
        "user": user,
        "positions": positions_data,
        "total_count": len(positions_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search_term,
        "status_filter": status_filter or "",
        "is_admin": True,
    })


@router.post("/positions/add")
async def add_position(
    request: Request,
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """افزودن سمت جدید"""
    enforce_permission(db, user, "manage_positions")
    referer = request.headers.get("referer", "/admin/positions")
    try:
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError:
            raise ValueError("ترتیب نمایش باید عدد باشد")

        duplicate = db.query(Position).filter(
            func.lower(Position.name) == clean_name.lower()
        ).first()
        if duplicate:
            raise ValueError("سمتی با همین نام قبلاً ثبت شده است")

        pos = Position(
            name=clean_name,
            sort_order=order,
            is_active=(is_active == "on"),
        )
        db.add(pos)
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"سمت «{clean_name}» ثبت شد"),
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


@router.post("/positions/{position_id}/edit")
async def edit_position(
    request: Request,
    position_id: int,
    name: str = Form(...),
    sort_order: str = Form("0"),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ویرایش سمت"""
    enforce_permission(db, user, "manage_positions")
    referer = request.headers.get("referer", "/admin/positions")
    pos = db.query(Position).filter(Position.id == position_id).first()
    if not pos:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "سمت یافت نشد"),
            status_code=302,
        )
    try:
        clean_name = _validate_name(name)
        try:
            order = int((sort_order or "0").strip() or "0")
        except ValueError:
            raise ValueError("ترتیب نمایش باید عدد باشد")

        duplicate = db.query(Position).filter(
            func.lower(Position.name) == clean_name.lower(),
            Position.id != position_id,
        ).first()
        if duplicate:
            raise ValueError("سمتی با همین نام قبلاً ثبت شده است")

        pos.name = clean_name
        pos.sort_order = order
        pos.is_active = (is_active == "on")
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"سمت «{clean_name}» به‌روزرسانی شد"),
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


@router.post("/positions/{position_id}/toggle")
async def toggle_position(
    request: Request,
    position_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """فعال/غیرفعال کردن سمت"""
    enforce_permission(db, user, "manage_positions")
    referer = request.headers.get("referer", "/admin/positions")
    pos = db.query(Position).filter(Position.id == position_id).first()
    if not pos:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "سمت یافت نشد"),
            status_code=302,
        )
    pos.is_active = not pos.is_active
    db.commit()
    state = "فعال" if pos.is_active else "غیرفعال"
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"سمت «{pos.name}» {state} شد"),
        status_code=302,
    )


@router.post("/positions/{position_id}/delete")
async def delete_position(
    request: Request,
    position_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """حذف سخت سمت فقط اگر هیچ کارمندی به آن ارجاع ندهد"""
    enforce_permission(db, user, "manage_positions")
    referer = request.headers.get("referer", "/admin/positions")
    pos = db.query(Position).filter(Position.id == position_id).first()
    if not pos:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "سمت یافت نشد"),
            status_code=302,
        )
    in_use = db.query(Employee).filter(Employee.position_id == position_id).count()
    if in_use:
        return RedirectResponse(
            url=build_redirect_url(
                referer,
                "error",
                f"سمت «{pos.name}» به {in_use} کارمند متصل است و قابل حذف نیست",
            ),
            status_code=302,
        )
    name = pos.name
    db.delete(pos)
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"سمت «{name}» حذف شد"),
        status_code=302,
    )
