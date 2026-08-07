"""صفحه رکوردهای تردد"""
from datetime import timedelta
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import jdatetime
from typing import Optional

from web.dependencies import get_db, check_password_change
from models.user import User
from models.attendance import Attendance

router = APIRouter(tags=["Attendance"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

MONTH_NAMES = {
    1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر',
    5: 'مرداد', 6: 'شهریور', 7: 'مهر', 8: 'آبان',
    9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
}


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year
    if not month:
        month = today_j.month

    # بازه ماه
    month_start_j = jdatetime.date(year, month, 1)
    if month == 12:
        month_end_j = jdatetime.date(year, 12, 29)
    else:
        month_end_j = jdatetime.date(year, month + 1, 1) - timedelta(days=1)

    month_start_g = month_start_j.togregorian()
    month_end_g = month_end_j.togregorian()

    # رکوردها
    records = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user.user_id,
            Attendance.timestamp >= month_start_g,
            Attendance.timestamp <= month_end_g + timedelta(days=1),
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    # گروه‌بندی بر اساس روز
    days_dict = {}
    for record in records:
        day = record.timestamp.date()
        if day not in days_dict:
            days_dict[day] = []
        days_dict[day].append(record)

    days_list = []
    for day, day_records in sorted(days_dict.items(), reverse=True):
        j_day = jdatetime.date.fromgregorian(date=day)
        enters = [r for r in day_records if r.punch == 0]
        exits = [r for r in day_records if r.punch == 1]

        work_hours = 0
        first_enter = min(enters, key=lambda x: x.timestamp).timestamp if enters else None
        last_exit = max(exits, key=lambda x: x.timestamp).timestamp if exits else None

        if first_enter and last_exit:
            diff = (last_exit - first_enter).total_seconds() / 3600
            work_hours = max(0, diff)

        days_list.append({
            'date': day,
            'jalali_date': j_day.strftime('%Y/%m/%d'),
            'day_name': j_day.strftime('%A'),
            'records': day_records,
            'first_enter': first_enter,
            'last_exit': last_exit,
            'work_hours': work_hours,
            'is_friday': day.weekday() == 4,
        })

    return templates.TemplateResponse(request, "attendance.html", {
        "user": user,
        "year": year,
        "month": month,
        "month_name": MONTH_NAMES.get(month, ""),
        "days": days_list,
        "total_records": len(records),
        "is_admin": user.is_admin,
    })