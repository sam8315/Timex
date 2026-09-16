"""پنل مدیریت تعطیلات"""
from datetime import date
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from models.user import User
from models.holiday import Holiday

router = APIRouter(tags=["Holidays"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

GROUP_NAMES = {
    '': 'ملی (همه)',
    '1': 'رسمی',
    '2': 'وظیفه',
    '3': 'خریدخدمت',
    '4': 'قراردادی',
    '5': 'پزشک'
}


@router.get("/holidays", response_class=HTMLResponse)
async def holidays_page(
    request: Request,
    year: Optional[int] = Query(None),
    group_filter: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست تعطیلات با فیلتر"""
    enforce_permission(db, user, 'view_dashboard')
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year

    # فیلتر سال (میلادی بر اساس سال شمسی)
    year_start_j = jdatetime.date(year, 1, 1)
    year_end_j = jdatetime.date(year, 12, 29)
    year_start_g = year_start_j.togregorian()
    year_end_g = year_end_j.togregorian()

    query = db.query(Holiday).filter(
        and_(
            Holiday.holiday_date >= year_start_g,
            Holiday.holiday_date <= year_end_g
        )
    )

    if group_filter:
        if group_filter == 'national':
            query = query.filter(Holiday.group_id == None)
        else:
            query = query.filter(Holiday.group_id == group_filter)

    holidays = query.order_by(Holiday.holiday_date).all()

    # تبدیل به شمسی
    holidays_data = []
    for h in holidays:
        j_date = jdatetime.date.fromgregorian(date=h.holiday_date)
        holidays_data.append({
            'id': h.id,
            'date_j': j_date.strftime('%Y/%m/%d'),
            'date_j_obj': j_date,
            'title': h.title,
            'group_id': h.group_id,
            'group_name': h.group_name,
            'is_national': h.is_national,
            'day_name': ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنج‌شنبه', 'جمعه'][j_date.weekday()],
        })

    # لیست سال‌ها (۵ سال اخیر و ۵ سال آینده)
    available_years = list(range(year - 2, year + 3))

    return templates.TemplateResponse(request, "admin/holidays.html", {
        "user": user,
        "year": year,
        "available_years": available_years,
        "group_filter": group_filter or "",
        "holidays": holidays_data,
        "total_count": len(holidays_data),
        "group_names": GROUP_NAMES,
        "is_admin": True,
    })


@router.post("/holidays/add")
async def add_holiday(
    request: Request,
    date_str: str = Form(...),
    title: str = Form(...),
    group_id: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """افزودن تعطیلی جدید"""
    enforce_permission(db, user, 'view_dashboard')
    try:
        # تبدیل تاریخ شمسی به میلادی
        j_date = jdatetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        # بررسی تکراری نبودن
        existing = db.query(Holiday).filter(Holiday.holiday_date == g_date).first()
        if existing:
            referer = request.headers.get("referer", "/admin/holidays")
            return RedirectResponse(
                url=f"{referer}&error=این تاریخ قبلاً ثبت شده است",
                status_code=302
            )

        # افزودن
        holiday = Holiday(
            holiday_date=g_date,
            title=title.strip(),
            is_national=(group_id == ""),
            group_id=group_id if group_id else None
        )
        db.add(holiday)
        db.commit()

        referer = request.headers.get("referer", "/admin/holidays")
        return RedirectResponse(url=f"/admin/holidays?success=تعطیلی اضافه شد", status_code=302)
    except Exception as e:
        referer = request.headers.get("referer", "/admin/holidays")
        return RedirectResponse(url=f"{referer}&error=خطا: {str(e)}", status_code=302)


@router.post("/holidays/{holiday_id}/edit")
async def edit_holiday(
    request: Request,
    holiday_id: int,
    title: str = Form(...),
    group_id: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش تعطیلی"""
    enforce_permission(db, user, 'view_dashboard')
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        return RedirectResponse(url="/admin/holidays?error=یافت نشد", status_code=302)

    holiday.title = title.strip()
    holiday.group_id = group_id if group_id else None
    holiday.is_national = (group_id == "")
    db.commit()

    referer = request.headers.get("referer", "/admin/holidays")
    return RedirectResponse(url=f"{referer}&success=ویرایش انجام شد", status_code=302)


@router.post("/holidays/{holiday_id}/delete")
async def delete_holiday(
    request: Request,
    holiday_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف تعطیلی"""
    enforce_permission(db, user, 'view_dashboard')
    holiday = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if not holiday:
        return RedirectResponse(url="/admin/holidays?error=یافت نشد", status_code=302)

    db.delete(holiday)
    db.commit()

    referer = request.headers.get("referer", "/admin/holidays")
    return RedirectResponse(url=f"{referer}&success=حذف انجام شد", status_code=302)