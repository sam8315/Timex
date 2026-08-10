"""
پنل مدیریت مانده و تراکنش‌های مرخصی
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin, require_super_admin
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from datetime import datetime
from models.leave_request import LeaveRequest

router = APIRouter(tags=["Admin Leave"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

LEAVE_TYPES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
}

TRANSACTION_TYPES = {
    'CHARGE': '➕ شارژ',
    'DEDUCT': '➖ کسر',
    'REVERSE': '↩️ برگشت',
    'USE': '📅 استفاده',
    'ADJUST': '🔧 تنظیم دستی',
}

LEAVE_REQUEST_STATUS = {
    'P': '⏳ در انتظار',
    'A': '✅ تایید شده',
    'R': '❌ رد شده',
    'D': '🗑️ حذف شده',
}

def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def get_employee_name(db, user_id: str) -> str:
    emp = db.query(Employee).filter(Employee.user_id == user_id).first()
    return emp.full_name if emp else f"کاربر {user_id}"


# ============================================
# صفحه مانده مرخصی
# ============================================
@router.get("/leave-balances", response_class=HTMLResponse)
async def leave_balances_page(
    request: Request,
    year: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست مانده مرخصی کاربران"""
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year

    has_filter = any([search, show_all]) or year != today_j.year or year is not None
    # برای لود اولیه خالی: فقط وقتی فیلتر داریم که search یا show_all باشد
    has_filter = any([search, show_all])

    balances_data = []

    if has_filter:
        query = db.query(LeaveBalance).filter(LeaveBalance.year == year)

        if search and search.strip():
            term = search.strip()
            query = query.outerjoin(Employee, LeaveBalance.user_id == Employee.user_id).filter(
                or_(
                    LeaveBalance.user_id.ilike(f"%{term}%"),
                    Employee.first_name.ilike(f"%{term}%"),
                    Employee.last_name.ilike(f"%{term}%")
                )
            )

        balances = query.order_by(LeaveBalance.user_id).all()

        # گروه‌بندی بر اساس کاربر (نمایش AL و SL در یک ردیف)
        grouped = {}
        for b in balances:
            if b.user_id not in grouped:
                grouped[b.user_id] = {
                    'user_id': b.user_id,
                    'year': b.year,
                    'AL': None,
                    'SL': None,
                }
            if b.leave_type in ('AL', 'SL'):
                grouped[b.user_id][b.leave_type] = b.balance

        for uid, row in grouped.items():
            row['full_name'] = get_employee_name(db, uid)
            balances_data.append(row)

    return templates.TemplateResponse(request, "admin/leave_balances.html", {
        "user": user,
        "balances": balances_data,
        "total_count": len(balances_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "year": year,
        "search": search or "",
        "available_years": list(range(today_j.year - 2, today_j.year + 3)),
        "leave_types": LEAVE_TYPES,
        "is_admin": True,
        "is_super_admin": user.is_super_admin,
    })


# ============================================
# تنظیم دستی مانده (فقط مدیر ارشد)
# ============================================
@router.post("/leave-balances/adjust")
async def adjust_balance(
    request: Request,
    user_id: str = Form(...),
    year: int = Form(...),
    leave_type: str = Form(...),
    amount: int = Form(...),
    description: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """تنظیم دستی مانده مرخصی + ثبت تراکنش"""
    if amount == 0:
        referer = request.headers.get("referer", "/admin/leave-balances")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "مقدار تغییر نمی‌تواند صفر باشد"),
            status_code=302
        )

    # بررسی وجود balance
    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == year,
        LeaveBalance.leave_type == leave_type
    ).first()

    old_value = balance.balance if balance else 0

    if not balance:
        balance = LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=0
        )
        db.add(balance)

    # اعمال تغییر (جلوگیری از منفی شدن)
    new_value = max(0, old_value + amount)
    balance.balance = new_value
    actual_change = new_value - old_value

    # ثبت تراکنش
    tx = LeaveTransaction(
        user_id=user_id,
        year=year,
        leave_type=leave_type,
        amount=abs(actual_change),
        transaction_type='ADJUST',
        description=description.strip() or f"تنظیم دستی توسط {user.name}",
        reference_id=None
    )
    db.add(tx)
    db.commit()

    type_name = LEAVE_TYPES.get(leave_type, leave_type)
    referer = request.headers.get("referer", "/admin/leave-balances")
    return RedirectResponse(
        url=build_redirect_url(
            referer, "success",
            f"مانده {type_name} کاربر {user_id} به {new_value} روز تغییر کرد"
        ),
        status_code=302
    )


