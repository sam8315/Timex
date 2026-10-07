"""داشبورد کاربر (+ نمای ادمین از نگاه کاربر)"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import jdatetime
from web.dependencies import get_db, check_password_change, require_admin
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.contract import Contract

from web.services.carry_forward_service import (
    get_unused_leave_from_previous_year,
    has_carry_forward_request,
    calculate_carry_forward_limit,
    analyze_yearly_contracts,
)
from models.leave_carry_forward_request import LeaveCarryForwardRequest

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# موقتاً خاموش تا پایان بازسازی و تأیید دفترکل مرخصی
CARRY_FORWARD_MODAL_ENABLED = False

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


def build_user_dashboard_context(
    db: Session,
    user_id: str,
    *,
    request: Optional[Request] = None,
    for_admin_view: bool = False,
) -> Dict[str, Any]:
    """دادهٔ داشبورد کاربر برای صفحهٔ خود کاربر یا نمای ادمین."""
    today_j = jdatetime.date.today()
    today_g = today_j.togregorian()

    target_user = db.query(User).filter(User.user_id == user_id).first()
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()

    today_status = db.query(DailyStatus).filter(
        and_(DailyStatus.user_id == user_id, DailyStatus.status_date == today_g)
    ).first()

    today_attendance = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user_id,
            func.date(Attendance.timestamp) == today_g,
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    leave_balances = db.query(LeaveBalance).filter(
        and_(LeaveBalance.user_id == user_id, LeaveBalance.year == today_j.year)
    ).all()
    balances_dict = {lb.leave_type: lb.balance for lb in leave_balances}

    # همان منطق صفحه مرخصی (وظیفه=دوره خدمت، بقیه=سال جاری+ذخیره)
    from web.services.leave_balance_overview_service import (
        resolve_user_al_availability,
    )
    al_avail = resolve_user_al_availability(db, user_id, year_j=today_j.year)
    total_al_available = al_avail['total']
    cw_days = al_avail.get('cw_days') or 0

    pending_items = []

    pending_leave_requests = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == 'P'
        )
    ).order_by(LeaveRequest.created_at.desc()).all()

    for req in pending_leave_requests:
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)
        pending_items.append({
            'type': 'leave',
            'type_name': 'مرخصی',
            'icon': '🏖️',
            'id': req.id,
            'title': f"مرخصی {LEAVE_TYPE_NAMES.get(req.leave_type, req.leave_type)}",
            'date_display': f"{j_from.strftime('%Y/%m/%d')} تا {j_to.strftime('%Y/%m/%d')}",
            'days_count': req.days_count,
            'unit': 'روز',
            'created_at': req.created_at,
            'status_name': 'در انتظار تایید',
            'detail_url': f"/leave/requests/{req.id}",
        })

    pending_cash_requests = db.query(LeaveCarryForwardRequest).filter(
        and_(
            LeaveCarryForwardRequest.user_id == user_id,
            LeaveCarryForwardRequest.status == 'P',
            LeaveCarryForwardRequest.user_choice == 'CASH'
        )
    ).order_by(LeaveCarryForwardRequest.created_at.desc()).all()

    for cf in pending_cash_requests:
        pending_items.append({
            'type': 'cash_out',
            'type_name': 'بازخرید مرخصی',
            'icon': '💰',
            'id': cf.id,
            'title': f"بازخرید مرخصی {LEAVE_TYPE_NAMES.get(cf.leave_type, cf.leave_type)}",
            'date_display': f"مرخصی سال {cf.from_year}",
            'days_count': cf.days_count,
            'unit': 'روز',
            'created_at': cf.created_at,
            'status_name': 'در انتظار تایید',
            'detail_url': f"/carry-forward/requests/{cf.id}",
        })

    pending_items.sort(key=lambda x: x['created_at'] or datetime.min, reverse=True)

    recent_requests_raw = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(5).all()

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

    month_start_j = jdatetime.date(today_j.year, today_j.month, 1)
    month_start_g = month_start_j.togregorian()
    month_attendance_count = db.query(Attendance).filter(
        and_(
            Attendance.user_id == user_id,
            Attendance.timestamp >= month_start_g,
            Attendance.timestamp <= today_g + timedelta(days=1),
            Attendance.is_deleted == False,
            Attendance.punch == 0
        )
    ).count()

    active_contract = db.query(Contract).filter(
        and_(
            Contract.user_id == user_id,
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
        j_end = (
            jdatetime.date.fromgregorian(date=active_contract.end_date)
            if active_contract.end_date
            else None
        )

        if active_contract.end_date:
            days_remaining = (active_contract.end_date - today_g).days
            total_days = (active_contract.end_date - active_contract.start_date).days
            elapsed_days = (today_g - active_contract.start_date).days
            progress_percent = min(
                100,
                max(0, (elapsed_days / total_days * 100) if total_days > 0 else 0),
            )
        else:
            days_remaining = None
            total_days = None
            elapsed_days = None
            progress_percent = 0

        contract_info = {
            'id': active_contract.id,
            'contract_type': (
                active_contract.contract_type_name
                if hasattr(active_contract, 'contract_type_name')
                else '-'
            ),
            'start_date_j': j_start.strftime('%Y/%m/%d'),
            'end_date_j': j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود',
            'days_remaining': days_remaining,
            'total_days': total_days,
            'elapsed_days': elapsed_days,
            'progress_percent': round(progress_percent, 1),
            'is_expiring_soon': days_remaining is not None and days_remaining <= 30,
            'is_expired': days_remaining is not None and days_remaining < 0,
        }

    last_login_display = None
    if for_admin_view:
        if target_user and target_user.last_login:
            try:
                last_login_j = jdatetime.datetime.fromgregorian(
                    datetime=target_user.last_login
                )
                last_login_display = last_login_j.strftime('%Y/%m/%d - %H:%M')
            except Exception:
                last_login_display = str(target_user.last_login)
        else:
            last_login_display = "بدون ورود ثبت‌شده"
    elif request is not None:
        previous_login_str = request.session.get('previous_login')
        if previous_login_str:
            try:
                previous_login = datetime.fromisoformat(previous_login_str)
                last_login_j = jdatetime.datetime.fromgregorian(
                    datetime=previous_login
                )
                last_login_display = last_login_j.strftime('%Y/%m/%d - %H:%M')
            except Exception:
                last_login_display = previous_login_str
        else:
            last_login_display = "اولین ورود شما"

    unused_leave = (
        get_unused_leave_from_previous_year(db, user_id)
        if CARRY_FORWARD_MODAL_ENABLED
        else {}
    )
    carry_forward_year = today_j.year - 1
    show_carry_forward_modal = False
    has_pending_carry_forward = False
    carry_forward_limit = None
    contract_analysis = None

    if CARRY_FORWARD_MODAL_ENABLED and unused_leave and not for_admin_view:
        has_pending_carry_forward = not has_carry_forward_request(
            db, user_id, carry_forward_year
        )
        carry_forward_limit = calculate_carry_forward_limit(
            db, user_id, carry_forward_year
        )
        contract_analysis = analyze_yearly_contracts(
            db, user_id, carry_forward_year
        )

        if has_pending_carry_forward and request is not None:
            postponed_until = request.session.get('carry_forward_postponed_until')
            should_show = True
            if postponed_until:
                try:
                    postponed_date = datetime.fromisoformat(postponed_until)
                    if datetime.now() < postponed_date:
                        should_show = False
                except Exception:
                    should_show = True
            if should_show:
                show_carry_forward_modal = True

    display_name = None
    if employee and getattr(employee, 'full_name', None):
        display_name = employee.full_name
    elif target_user:
        display_name = target_user.name or user_id
    else:
        display_name = user_id

    return {
        'target_user': target_user,
        'employee': employee,
        'today_j': today_j,
        'today_status': today_status,
        'today_attendance': today_attendance,
        'balances': balances_dict,
        'pending_items': pending_items,
        'pending_count': len(pending_items),
        'recent_requests': recent_requests,
        'month_attendance_count': month_attendance_count,
        'contract_info': contract_info,
        'last_login_display': last_login_display,
        'unused_leave': unused_leave,
        'carry_forward_year': carry_forward_year,
        'show_carry_forward_modal': show_carry_forward_modal,
        'has_pending_carry_forward': has_pending_carry_forward,
        'carry_forward_limit': carry_forward_limit,
        'contract_analysis': contract_analysis,
        'total_al_available': total_al_available,
        'cw_days': cw_days,
        'target_user_id': user_id,
        'target_display_name': display_name,
        'viewing_as_admin': for_admin_view,
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    ctx = build_user_dashboard_context(
        db, user.user_id, request=request, for_admin_view=False
    )
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "employee": ctx["employee"],
        "today_j": ctx["today_j"],
        "today_status": ctx["today_status"],
        "today_attendance": ctx["today_attendance"],
        "balances": ctx["balances"],
        "pending_items": ctx["pending_items"],
        "pending_count": ctx["pending_count"],
        "recent_requests": ctx["recent_requests"],
        "month_attendance_count": ctx["month_attendance_count"],
        "contract_info": ctx["contract_info"],
        "is_admin": user.is_admin,
        "last_login_display": ctx["last_login_display"],
        "unused_leave": ctx["unused_leave"],
        "carry_forward_year": ctx["carry_forward_year"],
        "show_carry_forward_modal": ctx["show_carry_forward_modal"],
        "has_pending_carry_forward": ctx["has_pending_carry_forward"],
        "carry_forward_limit": ctx["carry_forward_limit"],
        "contract_analysis": ctx["contract_analysis"],
        "total_al_available": ctx["total_al_available"],
        "cw_days": ctx["cw_days"],
        "viewing_as_admin": False,
        "target_user_id": user.user_id,
        "target_display_name": None,
    })


@router.get("/admin/dashboard/user/{target_user_id}", response_class=HTMLResponse)
async def admin_user_dashboard(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """داشبورد از نگاه کاربر (برای ادمین)."""
    target = db.query(User).filter(User.user_id == target_user_id).first()
    if not target:
        return RedirectResponse(
            url="/admin/users?error=کاربر یافت نشد",
            status_code=302,
        )
    ctx = build_user_dashboard_context(
        db, target_user_id, request=request, for_admin_view=True
    )
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "employee": ctx["employee"],
        "today_j": ctx["today_j"],
        "today_status": ctx["today_status"],
        "today_attendance": ctx["today_attendance"],
        "balances": ctx["balances"],
        "pending_items": ctx["pending_items"],
        "pending_count": ctx["pending_count"],
        "recent_requests": ctx["recent_requests"],
        "month_attendance_count": ctx["month_attendance_count"],
        "contract_info": ctx["contract_info"],
        "is_admin": True,
        "last_login_display": ctx["last_login_display"],
        "unused_leave": ctx["unused_leave"],
        "carry_forward_year": ctx["carry_forward_year"],
        "show_carry_forward_modal": False,
        "has_pending_carry_forward": False,
        "carry_forward_limit": ctx["carry_forward_limit"],
        "contract_analysis": ctx["contract_analysis"],
        "total_al_available": ctx["total_al_available"],
        "cw_days": ctx["cw_days"],
        "viewing_as_admin": True,
        "target_user_id": target_user_id,
        "target_display_name": ctx["target_display_name"],
    })
