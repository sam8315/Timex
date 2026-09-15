"""
پنل مدیریت مانده و تراکنش‌های مرخصی
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from datetime import time
import jdatetime
from typing import Optional, List

from web.dependencies import get_db, require_admin, require_super_admin
from web.permissions import enforce_permission
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from datetime import datetime
from models.leave_request import LeaveRequest
from models.contract import Contract, CONTRACT_TYPES
from sqlalchemy import func
from datetime import datetime, timedelta
from models.employee_phone import EmployeePhone
from core.sms_service import SmsService
from web.services.notification_service import is_sms_enabled
from web.services.hourly_leave_service import (
    approve_hourly_leave,
    reverse_hourly_leave,
    compute_requested_minutes,
    validate_hourly_leave_request,
)
from models.travel_leave_detail import TravelLeaveDetail
from web.services.travel_leave_service import override_travel_days, resolve_effective_service_location, validate_destination_city, calculate_travel_days, check_quota, create_travel_leave_detail, get_active_cities
from models.city import City
from models.travel_leave_policy_rules import TravelLeavePolicyRule
from core.distance_engine import calculate_distance_km
import threading

router = APIRouter(tags=["Admin Leave"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

LEAVE_TYPES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
    'CW': 'ذخیره سال قبل',  # 🆕
    'HL': 'ساعتی',          # 🆕 Phase 7
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
def _has_negative_balance(row: dict) -> bool:
    """🆕 بررسی داشتن مانده منفی در یک ردیف"""
    return (
        (row.get('AL') is not None and row['AL'] < 0) or
        (row.get('SL') is not None and row['SL'] < 0) or
        (row.get('RL') is not None and row['RL'] < 0) or
        (row.get('CW') is not None and row['CW'] < 0)
    )


@router.get("/leave-balances", response_class=HTMLResponse)
async def leave_balances_page(
        request: Request,
        year: Optional[str] = Query(None),
        search: Optional[str] = Query(None),
        contract_type: Optional[str] = Query(None),
        leave_type: Optional[str] = Query(None),      # 🆕 فیلتر نوع مرخصی
        negative_only: Optional[str] = Query(None),   # 🆕 فقط مانده منفی
        show_all: Optional[str] = Query(None),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """لیست مانده مرخصی کاربران - همه سال‌ها"""
    enforce_permission(db, user, 'view_leave_balances')
    today_j = jdatetime.date.today()

    # تبدیل year به int اگر خالی نباشد
    year_int = None
    if year and year.strip():
        try:
            year_int = int(year.strip())
        except ValueError:
            year_int = None

    # اعتبارسنجی نوع مرخصی
    valid_leave_types = ('AL', 'SL', 'RL', 'CW')
    if leave_type and leave_type not in valid_leave_types:
        leave_type = None

    # اگر هر فیلتری باشد، اعمال می‌شود
    has_filter = any([
        search, show_all,
        year_int is not None,
        contract_type,
        leave_type,           # 🆕
        negative_only         # 🆕
    ])

    balances_data = []
    summary = {'total': 0, 'negative_count': 0, 'positive_count': 0}

    if has_filter:
        query = db.query(LeaveBalance)

        # فیلتر سال
        if year_int:
            query = query.filter(LeaveBalance.year == year_int)

        # 🆕 فیلتر نوع مرخصی (در سطح query برای بهینه‌سازی)
        if leave_type:
            query = query.filter(LeaveBalance.leave_type == leave_type)

        # فیلتر نوع قرارداد (بر اساس آخرین قرارداد هر کاربر)
        if contract_type:
            latest_contract_subq = (
                db.query(
                    Contract.user_id,
                    func.max(Contract.start_date).label('max_start')
                )
                .group_by(Contract.user_id)
                .subquery()
            )

            users_with_type = (
                db.query(Contract.user_id)
                .join(
                    latest_contract_subq,
                    and_(
                        Contract.user_id == latest_contract_subq.c.user_id,
                        Contract.start_date == latest_contract_subq.c.max_start
                    )
                )
                .filter(Contract.contract_type_code == contract_type)
                .all()
            )

            user_ids = list(set([u[0] for u in users_with_type]))

            if user_ids:
                query = query.filter(LeaveBalance.user_id.in_(user_ids))
            else:
                query = query.filter(LeaveBalance.user_id == "___NONE___")

        # جستجو
        if search and search.strip():
            term = search.strip()
            query = query.outerjoin(Employee, LeaveBalance.user_id == Employee.user_id).filter(
                or_(
                    LeaveBalance.user_id.ilike(f"%{term}%"),
                    Employee.first_name.ilike(f"%{term}%"),
                    Employee.last_name.ilike(f"%{term}%")
                )
            )

        balances = query.order_by(LeaveBalance.year.desc(), LeaveBalance.user_id).all()

        # گروه‌بندی بر اساس کاربر و سال
        grouped = {}
        for b in balances:
            key = (b.user_id, b.year)
            if key not in grouped:
                grouped[key] = {
                    'user_id': b.user_id,
                    'year': b.year,
                    'AL': None,
                    'SL': None,
                    'RL': None,
                    'CW': None,
                }
            if b.leave_type in valid_leave_types:
                grouped[key][b.leave_type] = b.balance

        # دریافت نوع قرارداد هر کاربر برای نمایش
        user_ids_in_result = list(set([row['user_id'] for row in grouped.values()]))
        contract_types_map = {}
        if user_ids_in_result:
            for uid in user_ids_in_result:
                last_contract = db.query(Contract).filter(
                    Contract.user_id == uid
                ).order_by(Contract.start_date.desc()).first()

                if last_contract:
                    contract_types_map[uid] = {
                        'code': last_contract.contract_type_code,
                        'name': last_contract.contract_type_name,
                    }
                else:
                    contract_types_map[uid] = {'code': None, 'name': 'بدون قرارداد'}

        for key, row in grouped.items():
            row['full_name'] = get_employee_name(db, row['user_id'])
            row['contract_type'] = contract_types_map.get(row['user_id'], {'code': None, 'name': '-'})
            balances_data.append(row)

        # 🆕 فیلتر فقط مانده منفی (بعد از گروه‌بندی)
        if negative_only:
            balances_data = [row for row in balances_data if _has_negative_balance(row)]

        # 🆕 محاسبه خلاصه آمار
        summary['total'] = len(balances_data)
        summary['negative_count'] = sum(
            1 for row in balances_data if _has_negative_balance(row)
        )
        summary['positive_count'] = summary['total'] - summary['negative_count']

    # لیست سال‌های موجود در دیتابیس + سال جاری
    existing_years = db.query(LeaveBalance.year).distinct().all()
    available_years = sorted(
        set([y[0] for y in existing_years] + [today_j.year]),
        reverse=True
    )

    return templates.TemplateResponse(request, "admin/leave_balances.html", {
        "user": user,
        "balances": balances_data,
        "total_count": len(balances_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "year": year_int,
        "search": search or "",
        "contract_type_filter": contract_type or "",   # 🆕 تغییر نام برای template
        "leave_type": leave_type or "",                 # 🆕
        "negative_only": negative_only,                 # 🆕
        "available_years": available_years,
        "contract_types": CONTRACT_TYPES,
        "leave_types": LEAVE_TYPES,
        "summary": summary,                             # 🆕
        "is_admin": True,
        "is_super_admin": user.is_super_admin,
    })

# ============================================
# صفحه تراکنش‌های مرخصی
# ============================================
@router.get("/leave-transactions", response_class=HTMLResponse)
async def leave_transactions_page(
    request: Request,
    year: Optional[str] = Query(None),  # 🆕 تغییر از int به str
    leave_type: Optional[str] = Query(None),
    tx_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست تراکنش‌های مرخصی - همه سال‌ها"""
    enforce_permission(db, user, 'view_leave_balances')
    today_j = jdatetime.date.today()

    # 🆕 تبدیل year به int اگر خالی نباشد
    year_int = None
    if year and year.strip():
        try:
            year_int = int(year.strip())
        except ValueError:
            year_int = None

    # اگر هر فیلتری باشد، اعمال می‌شود
    has_filter = any([search, leave_type, tx_type, show_all, year_int is not None])

    transactions_data = []

    if has_filter:
        query = db.query(LeaveTransaction)

        # فقط اگر year مشخص شد، فیلتر سال اعمال شود
        if year_int:
            query = query.filter(LeaveTransaction.year == year_int)

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

    # لیست سال‌های موجود در دیتابیس + سال جاری
    existing_years = db.query(LeaveTransaction.year).distinct().all()
    available_years = sorted(
        set([y[0] for y in existing_years] + [today_j.year]),
        reverse=True
    )

    return templates.TemplateResponse(request, "admin/leave_transactions.html", {
        "user": user,
        "transactions": transactions_data,
        "total_count": len(transactions_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "year": year_int,  # 🆕 int یا None
        "search": search or "",
        "leave_type": leave_type or "",
        "tx_type": tx_type or "",
        "available_years": available_years,
        "leave_types": LEAVE_TYPES,
        "transaction_types": TRANSACTION_TYPES,
        "is_admin": True,
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
    enforce_permission(db, user, 'view_leave_balances')
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

    enforce_permission(db, user, 'approve_leave')
    search_term = (search or "").strip()

    has_filter = any([status_filter, leave_type, search_term, show_all])

    requests_data = []
    total_days = 0

    if has_filter:
        query = db.query(LeaveRequest)

        # ✅ فقط اگر وضعیت انتخاب شده بود، فیلتر شود
        if status_filter:
            query = query.filter(LeaveRequest.status == status_filter)

        # فیلتر نوع مرخصی
        if leave_type:
            query = query.filter(LeaveRequest.leave_type == leave_type)

        # ✅ جستجو
        if search_term:
            query = query.outerjoin(
                Employee,
                LeaveRequest.user_id == Employee.user_id
            ).filter(
                or_(
                    LeaveRequest.user_id.ilike(f"%{search_term}%"),
                    Employee.first_name.ilike(f"%{search_term}%"),
                    Employee.last_name.ilike(f"%{search_term}%")
                )
            )

        # مرتب‌سازی بر اساس تاریخ شروع
        requests = query.order_by(LeaveRequest.from_date.desc()).limit(200).all()

        for r in requests:
            from_j = jdatetime.date.fromgregorian(date=r.from_date).strftime('%Y/%m/%d')
            to_j = jdatetime.date.fromgregorian(date=r.to_date).strftime('%Y/%m/%d')

            created_j = None
            if r.created_at:
                try:
                    created_j = jdatetime.datetime.fromgregorian(datetime=r.created_at).strftime('%Y/%m/%d %H:%M')
                except Exception:
                    created_j = str(r.created_at)

            # 🆕 محاسبه مانده مرخصی کاربر (فقط برای درخواست‌های در انتظار)
            current_balance = 0
            if r.status == 'P':
                req_year_j = jdatetime.date.fromgregorian(date=r.from_date).year
                balance = db.query(LeaveBalance).filter(
                    and_(
                        LeaveBalance.user_id == r.user_id,
                        LeaveBalance.year == req_year_j,
                        LeaveBalance.leave_type == r.leave_type
                    )
                ).first()
                current_balance = balance.balance if balance else 0

            # 🆕 محاسبه اطلاعات مرخصی ساعتی
            hl_start_time = r.start_time.strftime('%H:%M') if r.start_time else None
            hl_end_time = r.end_time.strftime('%H:%M') if r.end_time else None
            hl_duration_minutes = None
            hl_duration_display = None
            if r.start_time and r.end_time:
                hl_duration_minutes = compute_requested_minutes(r.start_time, r.end_time)
                h = hl_duration_minutes // 60
                m = hl_duration_minutes % 60
                hl_duration_display = f"{h}h {m}m" if h > 0 else f"{m}m"

            requests_data.append({
                'request': r,
                'full_name': get_employee_name(db, r.user_id),
                'from_j': from_j,
                'to_j': to_j,
                'created_j': created_j,
                'leave_type_name': LEAVE_TYPES.get(r.leave_type, r.leave_type),
                'current_balance': current_balance,
                'hl_start_time': hl_start_time,
                'hl_end_time': hl_end_time,
                'hl_duration_minutes': hl_duration_minutes,
                'hl_duration_display': hl_duration_display,
                'travel_detail': r.travel_leave_detail if hasattr(r, 'travel_leave_detail') else None,
            })
        total_days = sum(item['request'].days_count for item in requests_data)

    pending_count = db.query(LeaveRequest).filter(LeaveRequest.status == 'P').count()
    # دریافت لیست کارمندان فعال برای انتخاب
    employees = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.first_name, Employee.last_name).all()

    employees_list = [
        {
            'user_id': emp.user_id,
            'full_name': emp.full_name,
            'department': emp.department or '-',
        }
        for emp in employees
    ]

    # 🆕 جزئیات درخواست نیازمند تاییدیه مانده منفی (فقط مدیر ارشد)
    confirm_negative_request = None
    confirm_id = request.query_params.get("confirm_negative")
    if confirm_id and user.is_super_admin:
        try:
            target = db.query(LeaveRequest).filter(
                LeaveRequest.id == int(confirm_id),
                LeaveRequest.status == 'P'
            ).first()
        except (TypeError, ValueError):
            target = None
        if target:
            target_year_j = jdatetime.date.fromgregorian(
                date=target.from_date).year
            target_balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == target.user_id,
                    LeaveBalance.year == target_year_j,
                    LeaveBalance.leave_type == target.leave_type
                )
            ).first()
            target_current = target_balance.balance if target_balance else 0
            if target_current < target.days_count:
                confirm_negative_request = {
                    'id': target.id,
                    'full_name': get_employee_name(db, target.user_id),
                    'leave_type_name': LEAVE_TYPES.get(
                        target.leave_type, target.leave_type),
                    'from_j': jdatetime.date.fromgregorian(
                        date=target.from_date).strftime('%Y/%m/%d'),
                    'to_j': jdatetime.date.fromgregorian(
                        date=target.to_date).strftime('%Y/%m/%d'),
                    'days_count': target.days_count,
                    'current_balance': target_current,
                    'resulting_balance': target_current - target.days_count,
                }

    return templates.TemplateResponse(request, "admin/leave_requests.html", {
        "user": user,
        "requests": requests_data,
        "total_count": len(requests_data),
        "total_days": total_days,
        "has_filter": has_filter,
        "show_all": show_all,
        "status_filter": status_filter or "",
        "leave_type": leave_type or "",
        "search": search_term,
        "pending_count": pending_count,
        "leave_types": LEAVE_TYPES,
        "is_admin": True,
        "employees": employees_list,  # لیست کارمندان
        "confirm_negative_request": confirm_negative_request,  # 🆕 باکس تایید مانده منفی
    })