# ============================================
# صفحه تراکنش‌های مرخصی
# ============================================
@router.get("/leave-transactions", response_class=HTMLResponse)
async def leave_transactions_page(
    request: Request,
    year: Optional[int] = Query(None),
    leave_type: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست تراکنش‌های مرخصی"""
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year

    has_filter = any([search, leave_type, tx_type, show_all])

    transactions_data = []

    if has_filter:
        query = db.query(LeaveTransaction).filter(LeaveTransaction.year == year)

        if leave_type:
            query = query.filter(LeaveTransaction.leave_type == leave_type)

        if tx_type:
            query = query.filter(LeaveTransaction.transaction_type == tx_type)

        if search and search.strip():
            term = search.strip()
            query = query.outerjoin(Employee, LeaveTransaction.user_id == Employee.user_id).filter(
                or_(
                    LeaveTransaction.user_id.ilike(f"%{term}%"),
                    Employee.first_name.ilike(f"%{term}%"),
                    Employee.last_name.ilike(f"%{term}%")
                )
            )

        transactions = query.order_by(LeaveTransaction.created_at.desc()).limit(500).all()

        for t in transactions:
            created_j = None
            if t.created_at:
                try:
                    created_j = jdatetime.datetime.fromgregorian(datetime=t.created_at).strftime('%Y/%m/%d %H:%M')
                except Exception:
                    created_j = t.created_at.strftime('%Y/%m/%d %H:%M')

            transactions_data.append({
                'id': t.id,
                'user_id': t.user_id,
                'full_name': get_employee_name(db, t.user_id),
                'year': t.year,
                'leave_type': t.leave_type,
                'leave_type_name': LEAVE_TYPES.get(t.leave_type, t.leave_type),
                'amount': t.amount,
                'transaction_type': t.transaction_type,
                'transaction_type_name': TRANSACTION_TYPES.get(t.transaction_type, t.transaction_type),
                'description': t.description,
                'created_j': created_j,
            })

    return templates.TemplateResponse(request, "admin/leave_transactions.html", {
        "user": user,
        "transactions": transactions_data,
        "total_count": len(transactions_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "year": year,
        "search": search or "",
        "leave_type": leave_type or "",
        "tx_type": tx_type or "",
        "available_years": list(range(today_j.year - 2, today_j.year + 3)),
        "leave_types": LEAVE_TYPES,
        "transaction_types": TRANSACTION_TYPES,
        "is_admin": True,
    })


from datetime import datetime
from models.leave_request import LeaveRequest


# ============================================
# صفحه مدیریت درخواست‌های مرخصی
# ============================================
@router.get("/leave-requests", response_class=HTMLResponse)
async def leave_requests_page(
        request: Request,
        status_filter: Optional[str] = Query(None),
        leave_type: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        show_all: Optional[str] = Query(None),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """لیست درخواست‌های مرخصی"""
    has_filter = any([status_filter, leave_type, search, show_all])
    requests_data = []

    if has_filter:
        query = db.query(LeaveRequest)

        # فیلتر وضعیت (پیش‌فرض: در انتظار)
        if status_filter:
            query = query.filter(LeaveRequest.status == status_filter)
        elif not show_all:
            # اگر فیلتری نیست و show_all هم نیست، فقط در انتظارها را نشان بده
            query = query.filter(LeaveRequest.status == 'P')

        # فیلتر نوع مرخصی
        if leave_type:
            query = query.filter(LeaveRequest.leave_type == leave_type)

        # جستجو
        if search and search.strip():
            term = search.strip()
            query = query.outerjoin(Employee, LeaveRequest.user_id == Employee.user_id).filter(
                or_(
                    LeaveRequest.user_id.ilike(f"%{term}%"),
                    Employee.first_name.ilike(f"%{term}%"),
                    Employee.last_name.ilike(f"%{term}%")
                )
            )

        requests = query.order_by(LeaveRequest.created_at.desc()).limit(200).all()

        for r in requests:
            # تبدیل تاریخ‌ها به شمسی
            from_j = jdatetime.date.fromgregorian(date=r.from_date).strftime('%Y/%m/%d')
            to_j = jdatetime.date.fromgregorian(date=r.to_date).strftime('%Y/%m/%d')

            created_j = None
            if r.created_at:
                try:
                    created_j = jdatetime.datetime.fromgregorian(datetime=r.created_at).strftime('%Y/%m/%d %H:%M')
                except Exception:
                    created_j = str(r.created_at)

            # بررسی مانده کاربر برای این نوع مرخصی
            year_j = jdatetime.date.fromgregorian(date=r.from_date).year
            balance = db.query(LeaveBalance).filter(
                LeaveBalance.user_id == r.user_id,
                LeaveBalance.year == year_j,
                LeaveBalance.leave_type == r.leave_type
            ).first()
            current_balance = balance.balance if balance else 0

            requests_data.append({
                'request': r,
                'full_name': get_employee_name(db, r.user_id),
                'from_j': from_j,
                'to_j': to_j,
                'created_j': created_j,
                'leave_type_name': LEAVE_TYPES.get(r.leave_type, r.leave_type),
                'current_balance': current_balance,
                'has_enough_balance': current_balance >= r.days_count,
            })

    # آمار درخواست‌های در انتظار
    pending_count = db.query(LeaveRequest).filter(LeaveRequest.status == 'P').count()

    return templates.TemplateResponse(request, "admin/leave_requests.html", {
        "user": user,
        "requests": requests_data,
        "total_count": len(requests_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "status_filter": status_filter or "",
        "leave_type": leave_type or "",
        "search": search or "",
        "pending_count": pending_count,
        "leave_types": LEAVE_TYPES,
        "is_admin": True,
    })


# ============================================
# تایید درخواست مرخصی
# ============================================
@router.post("/leave-requests/{request_id}/approve")
async def approve_leave_request(
        request: Request,
        request_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تایید درخواست مرخصی + کسر از مانده"""
    leave_req = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_req:
        return RedirectResponse(url="/admin/leave-requests?error=درخواست یافت نشد", status_code=302)

    # بررسی وضعیت
    if leave_req.status != 'P':
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "این درخواست قبلاً بررسی شده است"),
            status_code=302
        )

    # بررسی مانده کافی
    year_j = jdatetime.date.fromgregorian(date=leave_req.from_date).year
    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == leave_req.user_id,
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == leave_req.leave_type
    ).first()

    current_balance = balance.balance if balance else 0
    if current_balance < leave_req.days_count:
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(
                referer, "error",
                f"مانده کافی نیست! مانده: {current_balance} روز، درخواست: {leave_req.days_count} روز"
            ),
            status_code=302
        )

    try:
        # ۱. تایید درخواست
        leave_req.status = 'A'
        leave_req.approved_by = user.user_id
        leave_req.approved_at = datetime.now()

        # ۲. کسر از مانده
        if balance:
            balance.balance -= leave_req.days_count
        else:
            balance = LeaveBalance(
                user_id=leave_req.user_id,
                year=year_j,
                leave_type=leave_req.leave_type,
                balance=-leave_req.days_count
            )
            db.add(balance)

        # ۳. ثبت تراکنش
        tx = LeaveTransaction(
            user_id=leave_req.user_id,
            year=year_j,
            leave_type=leave_req.leave_type,
            amount=leave_req.days_count,
            transaction_type='USE',
            description=f"استفاده از مرخصی {LEAVE_TYPES.get(leave_req.leave_type, '')} - درخواست #{request_id}",
            reference_id=leave_req.id
        )
        db.add(tx)
        db.commit()

        type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success",
                f"درخواست تایید شد | {leave_req.days_count} روز مرخصی {type_name} کسر شد"
            ),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


