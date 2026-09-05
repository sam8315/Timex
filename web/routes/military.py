"""صفحه نظام وظیفه کاربر"""
from datetime import date
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.military_service import MilitaryService, MILITARY_STATUS, EXEMPTION_TYPES, SERVICE_TYPES

router = APIRouter(tags=["Military"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/military", response_class=HTMLResponse)
async def military_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    """صفحه نظام وظیفه کاربر"""
    today_g = date.today()
    today_j = jdatetime.date.today()

    record = db.query(MilitaryService).filter(
        MilitaryService.user_id == user.user_id
    ).first()

    # تبدیل تاریخ‌ها به شمسی
    record_data = None
    if record:
        start_j = jdatetime.date.fromgregorian(date=record.start_date) if record.start_date else None
        expected_end_j = jdatetime.date.fromgregorian(date=record.expected_end_date) if record.expected_end_date else None
        actual_end_j = jdatetime.date.fromgregorian(date=record.actual_end_date) if record.actual_end_date else None

        # محاسبه روزهای باقیمانده
        days_remaining = None
        if record.expected_end_date:
            days_remaining = max(0, (record.expected_end_date - today_g).days)

        # محاسبه مدت خدمت سپری شده
        days_elapsed = None
        if record.start_date:
            end = record.actual_end_date or today_g
            days_elapsed = (end - record.start_date).days + 1

        # محاسبه درصد پیشرفت
        progress_percent = None
        if record.start_date and record.expected_end_date:
            total_days = (record.expected_end_date - record.start_date).days
            if total_days > 0:
                progress_percent = round(min(100, (days_elapsed / total_days) * 100), 1)

        # محاسبه درصد کسر خدمت
        deduction_percent = None
        if record.total_deduction_days > 0:
            deduction_percent = round(
                (record.used_deduction_days / record.total_deduction_days) * 100, 1
            )

        record_data = {
            'record': record,
            'start_j': start_j.strftime('%Y/%m/%d') if start_j else None,
            'expected_end_j': expected_end_j.strftime('%Y/%m/%d') if expected_end_j else None,
            'actual_end_j': actual_end_j.strftime('%Y/%m/%d') if actual_end_j else None,
            'days_remaining': days_remaining,
            'days_elapsed': days_elapsed,
            'progress_percent': progress_percent,
            'deduction_percent': deduction_percent,
            'remaining_deduction_days': record.remaining_deduction_days,
        }

    return templates.TemplateResponse(request, "military.html", {
        "user": user,
        "today_j": today_j,
        "record_data": record_data,
        "military_statuses": MILITARY_STATUS,
        "exemption_types": EXEMPTION_TYPES,
        "service_types": SERVICE_TYPES,
        "is_admin": user.is_admin,
    })
