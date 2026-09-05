"""
پنل مدیریت نظام وظیفه
"""
from datetime import date
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin
from models.user import User
from models.employee import Employee
from models.military_service import (
    MilitaryService, MILITARY_STATUS, EXEMPTION_TYPES, SERVICE_TYPES,
    calculate_end_date
)

router = APIRouter(tags=["Admin Military"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


@router.get("/military", response_class=HTMLResponse)
async def military_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    exemption_filter: Optional[str] = Query(None),
    service_type_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست سوابق نظام وظیفه"""
    has_filter = any([search, status_filter, exemption_filter, service_type_filter, show_all])
    records_data = []

    if has_filter:
        query = db.query(MilitaryService)

        # جستجو بر اساس کد پرسنلی یا نام
        if search and search.strip():
            search_term = search.strip()
            query = query.outerjoin(Employee, MilitaryService.user_id == Employee.user_id).filter(
                or_(
                    MilitaryService.user_id.ilike(f"%{search_term}%"),
                    Employee.first_name.ilike(f"%{search_term}%"),
                    Employee.last_name.ilike(f"%{search_term}%")
                )
            )

        # فیلتر وضعیت
        if status_filter:
            query = query.filter(MilitaryService.status == status_filter)

        # فیلتر نوع معافیت
        if exemption_filter:
            query = query.filter(MilitaryService.exemption_type == exemption_filter)

        # فیلتر نوع خدمت
        if service_type_filter:
            query = query.filter(MilitaryService.service_type == service_type_filter)

        records = query.order_by(MilitaryService.created_at.desc()).all()

        for r in records:
            employee = db.query(Employee).filter(Employee.user_id == r.user_id).first()

            # تبدیل تاریخ‌ها به شمسی
            start_j = jdatetime.date.fromgregorian(date=r.start_date) if r.start_date else None
            expected_end_j = jdatetime.date.fromgregorian(date=r.expected_end_date) if r.expected_end_date else None
            actual_end_j = jdatetime.date.fromgregorian(date=r.actual_end_date) if r.actual_end_date else None

            records_data.append({
                'record': r,
                'employee': employee,
                'full_name': employee.full_name if employee else f"کاربر {r.user_id}",
                'start_j': start_j.strftime('%Y/%m/%d') if start_j else '-',
                'expected_end_j': expected_end_j.strftime('%Y/%m/%d') if expected_end_j else '-',
                'actual_end_j': actual_end_j.strftime('%Y/%m/%d') if actual_end_j else '-',
            })

    return templates.TemplateResponse(request, "admin/military.html", {
        "user": user,
        "records": records_data,
        "total_count": len(records_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search or "",
        "status_filter": status_filter or "",
        "exemption_filter": exemption_filter or "",
        "service_type_filter": service_type_filter or "",
        "military_statuses": MILITARY_STATUS,
        "exemption_types": EXEMPTION_TYPES,
        "service_types": SERVICE_TYPES,
        "is_admin": True,
    })


@router.post("/military/add")
async def add_military(
    request: Request,
    user_id: str = Form(...),
    status: str = Form(...),
    service_type: str = Form(""),
    exemption_type: str = Form(""),
    exemption_reason: str = Form(""),
    start_date_str: str = Form(""),
    expected_end_date_str: str = Form(""),
    actual_end_date_str: str = Form(""),
    total_deduction_days: int = Form(0),
    used_deduction_days: int = Form(0),
    service_number: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ثبت سابقه نظام وظیفه جدید"""
    try:
        # اعتبارسنجی وضعیت
        if status not in MILITARY_STATUS:
            raise ValueError("وضعیت نامعتبر است")

        # اعتبارسنجی نوع خدمت
        if service_type and service_type not in SERVICE_TYPES:
            raise ValueError("نوع خدمت نامعتبر است")

        # بررسی وجود کاربر
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            referer = request.headers.get("referer", "/admin/military")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "کاربر یافت نشد"),
                status_code=302
            )

        # بررسی تکراری نبودن
        existing = db.query(MilitaryService).filter(MilitaryService.user_id == user_id).first()
        if existing:
            referer = request.headers.get("referer", "/admin/military")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "این کاربر قبلاً سابقه نظام وظیفه دارد"),
                status_code=302
            )

        # تبدیل تاریخ‌های شمسی
        start_date = None
        if start_date_str.strip():
            start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
            start_date = start_j.togregorian()

        expected_end_date = None
        if expected_end_date_str.strip():
            expected_end_j = jdatetime.datetime.strptime(expected_end_date_str.strip(), "%Y/%m/%d").date()
            expected_end_date = expected_end_j.togregorian()
        elif start_date and service_type:
            # محاسبه خودکار تاریخ پایان از روی نوع خدمت
            expected_end_date = calculate_end_date(start_date, service_type, total_deduction_days)

        actual_end_date = None
        if actual_end_date_str.strip():
            actual_end_j = jdatetime.datetime.strptime(actual_end_date_str.strip(), "%Y/%m/%d").date()
            actual_end_date = actual_end_j.togregorian()

        # اعتبارسنجی تاریخ‌ها
        if start_date and expected_end_date and start_date >= expected_end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان مورد انتظار باشد")

        if start_date and actual_end_date and start_date >= actual_end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان واقعی باشد")

        # نوع معافیت فقط برای وضعیت معاف
        if status != 'exempted':
            exemption_type = None
            exemption_reason = None

        # ایجاد سابقه
        new_record = MilitaryService(
            user_id=user_id,
            status=status,
            service_type=service_type.strip() if service_type else None,
            exemption_type=exemption_type.strip() if exemption_type else None,
            exemption_reason=exemption_reason.strip() if exemption_reason else None,
            start_date=start_date,
            expected_end_date=expected_end_date,
            actual_end_date=actual_end_date,
            total_deduction_days=total_deduction_days,
            used_deduction_days=used_deduction_days,
            service_number=service_number.strip() if service_number else None,
            notes=notes.strip() if notes else None
        )
        db.add(new_record)
        db.commit()

        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "سابقه نظام وظیفه ثبت شد"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/military/{record_id}/edit")
