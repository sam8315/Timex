"""صفحه مرخصی‌ها"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from core.leave_request_manager import LeaveRequestManager

router = APIRouter(tags=["Leave"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

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


@router.get("/leave", response_class=HTMLResponse)
async def leave_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    today_j = jdatetime.date.today()

    # مانده مرخصی
    balances = db.query(LeaveBalance).filter(
        and_(LeaveBalance.user_id == user.user_id, LeaveBalance.year == today_j.year)
    ).all()
    balances_dict = {
        lb.leave_type: {
            'balance': lb.balance,
            'name': LEAVE_TYPE_NAMES.get(lb.leave_type, lb.leave_type)
        }
        for lb in balances
    }

    # درخواست‌ها
    requests_raw = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(20).all()

    # 🆕 تبدیل تاریخ‌ها و ترجمه
    leave_requests = []
    for req in requests_raw:
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)
        leave_requests.append({
            'id': req.id,
            'leave_type': req.leave_type,
            'leave_type_name': LEAVE_TYPE_NAMES.get(req.leave_type, req.leave_type),
            'from_date_j': j_from.strftime('%Y/%m/%d'),
            'to_date_j': j_to.strftime('%Y/%m/%d'),
            'days_count': req.days_count,
            'status': req.status,
            'status_name': STATUS_NAMES.get(req.status, req.status),
            'reason': req.reason,
            'created_at_j': jdatetime.date.fromgregorian(date=req.created_at.date()).strftime('%Y/%m/%d'),
        })

    return templates.TemplateResponse(request, "leave.html", {
        "user": user,
        "today_j": today_j,
        "balances": balances_dict,
        "leave_requests": leave_requests,
        "leave_type_names": LEAVE_TYPE_NAMES,
        "status_names": STATUS_NAMES,
        "is_admin": user.is_admin,
    })


@router.post("/leave/request")
async def submit_leave_request(
    request: Request,
    leave_type: str = Form(...),
    from_date_str: str = Form(...),
    to_date_str: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(check_password_change),
):
    try:
        j_from = jdatetime.datetime.strptime(from_date_str, "%Y/%m/%d").date()
        j_to = jdatetime.datetime.strptime(to_date_str, "%Y/%m/%d").date()
        g_from = j_from.togregorian()
        g_to = j_to.togregorian()
    except Exception:
        return RedirectResponse(url="/leave?error=تاریخ نامعتبر", status_code=302)

    manager = LeaveRequestManager()
    try:
        result = manager.create_request(
            user_id=user.user_id,
            leave_type=leave_type,
            from_date=g_from,
            to_date=g_to,
            reason=reason
        )
    finally:
        manager.close()

    if result['success']:
        return RedirectResponse(url="/leave?success=درخواست ثبت شد", status_code=302)
    else:
        return RedirectResponse(url=f"/leave?error={result['message']}", status_code=302)