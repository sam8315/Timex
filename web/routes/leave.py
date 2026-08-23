"""
صفحه درخواست مرخصی کاربر
"""
from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime
from typing import Optional

from web.dependencies import get_db, get_current_user, check_password_change
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.contract import Contract
from fastapi import Query
from models.holiday import Holiday

router = APIRouter(tags=["Leave"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# انواع مرخصی مجاز برای درخواست
LEAVE_TYPES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',          # 🆕
    'CW': 'ذخیره سال قبل',   # 🆕
}

# 🆕 انواع مرخصی که فقط در صورت داشتن مانده نمایش داده می‌شوند
CONDITIONAL_LEAVE_TYPES = {'RL', 'CW'}

STATUS_NAMES = {
    'P': '⏳ در انتظار',
    'A': '✅ تایید شده',
    'R': '❌ رد شده',
    'D': '🗑️ حذف شده',
}


def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def calculate_leave_days(
    db: Session,
    user_id: str,
    from_date: date,
    to_date: date
) -> int:
    """
    محاسبه تعداد روزهای مرخصی با کسر تعطیلات و جمعه‌ها

    اولویت:
    ۱. تعطیل رسمی/گروهی → شمرده نمی‌شود
    ۲. جمعه → شمرده نمی‌شود
    ۳. روزهای عادی → شمرده می‌شود
    """
    # دریافت گروه کاربر (برای تعطیلات گروهی)
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    user_group = employee.department if employee else None

    days = 0
    current = from_date

    while current <= to_date:
        # بررسی تعطیل بودن
        holiday = db.query(Holiday).filter(Holiday.holiday_date == current).first()

        is_holiday_for_user = False
        if holiday:
            # ملی یا گروه کاربر
            if holiday.group_id is None or holiday.group_id == user_group:
                is_holiday_for_user = True

        # بررسی جمعه
        j_date = jdatetime.date.fromgregorian(date=current)
        is_friday = j_date.weekday() == 4

        if not is_holiday_for_user and not is_friday:
            days += 1

        current += timedelta(days=1)

    return days


def get_user_leave_balance(db: Session, user_id: str, year: int) -> dict:
    """دریافت مانده مرخصی کاربر برای یک سال"""
    balances = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.user_id == user_id,
            LeaveBalance.year == year
        )
    ).all()

    return {b.leave_type: b.balance for b in balances}


@router.get("/leave", response_class=HTMLResponse)
async def leave_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """صفحه درخواست مرخصی"""
    today_j = jdatetime.date.today()
    current_year = today_j.year

    # دریافت مانده مرخصی سال جاری
    balances = get_user_leave_balance(db, user.user_id, current_year)

    # 🆕 فقط انواع مرخصی که کاربر می‌تواند درخواست دهد را نشان بده
    # - AL و SL: همیشه نمایش داده می‌شوند
    # - RL و CW: فقط اگر مانده > 0 باشد نمایش داده می‌شوند
    available_leave_types = {}
    for code, name in LEAVE_TYPES.items():
        if code in CONDITIONAL_LEAVE_TYPES:
            # انواع شرطی: فقط اگر مانده دارند نمایش داده شوند
            if balances.get(code, 0) > 0:
                available_leave_types[code] = name
        else:
            # انواع عادی: همیشه نمایش داده شوند
            available_leave_types[code] = name

    # دریافت درخواست‌های اخیر
    recent_requests_raw = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(20).all()

    recent_requests = []
    for req in recent_requests_raw:
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)
        recent_requests.append({
            'id': req.id,
            'leave_type': req.leave_type,
            'leave_type_name': LEAVE_TYPES.get(req.leave_type, req.leave_type),
            'from_date_j': j_from.strftime('%Y/%m/%d'),
            'to_date_j': j_to.strftime('%Y/%m/%d'),
            'days_count': req.days_count,
            'reason': req.reason,
            'status': req.status,
            'status_name': STATUS_NAMES.get(req.status, req.status),
            'rejection_reason': req.rejection_reason,
            'created_at': req.created_at.strftime('%Y/%m/%d %H:%M') if req.created_at else '',
        })

    # آمار درخواست‌ها
    pending_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'P')
    ).count()

    approved_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'A')
    ).count()

    rejected_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'R')
    ).count()

    return templates.TemplateResponse(request, "leave.html", {
        "user": user,
        "today_j": today_j.strftime('%Y/%m/%d'),
        "current_year": current_year,
        "balances": balances,
        "al_balance": balances.get('AL', 0),
        "sl_balance": balances.get('SL', 0),
        "rl_balance": balances.get('RL', 0),   # 🆕
        "cw_balance": balances.get('CW', 0),   # 🆕
        "recent_requests": recent_requests,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "leave_types": available_leave_types,  # 🆕 لیست فیلتر شده
        "is_admin": user.is_admin,
    })


