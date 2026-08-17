"""
پنل مدیریت مأموریت و استراحت
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin
from models.user import User
from models.employee import Employee
from models.daily_status import DailyStatus, STATUS_CODES

router = APIRouter(tags=["Admin Daily Status"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def get_employee_name(db, user_id: str) -> str:
    emp = db.query(Employee).filter(Employee.user_id == user_id).first()
    return emp.full_name if emp else f"کاربر {user_id}"


@router.get("/daily-status", response_class=HTMLResponse)
async def daily_status_page(
        request: Request,
        search: Optional[str] = Query(None),
        status_filter: Optional[str] = Query(None),
        year: Optional[int] = Query(None),
        month: Optional[int] = Query(None),
        show_all: Optional[str] = Query(None),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """لیست مأموریت‌ها و استراحت‌ها"""
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year
    if not month:
        month = today_j.month

    has_filter = any([search, status_filter, show_all])
    statuses_data = []

    if has_filter:
        # محاسبه بازه ماه
        month_start_j = jdatetime.date(year, month, 1)
        if month == 12:
            month_end_j = jdatetime.date(year, 12, 29)
        else:
            month_end_j = jdatetime.date(year, month + 1, 1) - jdatetime.timedelta(days=1)

        month_start_g = month_start_j.togregorian()
        month_end_g = month_end_j.togregorian()

        query = db.query(DailyStatus).filter(
            DailyStatus.status_date >= month_start_g,
            DailyStatus.status_date <= month_end_g
        )

        if status_filter:
            query = query.filter(DailyStatus.status_code == status_filter)

        if search and search.strip():
            term = search.strip()
            query = query.outerjoin(Employee, DailyStatus.user_id == Employee.user_id).filter(
                or_(
                    DailyStatus.user_id.ilike(f"%{term}%"),
                    Employee.first_name.ilike(f"%{term}%"),
                    Employee.last_name.ilike(f"%{term}%")
                )
            )

        statuses = query.order_by(DailyStatus.status_date.desc()).all()

        for s in statuses:
            date_j = jdatetime.date.fromgregorian(date=s.status_date)
            statuses_data.append({
                'status': s,
                'full_name': get_employee_name(db, s.user_id),
                'date_j': date_j.strftime('%Y/%m/%d'),
                'status_name': s.status_name,
            })

    return templates.TemplateResponse(request, "admin/daily_status.html", {
        "user": user,
        "statuses": statuses_data,
        "total_count": len(statuses_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search or "",
        "status_filter": status_filter or "",
        "year": year,
        "month": month,
        "available_years": list(range(today_j.year - 2, today_j.year + 3)),
        "available_months": list(range(1, 13)),
        "month_names": {
            1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
            4: 'تیر', 5: 'مرداد', 6: 'شهریور',
            7: 'مهر', 8: 'آبان', 9: 'آذر',
            10: 'دی', 11: 'بهمن', 12: 'اسفند'
        },
        "status_codes": STATUS_CODES,
        "is_admin": True,
    })


@router.post("/daily-status/add")
async def add_daily_status(
        request: Request,
        user_id: str = Form(...),
        date_str: str = Form(...),
        status_code: str = Form(...),
        description: str = Form(""),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """ثبت مأموریت یا استراحت"""
    try:
        # بررسی کد وضعیت
        if status_code not in STATUS_CODES:
            raise ValueError(f"کد وضعیت نامعتبر: {status_code}")

        # تبدیل تاریخ شمسی
        date_j = jdatetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date()
        date_g = date_j.togregorian()

        # بررسی تکراری نبودن
        existing = db.query(DailyStatus).filter(
            DailyStatus.user_id == user_id,
            DailyStatus.status_date == date_g
        ).first()
        if existing:
            referer = request.headers.get("referer", "/admin/daily-status")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "برای این روز قبلاً وضعیتی ثبت شده است"),
                status_code=302
            )

        # ثبت
        new_status = DailyStatus(
            user_id=user_id,
            status_date=date_g,
            status_code=status_code,
            description=description.strip() or None,
            created_by=user.user_id
        )
        db.add(new_status)
        db.commit()

        status_name = STATUS_CODES[status_code]
        referer = request.headers.get("referer", "/admin/daily-status")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"{status_name} برای {user_id} ثبت شد"),
            status_code=302
        )
    except Exception as e:
        referer = request.headers.get("referer", "/admin/daily-status")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/daily-status/{status_id}/delete")
async def delete_daily_status(
        request: Request,
        status_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """حذف مأموریت یا استراحت"""
    status = db.query(DailyStatus).filter(DailyStatus.id == status_id).first()
    if not status:
        referer = request.headers.get("referer", "/admin/daily-status")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "رکورد یافت نشد"),
            status_code=302
        )

    db.delete(status)
    db.commit()

    referer = request.headers.get("referer", "/admin/daily-status")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "وضعیت حذف شد"),
        status_code=302
    )