# ============================================
# تایید درخواست مرخصی
# ============================================
@router.post("/leave-requests/{request_id}/approve")
async def approve_leave_request(
        request: Request,
        request_id: int,
        allow_negative: str = Form("off"),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تایید درخواست مرخصی + کسر از مانده + ارسال پیامک"""
    enforce_permission(db, user, 'approve_leave')
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

    # Phase 7: HL requests use separate approval flow
    if leave_req.leave_type == 'HL':
        try:
            success, error_msg = approve_hourly_leave(db, leave_req, user.user_id)
            if not success:
                referer = request.headers.get("referer", "/admin/leave-requests")
                return RedirectResponse(
                    url=build_redirect_url(referer, "error", error_msg or "خطا در تایید مرخصی ساعتی"),
                    status_code=302
                )
            db.commit()

            # Compute summary for success message
            minutes = compute_requested_minutes(
                leave_req.start_time, leave_req.end_time
            ) if leave_req.start_time and leave_req.end_time else 0
            hours = minutes // 60
            mins = minutes % 60
            time_str = f"{hours}:{mins:02d}"

            referer = request.headers.get("referer", "/admin/leave-requests")
            return RedirectResponse(
                url=build_redirect_url(
                    referer, "success",
                    f"مرخصی ساعتی تایید شد ({time_str} ساعت)"
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

    # بررسی مانده کافی (for non-HL types)
    year_j = jdatetime.date.fromgregorian(date=leave_req.from_date).year
    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == leave_req.user_id,
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == leave_req.leave_type
    ).first()

    tl_detail = None
    deduct_days = leave_req.days_count

    if leave_req.leave_type == 'AL':
        tl_detail = db.query(TravelLeaveDetail).filter(
            TravelLeaveDetail.leave_request_id == leave_req.id
        ).first()

        if tl_detail:
            deduct_days = max(
                0,
                leave_req.days_count - tl_detail.final_travel_days
            )

    current_balance = balance.balance if balance else 0
    forced_negative = False
    if current_balance < deduct_days:
        # مدیر ارشد می‌تواند با مانده منفی تایید کند (با تاییدیه جداگانه)
        if user.is_super_admin and allow_negative in ("on", "true", "1"):
            forced_negative = True
        elif user.is_super_admin:
            referer = request.headers.get("referer", "/admin/leave-requests")
            url = build_redirect_url(
                referer, "error",
                f"مانده کافی نیست! مانده: {current_balance} روز، درخواست: {deduct_days} روز"
            )
            return RedirectResponse(
                url=f"{url}&confirm_negative={request_id}",
                status_code=302
            )
        else:
            referer = request.headers.get("referer", "/admin/leave-requests")
            return RedirectResponse(
                url=build_redirect_url(
                    referer, "error",
                    f"مانده کافی نیست! مانده: {current_balance} روز، درخواست: {deduct_days} روز"
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
            balance.balance -= deduct_days
        else:
            balance = LeaveBalance(
                user_id=leave_req.user_id,
                year=year_j,
                leave_type=leave_req.leave_type,
                balance=-deduct_days
            )
            db.add(balance)

        # ۳. ثبت تراکنش
        tx_description = f"استفاده از مرخصی {LEAVE_TYPES.get(leave_req.leave_type, '')} - درخواست #{request_id}"
        if forced_negative:
            tx_description += " | تایید با مانده منفی توسط مدیر ارشد"
        tx = LeaveTransaction(
            user_id=leave_req.user_id,
            year=year_j,
            leave_type=leave_req.leave_type,
            amount=deduct_days,
            transaction_type='USE',
            description=tx_description,
            reference_id=leave_req.id
        )
        db.add(tx)

        # ۴. Mark TravelLeaveDetail as approved if present
        if leave_req.leave_type == 'AL':
            tl_detail = db.query(TravelLeaveDetail).filter(
                TravelLeaveDetail.leave_request_id == leave_req.id
            ).first()
            if tl_detail:
                tl_detail.approved_at = datetime.now()

        db.commit()

        # 🆕 ۴. ارسال پیامک تایید (async - بدون کندی، فقط اگر فعال باشد)
        phones = _get_user_phones(db, leave_req.user_id)
        sms_sent = False
        if phones and is_sms_enabled(db):
            type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
            j_from = jdatetime.date.fromgregorian(date=leave_req.from_date)
            j_to = jdatetime.date.fromgregorian(date=leave_req.to_date)

            sms_message = (
                f"✅ مرخصی {type_name} شما تأیید شد.\n"
                f"از تاریخ {j_from.strftime('%Y/%m/%d')} "
                f"تا {j_to.strftime('%Y/%m/%d')}\n"
                f"به مدت {leave_req.days_count} روز\n"
                f"سامانه حضور و غیاب"
            )

            _send_sms_async(phones, sms_message, leave_req.user_id)
            sms_sent = True

        type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
        referer = request.headers.get("referer", "/admin/leave-requests")
        success_msg = (
            f"درخواست تایید شد | {deduct_days} روز مرخصی {type_name} کسر شد"
        )
        if forced_negative:
            resulting = current_balance - deduct_days
            success_msg += f" | ⚠️ مانده منفی شد: {resulting} روز"
        success_msg += (" | پیامک ارسال شد 📱" if sms_sent else "")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", success_msg),
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
    """رد درخواست مرخصی (بدون کسر از مانده) + ارسال پیامک"""
    enforce_permission(db, user, 'approve_leave')
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

        # 🆕 ارسال پیامک رد (async - فقط اگر فعال باشد)
        phones = _get_user_phones(db, leave_req.user_id)
        sms_sent = False
        if phones and is_sms_enabled(db):
            type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
            j_from = jdatetime.date.fromgregorian(date=leave_req.from_date)
            j_to = jdatetime.date.fromgregorian(date=leave_req.to_date)

            sms_message = (
                f"❌ درخواست مرخصی {type_name} شما رد شد.\n"
                f"از تاریخ {j_from.strftime('%Y/%m/%d')} "
                f"تا {j_to.strftime('%Y/%m/%d')}\n"
            )
            if leave_req.rejection_reason:
                sms_message += f"دلیل: {leave_req.rejection_reason}\n"
            sms_message += "سامانه حضور و غیاب"

            _send_sms_async(phones, sms_message, leave_req.user_id)
            sms_sent = True

        referer = request.headers.get("referer", "/admin/leave-requests")
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success",
                "درخواست رد شد" + (" | پیامک ارسال شد 📱" if sms_sent else "")
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
    enforce_permission(db, user, 'approve_leave')
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
        # Phase 7: HL requests use separate reversal flow
        if leave_req.leave_type == 'HL':
            reverse_hourly_leave(db, leave_req)
            db.commit()

            type_name = LEAVE_TYPES.get(leave_req.leave_type, '')
            referer = request.headers.get("referer", "/admin/leave-requests")
            return RedirectResponse(
                url=build_redirect_url(
                    referer, "success",
                    f"مرخصی {type_name} حذف شد و تراکنش‌های ساعتی بازگردانده شد"
                ),
                status_code=302
            )

        year_j = jdatetime.date.fromgregorian(date=leave_req.from_date).year

        # ۱. پیدا کردن مانده
        balance = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == leave_req.user_id,
            LeaveBalance.year == year_j,
            LeaveBalance.leave_type == leave_req.leave_type
        ).first()
        deduct_days = leave_req.days_count

        if leave_req.leave_type == 'AL':
            tl_detail = db.query(TravelLeaveDetail).filter(
                TravelLeaveDetail.leave_request_id == leave_req.id
            ).first()

            if tl_detail:
                deduct_days = max(
                    0,
                    leave_req.days_count - tl_detail.final_travel_days
                )

        # ۲. برگرداندن فقط مقدار واقعی کسرشده
        if balance:
            balance.balance += deduct_days
        else:
            balance = LeaveBalance(
                user_id=leave_req.user_id,
                year=year_j,
                leave_type=leave_req.leave_type,
                balance=deduct_days
            )
            db.add(balance)

        # ۳. ثبت تراکنش بازگشت
        tx = LeaveTransaction(
            user_id=leave_req.user_id,
            year=year_j,
            leave_type=leave_req.leave_type,
            amount=deduct_days,
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
                f"مرخصی حذف شد | {deduct_days} روز مرخصی {type_name} به مانده برگشت"
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
# صفحه وارد کردن مرخصی ذخیره سال قبل
# ============================================
@router.get("/import-previous-leave", response_class=HTMLResponse)
async def import_previous_leave_page(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """صفحه وارد کردن مرخصی ذخیره سال قبل"""
    enforce_permission(db, user, 'view_leave_balances')
    return templates.TemplateResponse(request, "admin/import_previous_leave.html", {
        "user": user,
        "is_admin": True,
    })


@router.post("/import-previous-leave")
async def import_previous_leave(
    request: Request,
    year: int = Form(...),
    leave_type: str = Form('AL'),
    data: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """پردازش وارد کردن مرخصی ذخیره"""
    enforce_permission(db, user, 'view_leave_balances')
    results = []
    lines = data.strip().split('\n')

    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue  # رد کردن خطوط خالی و کامنت‌ها

        try:
            # پشتیبانی از جداکننده‌های مختلف: , یا tab یا فاصله
            if ',' in line:
                parts = line.split(',')
            elif '\t' in line:
                parts = line.split('\t')
            else:
                parts = line.split()

            if len(parts) < 2:
                results.append({
                    'line': line_num,
                    'data': line,
                    'success': False,
                    'error': 'فرمت نامعتبر (باید: کد_پرسنلی, تعداد_روز)'
                })
                continue

            user_id = parts[0].strip()
            days = int(parts[1].strip())

            if days < 0:
                results.append({
                    'line': line_num,
                    'data': line,
                    'success': False,
                    'error': 'تعداد روز نمی‌تواند منفی باشد'
                })
                continue

            # بررسی وجود کاربر
            employee = db.query(Employee).filter(Employee.user_id == user_id).first()
            if not employee:
                results.append({
                    'line': line_num,
                    'data': line,
                    'success': False,
                    'error': f'کاربر {user_id} یافت نشد'
                })
                continue

            # بررسی وجود balance
            balance = db.query(LeaveBalance).filter(
                LeaveBalance.user_id == user_id,
                LeaveBalance.year == year,
                LeaveBalance.leave_type == leave_type
            ).first()

            if balance:
                old_value = balance.balance
                balance.balance += days
                action = f"افزوده شد ({old_value} → {balance.balance})"
            else:
                balance = LeaveBalance(
                    user_id=user_id,
                    year=year,
                    leave_type=leave_type,
                    balance=days
                )
                db.add(balance)
                action = f"ایجاد شد ({days} روز)"

            # ثبت تراکنش
            tx = LeaveTransaction(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=days,
                transaction_type='ADJUST',
                description=f"مرخصی ذخیره سال {year} - ورود دستی توسط {user.name}",
                reference_id=None
            )
            db.add(tx)

            results.append({
                'line': line_num,
                'data': line,
                'success': True,
                'user_id': user_id,
                'full_name': employee.full_name,
                'days': days,
                'action': action
            })

        except ValueError as e:
            results.append({
                'line': line_num,
                'data': line,
                'success': False,
                'error': f'خطا در تبدیل تعداد روز: {str(e)}'
            })
        except Exception as e:
            results.append({
                'line': line_num,
                'data': line,
                'success': False,
                'error': f'خطا: {str(e)}'
            })

    db.commit()

    # شمارش موفق/ناموفق
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count

    # ذخیره نتایج در session برای نمایش در صفحه
    request.session['import_results'] = results
    request.session['import_summary'] = {
        'total': len(results),
        'success': success_count,
        'fail': fail_count,
        'year': year,
    }

    return RedirectResponse(
        url=f"/admin/import-previous-leave?done=1&success={success_count}&fail={fail_count}",
        status_code=302
    )


@router.get("/import-previous-leave/results", response_class=HTMLResponse)
async def import_previous_leave_results(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمایش نتایج وارد کردن"""
    enforce_permission(db, user, 'view_leave_balances')
    results = request.session.get('import_results', [])
    summary = request.session.get('import_summary', {})

    return templates.TemplateResponse(request, "admin/import_previous_leave_results.html", {
        "user": user,
        "results": results,
        "summary": summary,
        "is_admin": True,
    })


# ============================================
# 🆕 ثبت مرخصی برای سایر کاربران (توسط مدیر ارشد)
# ============================================

def calculate_leave_days_admin(db, user_id, from_date, to_date) -> int:
    """محاسبه تعداد روزهای مرخصی با کسر تعطیلات و جمعه‌ها"""
    from models.employee import Employee
    from models.holiday import Holiday

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    user_group = employee.department if employee else None

    days = 0
    current = from_date

    while current <= to_date:
        # بررسی تعطیل بودن
        holiday = db.query(Holiday).filter(Holiday.holiday_date == current).first()
        is_holiday_for_user = False
        if holiday:
            if holiday.group_id is None or holiday.group_id == user_group:
                is_holiday_for_user = True

        # 🆕 بررسی جمعه (current میلادی است، جمعه = 4)
        is_friday = current.weekday() == 4

        if not is_holiday_for_user and not is_friday:
            days += 1

        current += timedelta(days=1)

    return days


@router.get("/leave-requests/register", response_class=HTMLResponse)
async def register_leave_form(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """فرم ثبت مرخصی برای سایر کاربران"""
    enforce_permission(db, user, 'approve_leave')
    from models.employee import Employee

    # دریافت لیست کارمندان فعال برای انتخاب
    employees = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.first_name, Employee.last_name).all()

    employees_list = [
        {
            'user_id': emp.user_id,
            'full_name': emp.full_name,
            'department': emp.department or '-',
        }
        for emp in employees
    ]

    # Resolve hourly leave policy granularity for hint text (default 15)
    hl_granularity = 15
    try:
        from web.services.hourly_leave_service import resolve_hourly_leave_policy
        # Use first active employee or user; approximate with user for hint
        hl_policy = resolve_hourly_leave_policy(db, user, __import__('datetime').date.today())
        if hl_policy and hl_policy.granularity_minutes:
            hl_granularity = hl_policy.granularity_minutes
    except Exception:
        pass

    cities = get_active_cities(db)

    return templates.TemplateResponse(request, "admin/leave_register.html", {
        "user": user,
        "employees": employees_list,
        "leave_types": LEAVE_TYPES,
        "is_admin": True,
        "hl_granularity": hl_granularity,
        "cities": cities,
    })


@router.post("/leave-requests/register")
async def register_leave_for_user(
        request: Request,
        target_user_id: str = Form(...),
        leave_type: str = Form(...),
        from_date_str: str = Form(...),
        to_date_str: str = Form(""),
        start_time_str: str = Form(""),
        end_time_str: str = Form(""),
        reason: str = Form(""),
        travel_leave_enabled: str = Form("off"),
        destination_city_id: str = Form(""),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """ثبت مرخصی برای یک کاربر (توسط مدیر) - در حالت در انتظار بررسی"""
    enforce_permission(db, user, 'approve_leave')
    from models.employee import Employee
    from models.leave_request import LeaveRequest

    try:
        # بررسی وجود کاربر هدف
        target_employee = db.query(Employee).filter(
            Employee.user_id == target_user_id
        ).first()
        if not target_employee:
            raise ValueError("کاربر مورد نظر یافت نشد")

        # اعتبارسنجی نوع مرخصی
        if leave_type not in LEAVE_TYPES:
            raise ValueError("نوع مرخصی نامعتبر است")

        # تبدیل تاریخ‌های شمسی به میلادی
        from_j = jdatetime.datetime.strptime(from_date_str.strip(), "%Y/%m/%d").date()
        from_date = from_j.togregorian()

        # 🆕 منطق مرخصی ساعتی
        if leave_type == 'HL':
            if not start_time_str or not end_time_str:
                raise ValueError("ساعت شروع و پایان برای مرخصی ساعتی الزامی است")
            from datetime import time as time_type
            try:
                st = start_time_str.strip().split(':')
                et = end_time_str.strip().split(':')
                start_time = time_type(int(st[0]), int(st[1]))
                end_time = time_type(int(et[0]), int(et[1]))
                if start_time >= end_time:
                    raise ValueError("ساعت شروع باید قبل از ساعت پایان باشد")
            except Exception as e:
                raise ValueError(f"فرمت ساعت نامعتبر: {str(e)}")

            to_date = from_date  # ✅ HL: same day, to_date = from_date
            days_count = 0  # ✅ HL: duration computed from minutes, not days

            # Validate via service policy
            employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
            if employee:
                valid, err = validate_hourly_leave_request(db, employee, from_date, start_time, end_time)
                if not valid:
                    raise ValueError(err or "اعتبارسنجی مرخصی ساعتی ناموفق")

            # Overlap check for HL (same date, existing approved/pending)
            overlapping = db.query(LeaveRequest).filter(
                and_(
                    LeaveRequest.user_id == target_user_id,
                    LeaveRequest.status.in_(['P', 'A']),
                    LeaveRequest.leave_type == 'HL',
                    LeaveRequest.from_date == from_date,
                    or_(
                        and_(LeaveRequest.start_time < end_time, LeaveRequest.end_time > start_time),
                        and_(LeaveRequest.start_time == start_time, LeaveRequest.end_time == end_time),
                    ),
                )
            ).first()
            if overlapping:
                raise ValueError("با مرخصی ساعتی موجود در این تاریخ تداخل زمانی دارد")

            new_request = LeaveRequest(
                user_id=target_user_id,
                leave_type=leave_type,
                from_date=from_date,
                to_date=to_date,
                days_count=days_count,
                start_time=start_time,
                end_time=end_time,
                reason=reason.strip() or f"ثبت شده توسط : {user.user_id}",
                status='P',
            )
            db.add(new_request)
            db.commit()
            duration_minutes = compute_requested_minutes(start_time, end_time)
            h = duration_minutes // 60
            m = duration_minutes % 60
            time_str = f"{h}:{m:02d}" if h > 0 else f"{m} دقیقه"
            return RedirectResponse(
                url=f"/admin/leave-requests/register?success=درخواست مرخصی ساعتی ({time_str}) برای {target_employee.full_name} در حالت در انتظار بررسی ثبت شد",
                status_code=302
            )
        else:
            # غیر HL: منطق قبلی
            to_j = jdatetime.datetime.strptime(to_date_str.strip(), "%Y/%m/%d").date()
            to_date = to_j.togregorian()
            if from_date > to_date:
                raise ValueError("تاریخ شروع باید قبل یا مساوی تاریخ پایان باشد")
            days_count = calculate_leave_days_admin(db, target_user_id, from_date, to_date)
            if days_count <= 0:
                raise ValueError("در بازه انتخابی، هیچ روز کاری وجود ندارد (همه تعطیل هستند)")
            overlaps = db.query(LeaveRequest).filter(
                and_(
                    LeaveRequest.user_id == target_user_id,
                    LeaveRequest.status.in_(['P', 'A']),
                    LeaveRequest.from_date <= to_date,
                    LeaveRequest.to_date >= from_date,
                )
            ).first()
            if overlaps:
                raise ValueError("کاربر در این بازه، درخواست مرخصی دیگری دارد")

            # مرخصی توراهی فقط با مرخصی استحقاقی (AL)
            tl_enabled = travel_leave_enabled == "on" and leave_type == "AL"
            tl_dest_city_id = None
            if tl_enabled:
                if not destination_city_id or not destination_city_id.strip():
                    raise ValueError("شهر مقصد برای مرخصی توراهی الزامی است")
                try:
                    tl_dest_city_id = int(destination_city_id.strip())
                except (ValueError, TypeError):
                    raise ValueError("شهر مقصد نامعتبر است")

            new_request = LeaveRequest(
                user_id=target_user_id,
                leave_type=leave_type,
                from_date=from_date,
                to_date=to_date,
                days_count=days_count,
                reason=reason.strip() or f"ثبت شده توسط : {user.user_id}",
                status='P',
            )
            db.add(new_request)
            db.flush()

            # ثبت جزئیات مرخصی توراهی به‌صورت اتمیک
            if tl_enabled:
                try:
                    create_travel_leave_detail(db, new_request, tl_dest_city_id)
                except ValueError as te:
                    db.rollback()
                    return RedirectResponse(
                        url=build_redirect_url(
                            request.headers.get("referer", "/admin/leave-requests/register"),
                            "error", str(te),
                        ),
                        status_code=302,
                    )
            db.commit()
            type_name = LEAVE_TYPES.get(leave_type, '')
            target_name = target_employee.full_name
            tl_msg = " + مرخصی توراهی" if tl_enabled else ""
            return RedirectResponse(
                url=f"/admin/leave-requests/register?success=درخواست مرخصی {type_name} ({days_count} روز){tl_msg} برای {target_name} در حالت در انتظار بررسی ثبت شد",
                status_code=302
            )
    except ValueError as e:
        return RedirectResponse(
            url=f"/admin/leave-requests/register?error={str(e)}",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/leave-requests/register?error=خطا: {str(e)}",
            status_code=302
        )


@router.get("/leave-requests/travel-preview")
async def admin_travel_leave_preview(
    target_user_id: str = Query(...),
    from_date: str = Query(...),
    destination_city_id: int = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """پیش‌نمایش مشاوره‌ای مرخصی توراهی برای ثبت توسط مدیر (محاسبه مجدد سمت سرور)."""
    enforce_permission(db, user, 'approve_leave')
    try:
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        from_g = from_j.togregorian()

        esl = resolve_effective_service_location(db, target_user_id, from_g)
        if not esl:
            return {"success": False, "message": "محل خدمت مؤثر در تاریخ شروع یافت نشد"}

        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        if not origin_city:
            return {"success": False, "message": "شهر محل خدمت یافت نشد"}

        dest_city = validate_destination_city(db, destination_city_id)
        if not dest_city:
            return {"success": False, "message": "شهر مقصد نامعتبر است"}

        distance_km = round(calculate_distance_km(
            (origin_city.latitude, origin_city.longitude),
            (dest_city.latitude, dest_city.longitude),
        ), 2)

        rules = db.query(TravelLeavePolicyRule).filter(
            TravelLeavePolicyRule.is_active == 1
        ).all()
        travel_days, _ = calculate_travel_days(distance_km, rules)

        jalali_year = jdatetime.date.fromgregorian(date=from_g).year
        allowed, used, max_allowed = check_quota(db, target_user_id, jalali_year)

        return {
            "success": True,
            "origin_city": origin_city.name,
            "destination_city": dest_city.name,
            "destination_province": dest_city.province or "",
            "distance_km": distance_km,
            "travel_days": travel_days,
            "eligible": travel_days > 0,
            "message": (
                f"فاصله {distance_km} کیلومتر — {travel_days} روز توراهی"
                if travel_days > 0 else
                (f"فاصله {distance_km} کیلومتر است. مرخصی توراهی برای این مسیر قابل استفاده نیست (کمتر از ۲۰۰ کیلومتر)."
                 if distance_km < 200 else
                 f"فاصله {distance_km} کیلومتر — مرخصی توراهی برای این مسیر قابل استفاده نیست (خارج از محدوده مجاز).")
            ),
            "quota_used": used,
            "quota_max": max_allowed,
            "quota_allowed": allowed,
            "jalali_year": jalali_year,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}


# ============================================
# 🆕 ویرایش درخواست مرخصی (توسط ادمین) - همه وضعیت‌ها
# ============================================

@router.get("/leave-requests/{request_id}/edit", response_class=HTMLResponse)
async def edit_leave_request_form(
        request: Request,
        request_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """فرم ویرایش درخواست مرخصی (همه وضعیت‌ها)"""
    enforce_permission(db, user, 'approve_leave')
    leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()

    if not leave_request:
        return RedirectResponse(url="/admin/leave-requests?error=درخواست یافت نشد", status_code=302)

    # ⚠️ هیچ محدودیت status وجود ندارد - همه قابل ویرایش هستند

    # تبدیل تاریخ‌ها به شمسی
    from_j = jdatetime.date.fromgregorian(date=leave_request.from_date).strftime('%Y/%m/%d')
    to_j = jdatetime.date.fromgregorian(date=leave_request.to_date).strftime('%Y/%m/%d')

    # دریافت لیست کارمندان فعال
    employees = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.first_name, Employee.last_name).all()

    employees_list = [
        {
            'user_id': emp.user_id,
            'full_name': emp.full_name,
            'department': emp.department or '-',
        }
        for emp in employees
    ]

    # دریافت اطلاعات کاربر فعلی
    current_employee = db.query(Employee).filter(
        Employee.user_id == leave_request.user_id
    ).first()

    # Travel Leave context
    travel_detail = leave_request.travel_leave_detail
    cities = get_active_cities(db)

    service_origin_city = None

    if travel_detail:
        service_origin_city = travel_detail.origin_city_name_snapshot
    else:
        esl = resolve_effective_service_location(
            db,
            leave_request.user_id,
            leave_request.from_date
        )
        if esl:
            origin_city = db.query(City).filter(
                City.id == esl.city_id
            ).first()
            if origin_city:
                service_origin_city = origin_city.name

    return templates.TemplateResponse(request, "admin/leave_request_edit.html", {
        "user": user,
        "leave_request": leave_request,
        "from_j": from_j,
        "to_j": to_j,
        "employees": employees_list,
        "current_employee_name": current_employee.full_name if current_employee else leave_request.user_id,
        "leave_types": LEAVE_TYPES,
        "statuses": {
            'P': 'در انتظار بررسی',
            'A': 'تایید شده',
            'R': 'رد شده',
        },
        "is_admin": True,
        "is_hl": leave_request.leave_type == 'HL',
        "travel_detail": travel_detail,
        "cities": cities,
        "service_origin_city": service_origin_city,
        "is_travel_leave": travel_detail is not None,
        "hl_start_time": leave_request.start_time.strftime('%H:%M') if leave_request.start_time else '',
        "hl_end_time": leave_request.end_time.strftime('%H:%M') if leave_request.end_time else '',
    })


@router.post("/leave-requests/{request_id}/edit")
async def edit_leave_request_submit(
        request: Request,
        request_id: int,
        target_user_id: str = Form(...),
        leave_type: str = Form(...),
        from_date_str: str = Form(...),
        to_date_str: str = Form(...),
        reason: str = Form(""),
        status: str = Form('P'),
        start_time_str: str = Form(""),
        end_time_str: str = Form(""),
        travel_leave_enabled: str = Form("off"),
        destination_city_id: str = Form(""),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """ثبت تغییرات درخواست مرخصی (همه وضعیت‌ها)"""
    enforce_permission(db, user, 'approve_leave')
    try:
        leave_request = db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()

        if not leave_request:
            raise ValueError("درخواست یافت نشد")

        # ⚠️ هیچ محدودیت status وجود ندارد

        # اعتبارسنجی وضعیت
        if status not in ('P', 'A', 'R'):
            raise ValueError("وضعیت نامعتبر است")

        # ذخیره وضعیت قبلی برای محاسبات بالانس
        old_status = leave_request.status
        old_leave_type = leave_request.leave_type
        old_days_count = leave_request.days_count
        old_user_id = leave_request.user_id
        old_year_j = jdatetime.date.fromgregorian(date=leave_request.from_date).year

        # بررسی وجود کاربر هدف
        target_employee = db.query(Employee).filter(
            Employee.user_id == target_user_id
        ).first()
        if not target_employee:
            raise ValueError("کاربر مورد نظر یافت نشد")

        # اعتبارسنجی نوع مرخصی
        if leave_type not in LEAVE_TYPES:
            raise ValueError("نوع مرخصی نامعتبر است")

        # تبدیل تاریخ‌های شمسی به میلادی
        from_j = jdatetime.datetime.strptime(from_date_str.strip(), "%Y/%m/%d").date()
        to_j = jdatetime.datetime.strptime(to_date_str.strip(), "%Y/%m/%d").date()
        from_date = from_j.togregorian()
        to_date = to_j.togregorian()

        # اعتبارسنجی بازه تاریخ
        if from_date > to_date:
            raise ValueError("تاریخ شروع باید قبل یا مساوی تاریخ پایان باشد")

        # محاسبه تعداد روزها
        days_count = calculate_leave_days_admin(db, target_user_id, from_date, to_date)

        if days_count <= 0:
            raise ValueError("در بازه انتخابی، هیچ روز کاری وجود ندارد (همه تعطیل هستند)")
        # Travel Leave
        tl_enabled = travel_leave_enabled == "on" and leave_type == "AL"
        tl_dest_city_id = None

        if tl_enabled:
            if not destination_city_id or not destination_city_id.strip():
                raise ValueError("شهر مقصد برای مرخصی توراهی الزامی است")

            try:
                tl_dest_city_id = int(destination_city_id.strip())
            except (ValueError, TypeError):
                raise ValueError("شهر مقصد نامعتبر است")

        # بررسی همپوشانی (به جز درخواست فعلی)
        overlapping = db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.user_id == target_user_id,
                LeaveRequest.id != request_id,
                LeaveRequest.status.in_(['P', 'A']),
                LeaveRequest.from_date <= to_date,
                LeaveRequest.to_date >= from_date
            )
        ).first()

        if overlapping:
            raise ValueError("کاربر در این بازه، درخواست مرخصی دیگری دارد")
        old_travel_detail = db.query(TravelLeaveDetail).filter(
            TravelLeaveDetail.leave_request_id == request_id
        ).first()
        old_final_travel_days = old_travel_detail.final_travel_days if old_travel_detail else 0

        # مرحله ۱: اگر درخواست قبلاً تایید شده، کسر قبلی را برمی‌گردانیم
        if old_status == 'A':
            # مقدار واقعی کسر شده از سالانه = کل روزها منهای روز توراهی
            old_deduct_days = max(0, old_days_count - old_final_travel_days)

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == old_user_id,
                    LeaveBalance.year == old_year_j,
                    LeaveBalance.leave_type == old_leave_type
                )
            ).first()
            if balance:
                balance.balance += old_deduct_days
            else:
                balance = LeaveBalance(
                    user_id=old_user_id,
                    year=old_year_j,
                    leave_type=old_leave_type,
                    balance=old_deduct_days
                )
                db.add(balance)

            # حذف تراکنش USE قبلی مرتبط با این درخواست
            old_tx = db.query(LeaveTransaction).filter(
                and_(
                    LeaveTransaction.reference_id == request_id,
                    LeaveTransaction.transaction_type == 'USE'
                )
            ).first()
            if old_tx:
                db.delete(old_tx)

        # مرحله ۲: به‌روزرسانی فیلدها
        leave_request.user_id = target_user_id
        leave_request.leave_type = leave_type
        leave_request.from_date = from_date
        leave_request.to_date = to_date
        leave_request.days_count = days_count
        leave_request.reason = reason.strip()
        leave_request.status = status

        # Travel Leave detail — rebuild/replace when AL and enabled; preserve override if appropriate
        if leave_type == 'AL' and tl_enabled:
            if old_travel_detail:
                # Preserve manual override metadata
                old_override = old_travel_detail.manual_override
                old_final_days = old_travel_detail.final_travel_days
                old_override_reason = old_travel_detail.override_reason
                old_overridden_by = old_travel_detail.overridden_by
                old_overridden_at = old_travel_detail.overridden_at

                # Delete old detail, recreate with server-side snapshots
                db.delete(old_travel_detail)
                db.flush()

                new_detail = create_travel_leave_detail(db, leave_request, tl_dest_city_id)

                # If there was a manual override, preserve the final value and metadata
                if old_override:
                    new_detail.manual_override = True
                    new_detail.final_travel_days = old_final_days
                    new_detail.override_reason = old_override_reason
                    new_detail.overridden_by = old_overridden_by
                    new_detail.overridden_at = old_overridden_at
                    db.flush()
            else:
                create_travel_leave_detail(db, leave_request, tl_dest_city_id)

        elif old_travel_detail:
            # Travel Leave disabled or leave type changed away from AL
            db.delete(old_travel_detail)
            db.flush()

        # 🆕 به‌روزرسانی فیلدهای مرخصی ساعتی
        if leave_type == 'HL' and start_time_str and end_time_str:
            try:
                from datetime import time as time_type
                st_parts = start_time_str.strip().split(':')
                et_parts = end_time_str.strip().split(':')
                start_time = time_type(int(st_parts[0]), int(st_parts[1]))
                end_time = time_type(int(et_parts[0]), int(et_parts[1]))
                if start_time >= end_time:
                    raise ValueError("ساعت شروع باید قبل از ساعت پایان باشد")
                leave_request.start_time = start_time
                leave_request.end_time = end_time
            except ValueError as e:
                raise ValueError(f"زمان نامعتبر: {str(e)}")
        elif leave_type != 'HL':
            # پاک کردن فیلدهای زمانی برای انواع غیر HL
            leave_request.start_time = None
            leave_request.end_time = None

        # مرحله ۳: اگر وضعیت جدید "تایید شده" است، کسر جدید اعمال شود
        if status == 'A':
            new_year_j = from_j.year
            # محاسبه روز توراهی از جزئیات تازه ساخته شده (در صورت وجود)
            new_tl = db.query(TravelLeaveDetail).filter(
                TravelLeaveDetail.leave_request_id == request_id
            ).first()
            new_final_travel_days = new_tl.final_travel_days if new_tl else 0
            new_deduct_days = max(0, days_count - new_final_travel_days)

            balance = db.query(LeaveBalance).filter(
                and_(
                    LeaveBalance.user_id == target_user_id,
                    LeaveBalance.year == new_year_j,
                    LeaveBalance.leave_type == leave_type
                )
            ).first()
            if balance:
                balance.balance -= new_deduct_days
            else:
                new_balance = LeaveBalance(
                    user_id=target_user_id,
                    year=new_year_j,
                    leave_type=leave_type,
                    balance=-new_deduct_days
                )
                db.add(new_balance)

            # ثبت تراکنش USE جدید با مقدار واقعی کسر شده
            new_tx = LeaveTransaction(
                user_id=target_user_id,
                year=new_year_j,
                leave_type=leave_type,
                amount=new_deduct_days,
                transaction_type='USE',
                description=f"مرخصی ویرایش شده (درخواست #{request_id})",
                reference_id=request_id
            )
            db.add(new_tx)

            # تنظیم approved_by و approved_at اگر قبلاً تایید نشده بوده
            if old_status != 'A':
                leave_request.approved_by = user.user_id
                leave_request.approved_at = datetime.now()
        else:
            # اگر وضعیت جدید "تایید شده" نیست، اطلاعات تایید پاک شود
            leave_request.approved_by = None
            leave_request.approved_at = None

        db.commit()

        type_name = LEAVE_TYPES.get(leave_type, '')
        target_name = target_employee.full_name

        return RedirectResponse(
            url=f"/admin/leave-requests?success=درخواست مرخصی {type_name} برای {target_name} با موفقیت ویرایش شد",
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/admin/leave-requests/{request_id}/edit?error={str(e)}",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/leave-requests/{request_id}/edit?error=خطا: {str(e)}",
            status_code=302
        )


