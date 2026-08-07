"""داشبورد کاربر"""
from datetime import timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.attendance import Attendance
from models.daily_status import DailyStatus

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    today_j = jdatetime.date.today()
    today_g = today_j.togregorian()

    # اطلاعات کارمند
    employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()

    # وضعیت امروز
    today_status = db.query(DailyStatus).filter(
        and_(DailyStatus.user_id == user.user_id, DailyStatus.status_date == today_g)
    ).first()

    # تردهای امروز
    today_attendance = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user.user_id,
            func.date(Attendance.timestamp) == today_g,
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    # مانده مرخصی
    leave_balances = db.query(LeaveBalance).filter(
        and_(LeaveBalance.user_id == user.user_id, LeaveBalance.year == today_j.year)
    ).all()
    balances_dict = {lb.leave_type: lb.balance for lb in leave_balances}

    # درخواست‌های اخیر
    recent_requests = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(5).all()

    # آمار ماه
    month_start_j = jdatetime.date(today_j.year, today_j.month, 1)
    month_start_g = month_start_j.togregorian()
    month_attendance_count = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user.user_id,
            Attendance.timestamp >= month_start_g,
            Attendance.timestamp <= today_g + timedelta(days=1),
            Attendance.is_deleted == False,
            Attendance.punch == 0
        )
    ).count()

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "employee": employee,
        "today_j": today_j,
        "today_status": today_status,
        "today_attendance": today_attendance,
        "balances": balances_dict,
        "recent_requests": recent_requests,
        "month_attendance_count": month_attendance_count,
        "is_admin": user.is_admin,
    })