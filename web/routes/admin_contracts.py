"""
پنل مدیریت قراردادها
"""
from datetime import date
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from models.user import User
from models.employee import Employee
from models.contract import Contract, CONTRACT_TYPES
from models.leave_transaction import LeaveTransaction
from web.services.leave_service import (
    charge_leave_for_new_contract,
    update_leave_for_contract,
    remove_leave_for_contract
)

router = APIRouter(tags=["Admin Contracts"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def format_charge_message(charged: dict, prefix: str) -> str:
    """🆕 ساخت پیام مرخصی شارژ شده به تفکیک سال"""
    if not charged:
        return ""
    year_parts = []
    for year_j, leaves in charged.items():
        al = leaves.get('AL', 0)
        sl = leaves.get('SL', 0)
        parts = []
        if al > 0:
            parts.append(f"استحقاقی {al}")
        if sl > 0:
            parts.append(f"استعلاجی {sl}")
        if parts:
            year_parts.append(f"سال {year_j}: {' و '.join(parts)} روز")
    if not year_parts:
        return ""
    return f" | {prefix} → " + " | ".join(year_parts)


def get_charged_by_year(db: Session, contract_id: int) -> dict:
    """🆕 محاسبه مرخصی شارژ شده بر اساس سال از تراکنش‌ها"""
    charged_by_year = {}
    charge_transactions = db.query(LeaveTransaction).filter(
        LeaveTransaction.reference_id == contract_id,
        LeaveTransaction.transaction_type == 'CHARGE'
    ).all()

    for tx in charge_transactions:
        if tx.year not in charged_by_year:
            charged_by_year[tx.year] = {'AL': 0, 'SL': 0}
        if tx.leave_type in ('AL', 'SL'):
            charged_by_year[tx.year][tx.leave_type] += tx.amount

    return charged_by_year


@router.get("/contracts", response_class=HTMLResponse)
async def contracts_page(
    request: Request,
    search: Optional[str] = Query(None),
    type_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست قراردادها"""
    enforce_permission(db, user, 'view_contracts')
    has_filter = any([search, type_filter, status_filter, show_all])
    contracts_data = []

    if has_filter:
        query = db.query(Contract)

        # جستجو بر اساس کد پرسنلی یا نام
        if search and search.strip():
            search_term = search.strip()
            query = query.outerjoin(Employee, Contract.user_id == Employee.user_id).filter(
                or_(
                    Contract.user_id.ilike(f"%{search_term}%"),
                    Employee.first_name.ilike(f"%{search_term}%"),
                    Employee.last_name.ilike(f"%{search_term}%")
                )
            )

        # فیلتر نوع قرارداد
        if type_filter:
            query = query.filter(Contract.contract_type_code == type_filter)

        contracts = query.order_by(Contract.start_date.desc()).all()

        for c in contracts:
            employee = db.query(Employee).filter(Employee.user_id == c.user_id).first()

            start_j = jdatetime.date.fromgregorian(date=c.start_date)
            end_j = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None

            # 🆕 محاسبه مرخصی شارژ شده بر اساس سال
            charged_by_year = get_charged_by_year(db, c.id)

            contracts_data.append({
                'contract': c,
                'employee': employee,
                'full_name': employee.full_name if employee else f"کاربر {c.user_id}",
                'start_j': start_j.strftime('%Y/%m/%d'),
                'end_j': end_j.strftime('%Y/%m/%d') if end_j else 'دائمی',
                'is_active': c.is_active,
                'charged_by_year': charged_by_year,
            })

        # فیلتر وضعیت (بعد از محاسبه is_active)
        if status_filter == 'active':
            contracts_data = [c for c in contracts_data if c['is_active']]
        elif status_filter == 'inactive':
            contracts_data = [c for c in contracts_data if not c['is_active']]

    return templates.TemplateResponse(request, "admin/contracts.html", {
        "user": user,
        "contracts": contracts_data,
        "total_count": len(contracts_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search or "",
        "type_filter": type_filter or "",
        "status_filter": status_filter or "",
        "contract_types": CONTRACT_TYPES,
        "is_admin": True,
    })


@router.post("/contracts/add")
async def add_contract(
    request: Request,
    user_id: str = Form(...),
    contract_type_code: str = Form(...),
    start_date_str: str = Form(...),
    end_date_str: str = Form(""),
    annual_leave_days: int = Form(0),
    sick_leave_days: int = Form(0),
    service_deduction_days: int = Form(0),
    description: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ثبت قرارداد جدید + شارژ مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    try:
        # اعتبارسنجی نوع قرارداد
        if contract_type_code not in CONTRACT_TYPES:
            raise ValueError("نوع قرارداد نامعتبر است")

        # تبدیل تاریخ‌های شمسی
        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()

        end_date = None
        if end_date_str.strip():
            end_j = jdatetime.datetime.strptime(end_date_str.strip(), "%Y/%m/%d").date()
            end_date = end_j.togregorian()

        # 🆕 اعتبارسنجی: شروع باید قبل از پایان باشد
        if end_date and start_date >= end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")

        # بررسی وجود کاربر
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            referer = request.headers.get("referer", "/admin/contracts")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "کاربر یافت نشد"),
                status_code=302
            )

        # بررسی کسر خدمت فقط برای وظیفه
        type_config = CONTRACT_TYPES.get(contract_type_code, {})
        if not type_config.get('allow_service_deduction', False):
            service_deduction_days = 0

        # 🆕 مقادیر مرخصی بر اساس نوع قرارداد
        if not type_config.get('editable_leave', False):
            # انواع ثابت: مقادیر از CONTRACT_TYPES
            annual_leave_days = type_config.get('annual_leave', 0)
            sick_leave_days = type_config.get('sick_leave', 0)

        # ایجاد قرارداد
        new_contract = Contract(
            user_id=user_id,
            contract_type_code=contract_type_code,
            start_date=start_date,
            end_date=end_date,
            annual_leave_days=annual_leave_days,
            sick_leave_days=sick_leave_days,
            service_deduction_days=service_deduction_days,
            description=description.strip() or None
        )
        db.add(new_contract)
        db.commit()
        db.refresh(new_contract)

        # 🆕 شارژ مرخصی به نسبت مدت قرارداد (چند ساله)
        charged = charge_leave_for_new_contract(db, new_contract)
        charge_msg = format_charge_message(charged, "مرخصی شارژ شد")

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"قرارداد ثبت شد{charge_msg}"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/contracts/{contract_id}/edit")
async def edit_contract(
    request: Request,
    contract_id: int,
    contract_type_code: str = Form(...),
    start_date_str: str = Form(...),
    end_date_str: str = Form(""),
    annual_leave_days: int = Form(0),
    sick_leave_days: int = Form(0),
    service_deduction_days: int = Form(0),
    description: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش قرارداد + بروزرسانی مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "قرارداد یافت نشد"),
            status_code=302
        )

    try:
        # ذخیره مقادیر قدیمی برای محاسبه مابه‌التفاوت
        old_annual = contract.annual_leave_days
        old_sick = contract.sick_leave_days
        old_start = contract.start_date
        old_end = contract.end_date
        old_deduction = contract.service_deduction_days

        # تبدیل تاریخ‌ها
        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()

        end_date = None
        if end_date_str.strip():
            end_j = jdatetime.datetime.strptime(end_date_str.strip(), "%Y/%m/%d").date()
            end_date = end_j.togregorian()

        # اعتبارسنجی تاریخ
        if end_date and start_date >= end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")

        # بررسی کسر خدمت
        type_config = CONTRACT_TYPES.get(contract_type_code, {})
        if not type_config.get('allow_service_deduction', False):
            service_deduction_days = 0

        # مقادیر مرخصی
        if not type_config.get('editable_leave', False):
            annual_leave_days = type_config.get('annual_leave', 0)
            sick_leave_days = type_config.get('sick_leave', 0)

        # بروزرسانی قرارداد
        contract.contract_type_code = contract_type_code
        contract.start_date = start_date
        contract.end_date = end_date
        contract.annual_leave_days = annual_leave_days
        contract.sick_leave_days = sick_leave_days
        contract.service_deduction_days = service_deduction_days
        contract.description = description.strip() or None
        db.commit()

        # 🆕 بروزرسانی مرخصی (اضافه یا کسر) - چند ساله
        changes = update_leave_for_contract(
            db=db,
            contract=contract,
            old_annual_leave=old_annual,
            old_sick_leave=old_sick,
            old_start_date=old_start,
            old_end_date=old_end,
            old_deduction=old_deduction
        )
        change_msg = format_charge_message(changes, "تغییرات مرخصی")

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"قرارداد ویرایش شد{change_msg}"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/contracts/{contract_id}/delete")
async def delete_contract(
    request: Request,
    contract_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف قرارداد + حذف مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "قرارداد یافت نشد"),
            status_code=302
        )

    try:
        # 🆕 حذف مرخصی شارژ شده (چند ساله)
        removed = remove_leave_for_contract(db, contract)
        remove_msg = format_charge_message(removed, "مرخصی کسر شد")

        # حذف قرارداد
        db.delete(contract)
        db.commit()

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"قرارداد حذف شد{remove_msg}"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )