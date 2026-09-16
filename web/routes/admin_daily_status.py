"""پنل مدیریت مأموریت و استراحت"""
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import jdatetime
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.daily_status import DailyStatus, STATUS_CODES
from models.employee import Employee
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission

router = APIRouter(tags=["Admin Daily Status"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = "&" if "?" in referer else "?"
    return f"{referer}{separator}{key}={value}"


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start_j = jdatetime.date(year, month, 1)
    next_month_j = (
        jdatetime.date(year + 1, 1, 1)
        if month == 12
        else jdatetime.date(year, month + 1, 1)
    )
    return (
        start_j.togregorian(),
        (next_month_j - timedelta(days=1)).togregorian(),
    )


def filter_query_string(
    search: str,
    status_filter: str,
    year: int,
    month: int,
    show_all: str,
) -> str:
    params = {}
    if search:
        params["search"] = search
    if status_filter:
        params["status_filter"] = status_filter
    params["year"] = year
    params["month"] = month
    if show_all:
        params["show_all"] = show_all
    return urlencode(params)


@router.get("/daily-status", response_class=HTMLResponse)
async def daily_status_page(
    request: Request,
    search: str | None = Query(None),
    status_filter: str | None = Query(None),
    year: int | None = Query(None, ge=1400, le=1500),
    month: int | None = Query(None, ge=1, le=12),
    show_all: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """لیست مأموریت‌ها و استراحت‌ها"""
    enforce_permission(db, user, "view_all_attendance")

    today_j = jdatetime.date.today()
    selected_year = year or today_j.year
    selected_month = month or today_j.month
    showing_all = bool(show_all)

    query = db.query(DailyStatus)
    if not showing_all:
        month_start_g, month_end_g = month_bounds(selected_year, selected_month)
        query = query.filter(
            DailyStatus.status_date >= month_start_g,
            DailyStatus.status_date <= month_end_g,
        )

    search_term = search.strip() if search else ""
    status_term = status_filter.strip() if status_filter else ""
    if status_term:
        query = query.filter(DailyStatus.status_code == status_term)
    if search_term:
        query = query.outerjoin(Employee, DailyStatus.user_id == Employee.user_id).filter(
            or_(
                DailyStatus.user_id.ilike(f"%{search_term}%"),
                Employee.first_name.ilike(f"%{search_term}%"),
                Employee.last_name.ilike(f"%{search_term}%"),
            )
        )

    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    selected_page = min(page, total_pages)
    status_counts = dict(
        query.with_entities(DailyStatus.status_code, func.count(DailyStatus.id))
        .group_by(DailyStatus.status_code)
        .all()
    )

    statuses = (
        query.order_by(DailyStatus.status_date.desc(), DailyStatus.id.desc())
        .offset((selected_page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    employee_map = {}
    user_ids = {status.user_id for status in statuses}
    if user_ids:
        employees = db.query(Employee).filter(Employee.user_id.in_(user_ids)).all()
        employee_map = {employee.user_id: employee for employee in employees}

    statuses_data = []
    for status in statuses:
        employee = employee_map.get(status.user_id)
        date_j = jdatetime.date.fromgregorian(date=status.status_date)
        statuses_data.append(
            {
                "status": status,
                "full_name": employee.full_name if employee else f"کاربر {status.user_id}",
                "personnel_code": status.user_id,
                "date_j": date_j.strftime("%Y/%m/%d"),
                "status_name": status.status_name,
            }
        )

    employees = (
        db.query(Employee)
        .filter(Employee.is_active.is_(True))
        .order_by(Employee.last_name, Employee.first_name)
        .limit(200)
        .all()
    )
    pagination_params = filter_query_string(
        search_term,
        status_term,
        selected_year,
        selected_month,
        show_all or "",
    )

    return templates.TemplateResponse(
        request,
        "admin/daily_status.html",
        {
            "user": user,
            "statuses": statuses_data,
            "total_count": total_count,
            "search": search_term,
            "status_filter": status_term,
            "year": selected_year,
            "month": selected_month,
            "page": selected_page,
            "per_page": per_page,
            "total_pages": total_pages,
            "pagination_params": pagination_params,
            "show_all": show_all or "",
            "available_years": list(range(today_j.year - 2, today_j.year + 3)),
            "available_months": list(range(1, 13)),
            "month_names": {
                1: "فروردین",
                2: "اردیبهشت",
                3: "خرداد",
                4: "تیر",
                5: "مرداد",
                6: "شهریور",
                7: "مهر",
                8: "آبان",
                9: "آذر",
                10: "دی",
                11: "بهمن",
                12: "اسفند",
            },
            "status_codes": STATUS_CODES,
            "mission_count": status_counts.get("M", 0),
            "rest_count": status_counts.get("R", 0),
            "employees": employees,
            "is_admin": True,
        },
    )


@router.post("/daily-status/add")
async def add_daily_status(
    request: Request,
    user_id: str = Form(...),
    from_date: str = Form(...),
    to_date: str | None = Form(None),
    status_code: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ثبت مأموریت یا استراحت برای بازه تاریخی"""
    enforce_permission(db, user, "view_all_attendance")
    referer = request.headers.get("referer", "/admin/daily-status")

    try:
        normalized_user_id = user_id.strip()
        normalized_status = status_code.strip()
        if not normalized_user_id:
            raise ValueError("کد پرسنلی الزامی است")
        if normalized_status not in STATUS_CODES:
            raise ValueError(f"کد وضعیت نامعتبر: {normalized_status}")

        from_date_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        to_date_text = to_date.strip() if to_date else ""
        to_date_j = (
            jdatetime.datetime.strptime(to_date_text, "%Y/%m/%d").date()
            if to_date_text
            else from_date_j
        )
        if from_date_j > to_date_j:
            raise ValueError("تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد")

        from_date_g = from_date_j.togregorian()
        to_date_g = to_date_j.togregorian()
        existing = (
            db.query(DailyStatus)
            .filter(
                DailyStatus.user_id == normalized_user_id,
                DailyStatus.status_date >= from_date_g,
                DailyStatus.status_date <= to_date_g,
            )
            .order_by(DailyStatus.status_date)
            .all()
        )
        if existing:
            conflict_dates = ", ".join(
                jdatetime.date.fromgregorian(date=status.status_date).strftime("%Y/%m/%d")
                for status in existing
            )
            raise ValueError(
                f"برای تاریخ‌های زیر قبلاً وضعیتی ثبت شده است: {conflict_dates}"
            )

        current_date = from_date_g
        while current_date <= to_date_g:
            db.add(
                DailyStatus(
                    user_id=normalized_user_id,
                    status_date=current_date,
                    status_code=normalized_status,
                    description=description.strip() or None,
                    created_by=user.user_id,
                )
            )
            current_date += timedelta(days=1)
        db.commit()

        date_message = (
            from_date_j.strftime("%Y/%m/%d")
            if from_date_j == to_date_j
            else f"{from_date_j.strftime('%Y/%m/%d')} تا {to_date_j.strftime('%Y/%m/%d')}"
        )
        message = f"{STATUS_CODES[normalized_status]} برای {normalized_user_id} در تاریخ {date_message} ثبت شد"
        return RedirectResponse(
            url=build_redirect_url(referer, "success", message),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {exc}"),
            status_code=302,
        )


@router.post("/daily-status/{status_id}/edit")
async def edit_daily_status(
    request: Request,
    status_id: int,
    user_id: str = Form(...),
    date_str: str = Form(...),
    status_code: str = Form(...),
    description: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ویرایش مأموریت یا استراحت"""
    enforce_permission(db, user, "view_all_attendance")
    referer = request.headers.get("referer", "/admin/daily-status")

    try:
        normalized_user_id = user_id.strip()
        normalized_status = status_code.strip()
        if not normalized_user_id:
            raise ValueError("کد پرسنلی الزامی است")
        if normalized_status not in STATUS_CODES:
            raise ValueError(f"کد وضعیت نامعتبر: {normalized_status}")

        status = db.query(DailyStatus).filter(DailyStatus.id == status_id).first()
        if not status:
            raise ValueError("رکورد یافت نشد")

        date_j = jdatetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date()
        date_g = date_j.togregorian()
        existing = (
            db.query(DailyStatus)
            .filter(
                DailyStatus.user_id == normalized_user_id,
                DailyStatus.status_date == date_g,
                DailyStatus.id != status_id,
            )
            .first()
        )
        if existing:
            raise ValueError("برای این روز قبلاً وضعیتی ثبت شده است")

        status.user_id = normalized_user_id
        status.status_date = date_g
        status.status_code = normalized_status
        status.description = description.strip() or None
        db.commit()

        message = (
            f"{STATUS_CODES[normalized_status]} برای {normalized_user_id} "
            f"در {date_j.strftime('%Y/%m/%d')} به‌روزرسانی شد"
        )
        return RedirectResponse(
            url=build_redirect_url(referer, "success", message),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {exc}"),
            status_code=302,
        )


@router.post("/daily-status/{status_id}/delete")
async def delete_daily_status(
    request: Request,
    status_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """حذف مأموریت یا استراحت"""
    enforce_permission(db, user, "view_all_attendance")
    status = db.query(DailyStatus).filter(DailyStatus.id == status_id).first()
    if not status:
        referer = request.headers.get("referer", "/admin/daily-status")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "رکورد یافت نشد"),
            status_code=302,
        )

    db.delete(status)
    db.commit()

    referer = request.headers.get("referer", "/admin/daily-status")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "وضعیت حذف شد"),
        status_code=302,
    )
