"""
روتر انتقال و بازخرید مرخصی
فقط روت‌ها - بدون منطق تجاری
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import jdatetime

from web.dependencies import get_db, require_admin, get_current_user
from web.permissions import enforce_permission
from models.user import User
from models.employee import Employee
from models.leave_carry_forward_request import LeaveCarryForwardRequest, REQUEST_STATUS
from web.services.carry_forward_service import (
    user_chooses_use_leave,
    user_chooses_cash_out,
    admin_approve_cash_out,
    admin_reject_cash_out
)

router = APIRouter(tags=["Carry Forward"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def get_employee_name(db, user_id: str) -> str:
    emp = db.query(Employee).filter(Employee.user_id == user_id).first()
    return emp.full_name if emp else f"کاربر {user_id}"


@router.post("/carry-forward/choose")
async def choose_carry_forward(
    request: Request,
    choice: str = Form(...),
    leave_type: str = Form('AL'),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """انتخاب کاربر: قصد استفاده یا درخواست بازخرید"""
    if choice == 'USE':
        result = user_chooses_use_leave(db, user.user_id, leave_type)
    elif choice == 'CASH':
        result = user_chooses_cash_out(db, user.user_id, leave_type)
    else:
        result = {'success': False, 'error': 'انتخاب نامعتبر'}

    if result['success']:
        if choice == 'USE':
            msg = f"✅ {result['days']} روز مرخصی به سال جدید منتقل شد"
        else:
            msg = f"✅ درخواست بازخرید {result['days']} روز برای مدیر ارسال شد"
        return RedirectResponse(url=f"/dashboard?success={msg}", status_code=302)
    else:
        return RedirectResponse(url=f"/dashboard?error={result['error']}", status_code=302)


@router.get("/admin/carry-forward-requests", response_class=HTMLResponse)
async def carry_forward_requests_page(
    request: Request,
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست درخواست‌های انتقال/بازخرید مرخصی"""
    enforce_permission(db, user, 'view_leave_balances')
    has_filter = any([status_filter, show_all])
    requests_data = []

    if has_filter:
        query = db.query(LeaveCarryForwardRequest)
        if status_filter:
            query = query.filter(LeaveCarryForwardRequest.status == status_filter)
        elif not show_all:
            query = query.filter(LeaveCarryForwardRequest.status == 'P')

        requests = query.order_by(LeaveCarryForwardRequest.created_at.desc()).all()
        for r in requests:
            requests_data.append({
                'request': r,
                'full_name': get_employee_name(db, r.user_id),
                'status_name': r.status_name,
                'user_choice_name': r.user_choice_name,
            })

    pending_count = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.status == 'P'
    ).count()

    return templates.TemplateResponse(request, "admin/carry_forward_requests.html", {
        "user": user,
        "requests": requests_data,
        "total_count": len(requests_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "status_filter": status_filter or "",
        "pending_count": pending_count,
        "request_status": REQUEST_STATUS,
        "is_admin": True,
    })


@router.post("/admin/carry-forward-requests/{request_id}/approve")
async def approve_cash_out(
    request: Request,
    request_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """تایید درخواست بازخرید"""
    enforce_permission(db, user, 'approve_leave')
    result = admin_approve_cash_out(db, request_id, user.user_id)
    referer = request.headers.get("referer", "/admin/carry-forward-requests")
    if result['success']:
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "درخواست بازخرید تایید شد. مانده مرخصی صفر شد."),
            status_code=302
        )
    else:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", result['error']),
            status_code=302
        )


@router.post("/admin/carry-forward-requests/{request_id}/reject")
async def reject_cash_out(
    request: Request,
    request_id: int,
    admin_note: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """رد درخواست بازخرید → انتقال به سال جدید"""
    enforce_permission(db, user, 'approve_leave')
    result = admin_reject_cash_out(db, request_id, user.user_id, admin_note)
    referer = request.headers.get("referer", "/admin/carry-forward-requests")
    if result['success']:
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "درخواست رد شد. مرخصی به سال جدید منتقل شد."),
            status_code=302
        )
    else:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", result['error']),
            status_code=302
        )


@router.post("/carry-forward/postpone")
async def postpone_carry_forward(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """کاربر می‌خواهد بعداً تصمیم بگیرد - ۷ روز تعویق"""
    from datetime import timedelta
    postpone_until = datetime.now() + timedelta(days=7)
    request.session['carry_forward_postponed_until'] = postpone_until.isoformat()
    return RedirectResponse(
        url="/dashboard?info=باشه، ۷ روز دیگه دوباره یادآوری می‌کنیم 👌",
        status_code=302
    )


@router.get("/carry-forward/manage")
async def manage_carry_forward(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """پاک کردن دوره تعویق و نمایش مجدد مودال"""
    if 'carry_forward_postponed_until' in request.session:
        del request.session['carry_forward_postponed_until']
    return RedirectResponse(url="/dashboard", status_code=302)
