"""
پنل مدیریت عضویت / قراردادها
"""
from datetime import date
from fastapi import APIRouter, Request, Depends, Form, Query, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
import jdatetime
import time
from typing import Optional

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from models.user import User
from models.employee import Employee
from models.contract import Contract, CONTRACT_TYPES
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import MEMBERSHIP_PERMANENT
from web.services.leave_service import (
    charge_leave_for_new_contract,
    update_leave_for_contract,
    remove_leave_for_contract,
    get_stored_leave_balance,
    set_stored_leave_for_year,
)
from web.services.leave_entitlement_service import (
    get_membership_timeline,
    resolve_annual_leave_days,
    find_overlapping_contract,
    add_years,
    sync_employee_department_from_active_contract,
    sync_employee_region_from_service_location,
)

router = APIRouter(tags=["Admin Contracts"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads" / "contracts"
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _static_to_disk(static_path: str) -> Path:
    rel = static_path.replace("/static/", "").replace("\\", "/").lstrip("/")
    return Path(__file__).parent.parent / "static" / rel


def _delete_contract_file(static_path: Optional[str]) -> None:
    if not static_path:
        return
    try:
        path = _static_to_disk(static_path)
        if path.is_file():
            path.unlink()
    except OSError:
        pass


async def _save_contract_file(
    upload: UploadFile,
    *,
    user_id: str,
    contract_id: int,
) -> str:
    """ذخیره فایل قرارداد و برگرداندن مسیر استاتیک."""
    if not upload.filename:
        raise ValueError("نام فایل نامعتبر است")
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("نوع فایل مجاز نیست (فقط PDF/JPG/PNG)")
    content = await upload.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("حجم فایل بیش از ۱۰ مگابایت است")
    if not content:
        raise ValueError("فایل خالی است")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_uid = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
    filename = f"{safe_uid}_{contract_id}_{int(time.time())}{ext}"
    disk_path = UPLOAD_DIR / filename
    with open(disk_path, "wb") as f:
        f.write(content)
    return f"/static/uploads/contracts/{filename}"


def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def format_charge_message(charged: dict, prefix: str) -> str:
    """ساخت پیام مرخصی شارژ شده به تفکیک سال"""
    if not charged:
        return ""
    year_parts = []
    for year_j, leaves in charged.items():
        al = leaves.get('AL', 0)
        sl = leaves.get('SL', 0)
        cw = leaves.get('CW', 0)
        parts = []
        if al:
            parts.append(f"استحقاقی {al}")
        if sl:
            parts.append(f"استعلاجی {sl}")
        if cw:
            parts.append(f"ذخیره {cw}")
        if parts:
            year_parts.append(f"سال {year_j}: {' و '.join(parts)} روز")
    if not year_parts:
        return ""
    return f" | {prefix} → " + " | ".join(year_parts)


def get_charged_by_year(db: Session, contract_id: int) -> dict:
    """محاسبه مرخصی شارژ شده بر اساس سال از تراکنش‌ها"""
    charged_by_year = {}
    charge_transactions = db.query(LeaveTransaction).filter(
        LeaveTransaction.reference_id == contract_id,
        LeaveTransaction.transaction_type.in_(['CHARGE', 'DEDUCT']),
    ).all()

    for tx in charge_transactions:
        if tx.year not in charged_by_year:
            charged_by_year[tx.year] = {'AL': 0, 'SL': 0, 'CW': 0}
        if tx.leave_type in ('AL', 'SL', 'CW'):
            sign = 1 if tx.transaction_type == 'CHARGE' else -1
            charged_by_year[tx.year][tx.leave_type] += sign * tx.amount

    return charged_by_year


def _ensure_permanent_end(contract_type_code: str, start_date: date, end_date: Optional[date]) -> Optional[date]:
    """رسمی بدون پایان → شروع + ۳۰ سال."""
    if contract_type_code == MEMBERSHIP_PERMANENT and end_date is None:
        return add_years(start_date, 30)
    return end_date


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
    """لیست عضویت‌ها / قراردادها"""
    enforce_permission(db, user, 'view_contracts')
    has_filter = any([search, type_filter, status_filter, show_all])
    contracts_data = []

    if has_filter:
        query = db.query(Contract)

        if search and search.strip():
            search_term = search.strip()
            query = query.outerjoin(Employee, Contract.user_id == Employee.user_id).filter(
                or_(
                    Contract.user_id.ilike(f"%{search_term}%"),
                    Employee.first_name.ilike(f"%{search_term}%"),
                    Employee.last_name.ilike(f"%{search_term}%")
                )
            )

        if type_filter:
            query = query.filter(Contract.contract_type_code == type_filter)

        contracts = query.order_by(Contract.start_date.desc()).all()

        for c in contracts:
            employee = db.query(Employee).filter(Employee.user_id == c.user_id).first()
            start_j = jdatetime.date.fromgregorian(date=c.start_date)
            end_j = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None
            start_year = start_j.year
            stored_cw = get_stored_leave_balance(db, c.user_id, start_year)

            contracts_data.append({
                'contract': c,
                'employee': employee,
                'full_name': employee.full_name if employee else f"کاربر {c.user_id}",
                'start_j': start_j.strftime('%Y/%m/%d'),
                'end_j': end_j.strftime('%Y/%m/%d') if end_j else 'دائمی',
                'is_active': c.is_active,
                'charged_by_year': get_charged_by_year(db, c.id),
                'stored_leave_days': stored_cw,
                'start_year': start_year,
            })

        if status_filter == 'active':
            contracts_data = [c for c in contracts_data if c['is_active']]
        elif status_filter == 'inactive':
            contracts_data = [c for c in contracts_data if not c['is_active']]

    membership_timeline = []
    timeline_user_id = None
    timeline_name = None
    if search and search.strip() and contracts_data:
        user_ids = {c['contract'].user_id for c in contracts_data}
        if len(user_ids) == 1:
            timeline_user_id = next(iter(user_ids))
            membership_timeline = get_membership_timeline(db, timeline_user_id)
            emp = db.query(Employee).filter(Employee.user_id == timeline_user_id).first()
            timeline_name = emp.full_name if emp else timeline_user_id

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
        "membership_timeline": membership_timeline,
        "timeline_user_id": timeline_user_id,
        "timeline_name": timeline_name,
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
    stored_leave_days: int = Form(0),
    description: str = Form(""),
    contract_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ثبت عضویت جدید + شارژ مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    try:
        if contract_type_code not in CONTRACT_TYPES:
            raise ValueError("نوع عضویت نامعتبر است")
        if stored_leave_days < 0:
            raise ValueError("مرخصی ذخیره نمی‌تواند منفی باشد")

        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()

        end_date = None
        if end_date_str.strip():
            end_j = jdatetime.datetime.strptime(end_date_str.strip(), "%Y/%m/%d").date()
            end_date = end_j.togregorian()

        end_date = _ensure_permanent_end(contract_type_code, start_date, end_date)

        if end_date and start_date >= end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            referer = request.headers.get("referer", "/admin/contracts")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "کاربر یافت نشد"),
                status_code=302
            )

        overlapping = find_overlapping_contract(db, user_id, start_date, end_date)
        if overlapping:
            raise ValueError(
                f"تداخل بازه با عضویت موجود (شروع: "
                f"{jdatetime.date.fromgregorian(date=overlapping.start_date).strftime('%Y/%m/%d')})"
            )

        type_config = CONTRACT_TYPES.get(contract_type_code, {})
        if not type_config.get('allow_service_deduction', False):
            service_deduction_days = 0

        # منطقه خدمتی از شهر محل خدمت؛ قبل از محاسبه استحقاق همگام شود
        region_code = sync_employee_region_from_service_location(
            db, user_id, commit=False, approved_by=user.user_id,
        )

        if not type_config.get('editable_leave', False):
            annual_leave_days = resolve_annual_leave_days(
                db,
                contract_type_code,
                region_code=region_code,
            )
            sick_leave_days = type_config.get('sick_leave', 0)

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
        db.flush()

        if contract_file and contract_file.filename:
            new_contract.file_path = await _save_contract_file(
                contract_file, user_id=user_id, contract_id=new_contract.id,
            )

        db.commit()
        db.refresh(new_contract)

        charged = charge_leave_for_new_contract(db, new_contract)

        start_year = jdatetime.date.fromgregorian(date=start_date).year
        if stored_leave_days > 0:
            cw_result = set_stored_leave_for_year(
                db,
                user_id=user_id,
                year=start_year,
                target_days=stored_leave_days,
                reference_id=new_contract.id,
                description=f"ورود مرخصی ذخیره هنگام ثبت عضویت #{new_contract.id}",
                commit=True,
            )
            charged.setdefault(start_year, {})['CW'] = cw_result['new']

        sync_employee_department_from_active_contract(db, user_id, commit=True)
        charge_msg = format_charge_message(charged, "مرخصی شارژ شد")

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"عضویت ثبت شد{charge_msg}"),
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
    stored_leave_days: int = Form(0),
    description: str = Form(""),
    remove_contract_file: str = Form(""),
    contract_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش عضویت + بروزرسانی مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "عضویت یافت نشد"),
            status_code=302
        )

    try:
        if stored_leave_days < 0:
            raise ValueError("مرخصی ذخیره نمی‌تواند منفی باشد")

        old_annual = contract.annual_leave_days
        old_sick = contract.sick_leave_days
        old_start = contract.start_date
        old_end = contract.end_date
        old_deduction = contract.service_deduction_days
        old_type_code = contract.contract_type_code

        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()

        end_date = None
        if end_date_str.strip():
            end_j = jdatetime.datetime.strptime(end_date_str.strip(), "%Y/%m/%d").date()
            end_date = end_j.togregorian()

        end_date = _ensure_permanent_end(contract_type_code, start_date, end_date)

        if end_date and start_date >= end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")

        overlapping = find_overlapping_contract(
            db, contract.user_id, start_date, end_date, exclude_id=contract.id
        )
        if overlapping:
            raise ValueError(
                f"تداخل بازه با عضویت موجود (شروع: "
                f"{jdatetime.date.fromgregorian(date=overlapping.start_date).strftime('%Y/%m/%d')})"
            )

        type_config = CONTRACT_TYPES.get(contract_type_code, {})
        if not type_config.get('allow_service_deduction', False):
            service_deduction_days = 0

        employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
        region_code = None
        if employee:
            region_code = sync_employee_region_from_service_location(
                db, contract.user_id, commit=False, approved_by=user.user_id,
            )

        if not type_config.get('editable_leave', False):
            annual_leave_days = resolve_annual_leave_days(
                db,
                contract_type_code,
                region_code=region_code,
            )
            sick_leave_days = type_config.get('sick_leave', 0)

        contract.contract_type_code = contract_type_code
        contract.start_date = start_date
        contract.end_date = end_date
        contract.annual_leave_days = annual_leave_days
        contract.sick_leave_days = sick_leave_days
        contract.service_deduction_days = service_deduction_days
        contract.description = description.strip() or None

        if contract_file and contract_file.filename:
            old_path = contract.file_path
            contract.file_path = await _save_contract_file(
                contract_file, user_id=contract.user_id, contract_id=contract.id,
            )
            if old_path and old_path != contract.file_path:
                _delete_contract_file(old_path)
        elif remove_contract_file == "on" and contract.file_path:
            _delete_contract_file(contract.file_path)
            contract.file_path = None

        db.commit()

        changes = update_leave_for_contract(
            db=db,
            contract=contract,
            old_annual_leave=old_annual,
            old_sick_leave=old_sick,
            old_start_date=old_start,
            old_end_date=old_end,
            old_deduction=old_deduction,
            old_type_code=old_type_code,
        )

        start_year = jdatetime.date.fromgregorian(date=start_date).year
        cw_result = set_stored_leave_for_year(
            db,
            user_id=contract.user_id,
            year=start_year,
            target_days=stored_leave_days,
            reference_id=contract.id,
            description=f"تنظیم مرخصی ذخیره هنگام ویرایش عضویت #{contract.id}",
            commit=True,
        )
        if cw_result['diff'] != 0:
            changes.setdefault(start_year, {})['CW'] = cw_result['diff']

        sync_employee_department_from_active_contract(db, contract.user_id, commit=True)
        change_msg = format_charge_message(changes, "تغییرات مرخصی")

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"عضویت ویرایش شد{change_msg}"),
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
    """حذف عضویت + حذف مرخصی"""
    enforce_permission(db, user, 'view_contracts')
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "عضویت یافت نشد"),
            status_code=302
        )

    try:
        user_id = contract.user_id
        file_path = contract.file_path
        removed = remove_leave_for_contract(db, contract)
        remove_msg = format_charge_message(removed, "مرخصی کسر شد")

        db.delete(contract)
        db.commit()
        _delete_contract_file(file_path)
        sync_employee_department_from_active_contract(db, user_id, commit=True)

        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"عضویت حذف شد{remove_msg}"),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/contracts")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.get("/contracts/{contract_id}/file")
async def view_contract_file(
    contract_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """مشاهده / دانلود فایل قرارداد پیوست‌شده."""
    enforce_permission(db, user, 'view_contracts')
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract or not contract.file_path:
        return RedirectResponse(
            url="/admin/contracts?error=فایل قرارداد یافت نشد",
            status_code=302,
        )
    disk = _static_to_disk(contract.file_path)
    if not disk.is_file():
        return RedirectResponse(
            url="/admin/contracts?error=فایل قرارداد روی دیسک موجود نیست",
            status_code=302,
        )
    return FileResponse(
        path=str(disk),
        filename=disk.name,
        media_type=None,
        content_disposition_type="inline",
    )