async def edit_military(
    request: Request,
    record_id: int,
    status: str = Form(...),
    service_type: str = Form(""),
    exemption_type: str = Form(""),
    exemption_reason: str = Form(""),
    start_date_str: str = Form(""),
    expected_end_date_str: str = Form(""),
    actual_end_date_str: str = Form(""),
    total_deduction_days: int = Form(0),
    used_deduction_days: int = Form(0),
    service_number: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش سابقه نظام وظیفه"""
    record = db.query(MilitaryService).filter(MilitaryService.id == record_id).first()
    if not record:
        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "سابقه یافت نشد"),
            status_code=302
        )

    try:
        # اعتبارسنجی وضعیت
        if status not in MILITARY_STATUS:
            raise ValueError("وضعیت نامعتبر است")

        # اعتبارسنجی نوع خدمت
        if service_type and service_type not in SERVICE_TYPES:
            raise ValueError("نوع خدمت نامعتبر است")

        # تبدیل تاریخ‌ها
        start_date = None
        if start_date_str.strip():
            start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
            start_date = start_j.togregorian()

        expected_end_date = None
        if expected_end_date_str.strip():
            expected_end_j = jdatetime.datetime.strptime(expected_end_date_str.strip(), "%Y/%m/%d").date()
            expected_end_date = expected_end_j.togregorian()
        elif start_date and service_type:
            # محاسبه خودکار
            expected_end_date = calculate_end_date(start_date, service_type, total_deduction_days)

        actual_end_date = None
        if actual_end_date_str.strip():
            actual_end_j = jdatetime.datetime.strptime(actual_end_date_str.strip(), "%Y/%m/%d").date()
            actual_end_date = actual_end_j.togregorian()

        # اعتبارسنجی تاریخ‌ها
        if start_date and expected_end_date and start_date >= expected_end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان مورد انتظار باشد")

        if start_date and actual_end_date and start_date >= actual_end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان واقعی باشد")

        # نوع معافیت فقط برای وضعیت معاف
        if status != 'exempted':
            exemption_type = None
            exemption_reason = None

        # بروزرسانی
        record.status = status
        record.service_type = service_type.strip() if service_type else None
        record.exemption_type = exemption_type.strip() if exemption_type else None
        record.exemption_reason = exemption_reason.strip() if exemption_reason else None
        record.start_date = start_date
        record.expected_end_date = expected_end_date
        record.actual_end_date = actual_end_date
        record.total_deduction_days = total_deduction_days
        record.used_deduction_days = used_deduction_days
        record.service_number = service_number.strip() if service_number else None
        record.notes = notes.strip() if notes else None

        db.commit()

        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "سابقه ویرایش شد"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/military/{record_id}/delete")
async def delete_military(
    request: Request,
    record_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف سابقه نظام وظیفه"""
    record = db.query(MilitaryService).filter(MilitaryService.id == record_id).first()
    if not record:
        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "سابقه یافت نشد"),
            status_code=302
        )

    try:
        db.delete(record)
        db.commit()

        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "سابقه حذف شد"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/military")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.get("/calculate_end_date")
async def api_calculate_end_date(
    request: Request,
    start_date_str: str = Query(...),
    service_type: str = Query(...),
    deduction_days: int = Query(0),
    user: User = Depends(require_admin),
):
    """محاسبه تاریخ پایان از روی نوع خدمت (API برای فرم)"""
    try:
        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()
        end_date = calculate_end_date(start_date, service_type, deduction_days)
        end_j = jdatetime.date.fromgregorian(date=end_date)
        return JSONResponse({
            'end_date': end_j.strftime('%Y/%m/%d'),
            'months': SERVICE_TYPES.get(service_type, {}).get('months', 21),
        })
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=400)