@router.post("/leave/request")
async def submit_leave_request(
    request: Request,
    leave_type: str = Form(...),
    from_date_str: str = Form(...),
    to_date_str: str = Form(...),
    reason: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """ثبت درخواست مرخصی جدید"""
    try:
        # اعتبارسنجی نوع مرخصی
        if leave_type not in LEAVE_TYPES:
            raise ValueError("نوع مرخصی نامعتبر است")

        # تبدیل تاریخ‌های شمسی به میلادی
        from_j = jdatetime.datetime.strptime(from_date_str.strip(), "%Y/%m/%d").date()
        to_j = jdatetime.datetime.strptime(to_date_str.strip(), "%Y/%m/%d").date()

        from_date = from_j.togregorian()
        to_date = to_j.togregorian()

        # اعتبارسنجی تاریخ‌ها
        if from_date > to_date:
            raise ValueError("تاریخ شروع باید قبل یا مساوی تاریخ پایان باشد")

        today_g = date.today()
        if from_date < today_g:
            raise ValueError("تاریخ شروع نمی‌تواند در گذشته باشد")

        # بررسی بازه مجاز (حداکثر ۳۰ روز)
        if (to_date - from_date).days > 30:
            raise ValueError("حداکثر بازه مرخصی ۳۰ روز است")

        # محاسبه تعداد روزها (با کسر تعطیلات)
        days_count = calculate_leave_days(db, user.user_id, from_date, to_date)

        if days_count <= 0:
            raise ValueError("در بازه انتخابی، هیچ روز کاری وجود ندارد (همه تعطیل هستند)")

        # بررسی مانده کافی
        year_j = from_j.year
        balance = db.query(LeaveBalance).filter(
            and_(
                LeaveBalance.user_id == user.user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == leave_type
            )
        ).first()

        current_balance = balance.balance if balance else 0

        if current_balance < days_count:
            type_name = LEAVE_TYPES.get(leave_type, '')
            raise ValueError(
                f"مانده کافی نیست! مانده {type_name}: {current_balance} روز، "
                f"درخواست: {days_count} روز"
            )

        # بررسی درخواست تکراری (همپوشانی تاریخ)
        overlapping = db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == user.user_id,
                LeaveRequest.status.in_(['P', 'A']),
                LeaveRequest.from_date <= to_date,
                LeaveRequest.to_date >= from_date
            )
        ).first()

        if overlapping:
            raise ValueError("در این بازه، درخواست مرخصی دیگری دارید")

        # ثبت درخواست
        new_request = LeaveRequest(
            user_id=user.user_id,
            leave_type=leave_type,
            from_date=from_date,
            to_date=to_date,
            days_count=days_count,
            reason=reason.strip() or None,
            status='P'
        )
        db.add(new_request)
        db.commit()

        type_name = LEAVE_TYPES.get(leave_type, '')
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success",
                f"درخواست مرخصی {type_name} ({days_count} روز) با موفقیت ثبت شد"
            ),
            status_code=302
        )
    except ValueError as e:
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/leave/request/{request_id}/cancel")
async def cancel_leave_request(
    request: Request,
    request_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """لغو درخواست مرخصی در انتظار"""
    leave_req = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.id == request_id,
            LeaveRequest.user_id == user.user_id
        )
    ).first()

    if not leave_req:
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "درخواست یافت نشد"),
            status_code=302
        )

    if leave_req.status != 'P':
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "فقط درخواست‌های در انتظار قابل لغو هستند"),
            status_code=302
        )

    try:
        leave_req.status = 'R'
        leave_req.rejection_reason = "لغو شده توسط کاربر"
        db.commit()

        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "درخواست با موفقیت لغو شد"),
            status_code=302
        )
    except Exception as e:
        referer = request.headers.get("referer", "/leave")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.get("/leave/calculate-days")
async def calculate_leave_days(
        from_date: str = Query(...),
        to_date: str = Query(...),
        user: User = Depends(check_password_change),
        db: Session = Depends(get_db)
):
    """محاسبه تعداد روزهای کاری بین دو تاریخ"""
    try:
        # تبدیل تاریخ‌های شمسی به میلادی
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        to_j = jdatetime.datetime.strptime(to_date.strip(), "%Y/%m/%d").date()

        from_g = from_j.togregorian()
        to_g = to_j.togregorian()

        if from_g > to_g:
            return {"success": False, "days_count": 0, "message": "تاریخ شروع باید قبل از پایان باشد"}

        # محاسبه روزهای کاری (کسر تعطیلات و جمعه‌ها)
        days_count = 0
        current = from_g
        while current <= to_g:
            # بررسی جمعه
            if current.weekday() == 4:  # جمعه
                current += timedelta(days=1)
                continue

            # بررسی تعطیلات رسمی
            holiday = db.query(Holiday).filter(Holiday.holiday_date == current).first()
            if holiday:
                current += timedelta(days=1)
                continue

            days_count += 1
            current += timedelta(days=1)

        return {"success": True, "days_count": days_count}
    except Exception as e:
        return {"success": False, "days_count": 0, "message": str(e)}