# ============================================
# رد درخواست مرخصی
# ============================================
@router.post("/leave-requests/{request_id}/reject")
async def reject_leave_request(
        request: Request,
        request_id: int,
        rejection_reason: str = Form(""),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """رد درخواست مرخصی (بدون کسر از مانده)"""
    leave_req = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_req:
        return RedirectResponse(url="/admin/leave-requests?error=درخواست یافت نشد", status_code=302)

    # بررسی وضعیت
    if leave_req.status != 'P':
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "این درخواست قبلاً بررسی شده است"),
            status_code=302
        )

    try:
        leave_req.status = 'R'
        leave_req.approved_by = user.user_id
        leave_req.approved_at = datetime.now()
        leave_req.rejection_reason = rejection_reason.strip() or None
        db.commit()

        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "درخواست رد شد"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


# ============================================
# حذف مرخصی تایید شده (بازگشت مرخصی)
# ============================================
@router.post("/leave-requests/{request_id}/delete")
async def delete_leave_request(
    request: Request,
    request_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف مرخصی تایید شده + برگرداندن روزها به مانده"""
    leave_req = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
    if not leave_req:
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "درخواست یافت نشد"),
            status_code=302
        )

    # فقط درخواست‌های تایید شده قابل حذف هستند
    if leave_req.status != 'A':
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "فقط مرخصی‌های تایید شده قابل حذف هستند"),
            status_code=302
        )

    try:
        year_j = jdatetime.date.fromgregorian(date=leave_req.from_date).year

        # ۱. پیدا کردن مانده
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == leave_req.user_id,
            LeaveBalance.year == year_j,
            LeaveBalance.leave_type == leave_req.leave_type
        ).first()

        # ۲. برگرداندن روزها به مانده
        if balance:
            balance.balance += leave_req.days_count
        else:
            balance = LeaveBalance(
                user_id=leave_req.user_id,
                year=year_j,
                leave_type=leave_req.leave_type,
                balance=leave_req.days_count
            )
            db.add(balance)

        # ۳. ثبت تراکنش بازگشت
        tx = LeaveTransaction(
            user_id=leave_req.user_id,
            year=year_j,
            leave_type=leave_req.leave_type,
            amount=leave_req.days_count,
            transaction_type='REVERSE',
            description=f"حذف مرخصی تایید شده - درخواست #{request_id}",
            reference_id=leave_req.id
        )
        db.add(tx)

        # ۴. تغییر وضعیت به حذف شده
        leave_req.status = 'D'
        db.commit()

        type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success",
                f"مرخصی حذف شد | {leave_req.days_count} روز مرخصی {type_name} به مانده برگشت"
            ),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )