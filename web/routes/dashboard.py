"""داشبورد کاربر"""
from datetime import timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
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

# 🆕 دیکشنری ترجمه انواع مرخصی
LEAVE_TYPE_NAMES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
    'CW': 'ذخیره سال قبل'
}

STATUS_NAMES = {
    'P': 'در انتظار',
    'A': 'تایید شده',
    'R': 'رد شده'
}


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

    # ترددهای امروز
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
    recent_requests_raw = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(5).all()

    # 🆕 تبدیل تاریخ‌ها و ترجمه نوع مرخصی
    recent_requests = []
    for req in recent_requests_raw:
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)
        recent_requests.append({
            'id': req.id,
            'leave_type': req.leave_type,
            'leave_type_name': LEAVE_TYPE_NAMES.get(req.leave_type, req.leave_type),
            'from_date_j': j_from.strftime('%Y/%m/%d'),
            'to_date_j': j_to.strftime('%Y/%m/%d'),
            'days_count': req.days_count,
            'status': req.status,
            'status_name': STATUS_NAMES.get(req.status, req.status),
            'reason': req.reason,
        })

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
    # 🆕 اطلاعات قرارداد فعال
    from models.contract import Contract
    active_contract = db.query(Contract).filter(
        and_(
            Contract.user_id == user.user_id,
            Contract.start_date <= today_g,
            or_(
                Contract.end_date == None,
                Contract.end_date >= today_g
            )
        )
    ).order_by(Contract.start_date.desc()).first()

    contract_info = None
    if active_contract:
        j_start = jdatetime.date.fromgregorian(date=active_contract.start_date)
        j_end = jdatetime.date.fromgregorian(date=active_contract.end_date) if active_contract.end_date else None

        # محاسبه روزهای باقی‌مانده
        if active_contract.end_date:
            days_remaining = (active_contract.end_date - today_g).days
            total_days = (active_contract.end_date - active_contract.start_date).days
            elapsed_days = (today_g - active_contract.start_date).days
            progress_percent = min(100, max(0, (elapsed_days / total_days * 100) if total_days > 0 else 0))
        else:
            days_remaining = None
            total_days = None
            elapsed_days = None
            progress_percent = 0

        contract_info = {
            'id': active_contract.id,
            'contract_type': active_contract.contract_type,
            'start_date_j': j_start.strftime('%Y/%m/%d'),
            'end_date_j': j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود',
            'days_remaining': days_remaining,
            'total_days': total_days,
            'elapsed_days': elapsed_days,
            'progress_percent': round(progress_percent, 1),
            'is_expiring_soon': days_remaining is not None and days_remaining <= 30,
            'is_expired': days_remaining is not None and days_remaining < 0,
        }

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "employee": employee,
        "today_j": today_j,
        "today_status": today_status,
        "today_attendance": today_attendance,
        "balances": balances_dict,
        "recent_requests": recent_requests,
        "month_attendance_count": month_attendance_count,
        "contract_info": contract_info,  # 🆕
        "is_admin": user.is_admin,
    })