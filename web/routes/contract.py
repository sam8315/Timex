"""صفحه قراردادها"""
from datetime import date
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.contract import Contract

router = APIRouter(tags=["Contract"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/contract", response_class=HTMLResponse)
async def contract_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    """صفحه قراردادهای کاربر"""
    today_g = date.today()
    today_j = jdatetime.date.today()

    # دریافت همه قراردادهای کاربر
    contracts_raw = db.query(Contract).filter(
        Contract.user_id == user.user_id
    ).order_by(Contract.start_date.desc()).all()

    contracts = []
    active_contract = None
    stats = {
        'total_contracts': 0,
        'active_contracts': 0,
        'expired_contracts': 0,
        'pending_contracts': 0,
    }

    for c in contracts_raw:
        stats['total_contracts'] += 1

        # تبدیل تاریخ‌ها به شمسی
        j_start = jdatetime.date.fromgregorian(date=c.start_date)
        j_end = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None
        j_actual_end = jdatetime.date.fromgregorian(date=c.actual_end_date) if c.actual_end_date else None

        # محاسبه مدت قرارداد
        duration_days = c.contract_duration_days
        duration_text = f"{duration_days} روز" if duration_days else 'باز'

        # 🆕 محاسبات پیشرفت
        days_elapsed = (today_g - c.start_date).days if c.is_active or today_g > c.start_date else 0
        days_elapsed = max(0, days_elapsed)

        # روزهای باقیمانده و درصد پیشرفت
        if c.actual_end_date:
            days_remaining = max(0, (c.actual_end_date - today_g).days)
            total_days = (c.actual_end_date - c.start_date).days
            progress_percent = round((days_elapsed / total_days * 100), 1) if total_days > 0 else 0
        else:
            # قرارداد باز
            days_remaining = None
            total_days = None
            progress_percent = None

        contract_data = {
            'id': c.id,
            'contract_type_code': c.contract_type_code,
            'contract_type_name': c.contract_type_name,

            # تاریخ‌ها
            'start_date_j': j_start.strftime('%Y/%m/%d'),
            'end_date_j': j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود',
            'actual_end_date_j': j_actual_end.strftime('%Y/%m/%d') if j_actual_end else 'نامحدود',

            # مرخصی‌ها
            'annual_leave_days': c.annual_leave_days,
            'sick_leave_days': c.sick_leave_days,
            'prorated_annual_leave': c.prorated_annual_leave,
            'prorated_sick_leave': c.prorated_sick_leave,

            # کسر خدمت
            'service_deduction_days': c.service_deduction_days,
            'allow_service_deduction': c.allow_service_deduction,

            # وضعیت
            'is_active': c.is_active,
            'status_name': c.status_name,

            # مدت
            'duration_days': duration_days,
            'duration_text': duration_text,

            # 🆕 پیشرفت
            'days_elapsed': days_elapsed,
            'days_remaining': days_remaining,
            'total_days': total_days,
            'progress_percent': progress_percent,

            # متا
            'description': c.description or '-',
            'has_file': c.file_path is not None,
            'file_path': c.file_path,
        }

        contracts.append(contract_data)

        # شناسایی قرارداد فعال
        if c.is_active and active_contract is None:
            active_contract = contract_data

        # آمار
        if c.is_active:
            stats['active_contracts'] += 1
        elif c.status_name == '⏰ منقضی':
            stats['expired_contracts'] += 1
        else:
            stats['pending_contracts'] += 1

    return templates.TemplateResponse(request, "contract.html", {
        "user": user,
        "today_j": today_j,
        "contracts": contracts,
        "active_contract": active_contract,
        "stats": stats,
        "is_admin": user.is_admin,
    })