# ============================================
# 🆕 Travel Leave — Admin Override
# ============================================
@router.post("/leave-requests/{request_id}/travel-leave-override")
async def travel_leave_override(
    request: Request,
    request_id: int,
    detail_id: int = Form(...),
    final_travel_days: int = Form(...),
    override_reason: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Override final travel days for a pending Travel Leave request."""
    enforce_permission(db, user, 'approve_leave')

    referer = request.headers.get("referer", "/admin/leave-requests")
    try:
        override_travel_days(
            db=db,
            detail_id=detail_id,
            new_final_days=final_travel_days,
            admin_user_id=user.user_id,
            reason=override_reason,
        )
        db.commit()
        return RedirectResponse(
            url=build_redirect_url(
                referer, "success",
                f"روزهای توراهی درخواست #{request_id} به {final_travel_days} روز تغییر کرد"
            ),
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


# ============================================
# 🆕 ارسال پیامک ایمن (بدون تأثیر بر فرآیند اصلی)
# ============================================

def _get_user_phones(db: Session, user_id: str) -> List[str]:
    """دریافت شماره‌های موبایل کاربر (اول پیش‌فرض، سپس بقیه)"""
    phones = db.query(EmployeePhone).filter(
        EmployeePhone.user_id == user_id
    ).order_by(EmployeePhone.is_default.desc()).all()

    if not phones:
        return []

    # اول شماره پیش‌فرض، سپس بقیه (بدون تکرار)
    result = []
    default_phone = next((p for p in phones if p.is_default), None)
    if default_phone:
        result.append(default_phone.phone_number)

    for p in phones:
        if p.phone_number not in result:
            result.append(p.phone_number)

    return result


def _send_sms_async(phones: List[str], message: str, user_id: str):
    """ارسال پیامک در thread جداگانه (بدون کند کردن redirect)"""

    def send_task():
        try:
            sms = SmsService()
            result = sms.send_sms(phones, message)
            if result.get('success'):
                print(f"✅ پیامک مرخصی به {user_id} ارسال شد: {phones}")
            else:
                print(f"⚠️ پیامک به {user_id} ارسال نشد: {result.get('message')}")
        except Exception as e:
            print(f"❌ خطای ارسال پیامک به {user_id}: {e}")

    # اجرای async در thread جداگانه
    thread = threading.Thread(target=send_task, daemon=True)
    thread.start()