"""
پنل مدیریت عضویت / قراردادها
"""
from datetime import date, timedelta
from fastapi import APIRouter, Request, Depends, Form, Query, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
import jdatetime
import json
from typing import Optional

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission, has_permission
from models.user import User
from models.employee import Employee
from models.contract import Contract
from models.leave_transaction import LeaveTransaction
from web.services import membership_semantics as msem
from web.services.membership_service import (
    get_effective_rule,
    membership_types_as_dict,
)
from web.services.leave_service import (
    charge_leave_for_new_contract,
    update_leave_for_contract,
    remove_leave_for_contract,
    get_stored_leave_balance,
    set_stored_leave_for_year,
    get_buyback_quota,
    set_buyback_quota_for_year,
)
from web.services.leave_entitlement_service import (
    get_membership_timeline,
    resolve_annual_leave_days,
    find_overlapping_contract,
    add_years,
    sync_employee_department_from_active_contract,
    sync_employee_region_from_service_location,
)
from web.services.permanent_leave_history_service import (
    apply_permanent_history,
    clear_permanent_history,
    get_used_by_year_from_contract,
    parse_used_by_year_from_form,
    preview_history_summary,
)
from web.services.contract_file_storage import (
    delete_contract_file as _delete_contract_file,
    resolve_contract_file_disk,
    save_contract_file as _save_contract_file,
)
from web.services.service_duty_region_service import (
    list_duty_regions,
    region_as_dict,
)
from web.services.service_end_date_engine import (
    ServiceEndDateError,
    apply_end_date_to_contract,
    preview_end_date,
)
from web.services.service_adjustment_service import list_adjustments_for_contract

router = APIRouter(tags=["Admin Contracts"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _parse_jalali_optional(date_str: str) -> Optional[date]:
    raw = (date_str or "").strip()
    if not raw:
        return None
    return jdatetime.datetime.strptime(raw, "%Y/%m/%d").date().togregorian()


def _parse_is_native(raw: str) -> Optional[bool]:
    value = (raw or "").strip().lower()
    if value in ("1", "true", "on", "yes", "native", "bomi"):
        return True
    if value in ("0", "false", "off", "no", "non_native", "non-bomi", "non_bomi"):
        return False
    return None


def _apply_conscript_fields(
    db: Session,
    contract: Contract,
    *,
    contract_type_code: str,
    form,
    start_date: date,
) -> date:
    """
    برای وظیفه: ذخیره فیلدهای خدمت، start=اعزام، end محاسبه‌ای.
    برای غیر وظیفه: فیلدهای خدمت را خالی می‌کند.
    برمی‌گرداند: start_date نهایی.
    """
    if not msem.is_conscript(db, contract_type_code):
        contract.dispatch_date = None
        contract.unit_entry_date = None
        contract.clinic_entry_date = None
        contract.is_native = None
        contract.service_duty_region_code = None
        return start_date

    from models.membership_type_rule import (
        LEAVE_START_CLINIC_ENTRY,
        LEAVE_START_UNIT_ENTRY,
    )

    dispatch = _parse_jalali_optional(str(form.get("dispatch_date_str") or ""))
    unit_entry = _parse_jalali_optional(str(form.get("unit_entry_date_str") or ""))
    clinic_entry = _parse_jalali_optional(str(form.get("clinic_entry_date_str") or ""))
    region_code = (str(form.get("service_duty_region_code") or "")).strip() or None
    is_native = _parse_is_native(str(form.get("is_native") or ""))

    if dispatch is None:
        # سازگاری: اگر اعزام خالی بود از start استفاده کن
        dispatch = start_date
    if dispatch is None:
        raise ValueError("تاریخ اعزام برای عضویت وظیفه الزامی است")
    if not region_code:
        raise ValueError("انتخاب منطقه خدمت برای عضویت وظیفه الزامی است")

    basis = msem.resolve_leave_start_basis(
        db, contract_type_code, on_date=dispatch
    )
    if basis == LEAVE_START_UNIT_ENTRY and unit_entry is None:
        raise ValueError(
            "طبق پالیسی عضویت، مبنای شروع مرخصی «ورود به یگان» است؛ این تاریخ الزامی است"
        )
    if basis == LEAVE_START_CLINIC_ENTRY and clinic_entry is None:
        raise ValueError(
            "طبق پالیسی عضویت، مبنای شروع مرخصی «ورود به درمانگاه» است؛ این تاریخ الزامی است"
        )

    contract.dispatch_date = dispatch
    contract.unit_entry_date = unit_entry
    contract.clinic_entry_date = clinic_entry
    contract.is_native = is_native
    contract.service_duty_region_code = region_code
    contract.start_date = dispatch
    apply_end_date_to_contract(db, contract)
    return dispatch


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
        bb = leaves.get('BB', 0)
        if bb:
            parts.append(f"قابل‌بازخرید {bb}")
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


def _ensure_permanent_end(db, contract_type_code: str, start_date: date, end_date: Optional[date]) -> Optional[date]:
    """رسمی: پایان همیشه شروع + ۳۰ سال (ورودی کاربر نادیده گرفته می‌شود)."""
    if msem.is_permanent(db, contract_type_code):
        return add_years(start_date, 30)
    return end_date


@router.get("/contracts", response_class=HTMLResponse)
async def contracts_page(
    request: Request,
    search: Optional[str] = Query(None),
    type_filter: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    expiry_filter: Optional[str] = Query(None),
    file_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست عضویت‌ها / قراردادها"""
    enforce_permission(db, user, 'view_contracts')
    has_filter = any([search, type_filter, status_filter, expiry_filter, file_filter, show_all])
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

        if expiry_filter == 'soon':
            today_g = date.today()
            threshold = today_g + timedelta(days=30)
            query = query.filter(
                and_(
                    Contract.end_date.isnot(None),
                    Contract.end_date >= today_g,
                    Contract.end_date <= threshold,
                )
            )

        if file_filter == 'missing':
            query = query.filter(
                or_(
                    Contract.file_path.is_(None),
                    Contract.file_path == '',
                )
            )

        contracts = query.order_by(Contract.start_date.desc()).all()

        for c in contracts:
            employee = db.query(Employee).filter(Employee.user_id == c.user_id).first()
            start_j = jdatetime.date.fromgregorian(date=c.start_date)
            end_j = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None
            start_year = start_j.year
            stored_cw = get_stored_leave_balance(db, c.user_id, start_year)
            buyback_days = get_buyback_quota(db, c.user_id, start_year)
            # برای نمایش ویرایش: CW/BB سال جاری + مصرف تاریخچه
            current_year = jdatetime.date.today().year
            stored_cw_current = get_stored_leave_balance(db, c.user_id, current_year)
            buyback_current = get_buyback_quota(db, c.user_id, current_year)
            history_used = get_used_by_year_from_contract(db, c.id) if msem.is_permanent(db, c.contract_type_code) else {}

            def _j(d):
                if not d:
                    return ""
                return jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d")

            adjustments = list_adjustments_for_contract(db, c.id, active_only=True)
            contracts_data.append({
                'contract': c,
                'employee': employee,
                'full_name': employee.full_name if employee else f"کاربر {c.user_id}",
                'start_j': start_j.strftime('%Y/%m/%d'),
                'end_j': end_j.strftime('%Y/%m/%d') if end_j else 'دائمی',
                'dispatch_j': _j(c.dispatch_date),
                'unit_entry_j': _j(c.unit_entry_date),
                'clinic_entry_j': _j(c.clinic_entry_date),
                'is_conscript': msem.is_conscript(db, c.contract_type_code),
                'is_permanent': msem.is_permanent(db, c.contract_type_code),
                'is_active': c.is_active,
                'charged_by_year': get_charged_by_year(db, c.id),
                'stored_leave_days': stored_cw_current if msem.is_permanent(db, c.contract_type_code) else stored_cw,
                'buyback_leave_days': buyback_current if msem.is_permanent(db, c.contract_type_code) else buyback_days,
                'history_used': history_used,
                'history_used_json': json.dumps({str(k): v for k, v in history_used.items()}),
                'start_year': start_year,
                'adjustments': adjustments,
                'adjustments_count': len(adjustments),
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

    employees_for_search = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.first_name, Employee.last_name).all()
    employees_list = [
        {
            'user_id': emp.user_id,
            'full_name': emp.full_name,
            'department': emp.membership_name or emp.membership_type_code or '-',
            'organization': emp.department_name or '',
        }
        for emp in employees_for_search
    ]

    duty_regions = [
        region_as_dict(r) for r in list_duty_regions(db, active_only=True)
    ]
    return templates.TemplateResponse(request, "admin/contracts.html", {
        "user": user,
        "contracts": contracts_data,
        "total_count": len(contracts_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search or "",
        "type_filter": type_filter or "",
        "status_filter": status_filter or "",
        "expiry_filter": expiry_filter or "",
        "file_filter": file_filter or "",
        "employees": employees_list,
        "contract_types": membership_types_as_dict(db, active_only=True),
        "duty_regions": duty_regions,
        "is_admin": True,
        "membership_timeline": membership_timeline,
        "timeline_user_id": timeline_user_id,
        "timeline_name": timeline_name,
        "can_view_contracts": True,
        "can_add_contracts": has_permission(db, user, "add_contracts"),
        "can_edit_contracts": has_permission(db, user, "edit_contracts"),
        "can_delete_contracts": has_permission(db, user, "delete_contracts"),
    })


@router.get("/contracts/user/{target_user_id}", response_class=HTMLResponse)
async def admin_user_contract_view(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """صفحه قرارداد از نگاه کاربر (برای ادمین)."""
    enforce_permission(db, user, "view_contracts")
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(
            url="/admin/contracts?error=کاربر یافت نشد",
            status_code=302,
        )
    target_employee = (
        db.query(Employee).filter(Employee.user_id == target_user_id).first()
    )
    from web.routes.contract import build_user_contract_page_data

    data = build_user_contract_page_data(
        db,
        target_user_id,
        file_url_prefix="/admin/contracts",
    )
    display_name = (
        target_employee.full_name
        if target_employee
        else (target_user.name or target_user_id)
    )
    return templates.TemplateResponse(
        request,
        "contract.html",
        {
            "user": user,
            "today_j": data["today_j"],
            "contracts": data["contracts"],
            "active_contract": data["active_contract"],
            "stats": data["stats"],
            "is_admin": True,
            "viewing_as_admin": True,
            "target_user_id": target_user_id,
            "target_display_name": display_name,
        },
    )


@router.get("/contracts/preview-end-date")
async def contracts_preview_end_date(
    dispatch_date_str: str = Query(...),
    service_duty_region_code: str = Query(...),
    is_native: Optional[str] = Query(None),
    contract_id: Optional[int] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """پیش‌نمایش تاریخ پایان خدمت وظیفه (شمسی)."""
    enforce_permission(db, user, "view_contracts")
    try:
        dispatch = _parse_jalali_optional(dispatch_date_str)
        if dispatch is None:
            return JSONResponse({"error": "تاریخ اعزام نامعتبر است"}, status_code=400)
        native = _parse_is_native(is_native or "")
        end = preview_end_date(
            db,
            dispatch_date=dispatch,
            region_code=service_duty_region_code.strip(),
            is_native=native,
            contract_id=contract_id,
        )
        end_j = jdatetime.date.fromgregorian(date=end).strftime("%Y/%m/%d")
        return JSONResponse({"end_date": end.isoformat(), "end_date_j": end_j})
    except (ServiceEndDateError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)


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
    buyback_leave_days: int = Form(0),
    description: str = Form(""),
    contract_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ثبت عضویت جدید + شارژ مرخصی"""
    enforce_permission(db, user, 'add_contracts')
    try:
        membership_types = membership_types_as_dict(db, active_only=True)
        if contract_type_code not in membership_types:
            raise ValueError("نوع عضویت نامعتبر است")
        if stored_leave_days < 0:
            raise ValueError("مرخصی ذخیره نمی‌تواند منفی باشد")
        if buyback_leave_days < 0:
            raise ValueError("قابل‌بازخرید نمی‌تواند منفی باشد")

        form = await request.form()
        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()

        end_date = None
        if end_date_str.strip():
            end_j = jdatetime.datetime.strptime(end_date_str.strip(), "%Y/%m/%d").date()
            end_date = end_j.togregorian()

        end_date = _ensure_permanent_end(db, contract_type_code, start_date, end_date)

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            referer = request.headers.get("referer", "/admin/contracts")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "کاربر یافت نشد"),
                status_code=302
            )

        rule = get_effective_rule(db, contract_type_code, on_date=start_date)
        if not rule or not rule.supports_service_deduction:
            service_deduction_days = 0

        # منطقه خدمتی از شهر محل خدمت؛ قبل از محاسبه استحقاق همگام شود
        region_code = sync_employee_region_from_service_location(
            db, user_id, commit=False, approved_by=user.user_id,
        )

        # editable_leave حذف شد — annual همیشه از Membership Rule + منطقه
        annual_leave_days = resolve_annual_leave_days(
            db,
            contract_type_code,
            region_code=region_code,
        )
        sick_leave_days = 0

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

        if msem.is_conscript(db, contract_type_code):
            start_date = _apply_conscript_fields(
                db,
                new_contract,
                contract_type_code=contract_type_code,
                form=form,
                start_date=start_date,
            )
            start_j = jdatetime.date.fromgregorian(date=start_date)
            end_date = new_contract.end_date
            service_deduction_days = new_contract.service_deduction_days

        if end_date and start_date >= end_date:
            raise ValueError("تاریخ شروع باید قبل از تاریخ پایان باشد")

        overlapping = find_overlapping_contract(
            db, user_id, start_date, end_date, exclude_id=new_contract.id
        )
        if overlapping:
            raise ValueError(
                f"تداخل بازه با عضویت موجود (شروع: "
                f"{jdatetime.date.fromgregorian(date=overlapping.start_date).strftime('%Y/%m/%d')})"
            )

        if contract_file and contract_file.filename:
            new_contract.file_path = await _save_contract_file(
                contract_file, user_id=user_id, contract_id=new_contract.id,
            )

        db.commit()
        db.refresh(new_contract)

        used_by_year = parse_used_by_year_from_form(form)
        current_year = jdatetime.date.today().year
        needs_history = (
            msem.is_permanent(db, contract_type_code) and start_j.year < current_year
        )

        if needs_history:
            # سال‌های قبل فقط از تاریخچه (CHARGE/CF_OUT طبق سقف ذخیره پالیسی)
            charged = charge_leave_for_new_contract(
                db, new_contract, years_filter={current_year}
            )
            hist = apply_permanent_history(
                db, new_contract, used_by_year, commit=True
            )
            charged.setdefault(current_year, {})['CW'] = hist['stored_cw']
            charged.setdefault(current_year, {})['BB'] = hist['buyback']
        else:
            charged = charge_leave_for_new_contract(db, new_contract)
        if not needs_history:
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

            if buyback_leave_days > 0 or get_buyback_quota(db, user_id, start_year) != buyback_leave_days:
                bb_result = set_buyback_quota_for_year(
                    db,
                    user_id=user_id,
                    year=start_year,
                    target_days=buyback_leave_days,
                    source='MANUAL',
                    notes=f"ورود قابل‌بازخرید هنگام ثبت عضویت #{new_contract.id} توسط {user.user_id}",
                    commit=True,
                )
                if bb_result['new'] or bb_result['diff']:
                    charged.setdefault(start_year, {})['BB'] = bb_result['new']

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


@router.get("/contracts/permanent-history-plan")
async def permanent_history_plan(
    request: Request,
    user_id: str = Query(...),
    start_date_str: str = Query(...),
    contract_id: Optional[int] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """پیش‌نمایش سال‌ها و استحقاق تاریخچه رسمی برای مودال."""
    if not (
        has_permission(db, user, 'add_contracts')
        or has_permission(db, user, 'edit_contracts')
    ):
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
    try:
        start_j = jdatetime.datetime.strptime(start_date_str.strip(), "%Y/%m/%d").date()
        start_date = start_j.togregorian()
    except Exception:
        return JSONResponse({"error": "تاریخ شروع نامعتبر است"}, status_code=400)

    used_by_year = {}
    if contract_id:
        used_by_year = get_used_by_year_from_contract(db, contract_id)

    summary = preview_history_summary(
        db,
        user_id=user_id,
        start_date=start_date,
        used_by_year=used_by_year,
    )
    # Ensure per-year caps are JSON-friendly for the contracts UI
    for row in summary.get('years') or []:
        if 'storage_cap' not in row:
            row['storage_cap'] = summary.get('carry_forward_cap')
        if 'buyback_cap' not in row:
            row['buyback_cap'] = summary.get('buyback_cap')
    return JSONResponse(summary)


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
    buyback_leave_days: int = Form(0),
    description: str = Form(""),
    remove_contract_file: str = Form(""),
    contract_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش عضویت + بروزرسانی مرخصی"""
    enforce_permission(db, user, 'edit_contracts')
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
        if buyback_leave_days < 0:
            raise ValueError("قابل‌بازخرید نمی‌تواند منفی باشد")

        form = await request.form()
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

        end_date = _ensure_permanent_end(db, contract_type_code, start_date, end_date)

        membership_types = membership_types_as_dict(db, active_only=True)
        if contract_type_code not in membership_types:
            raise ValueError("نوع عضویت نامعتبر است")

        rule = get_effective_rule(db, contract_type_code, on_date=start_date)
        if not rule or not rule.supports_service_deduction:
            service_deduction_days = 0

        employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()
        region_code = None
        if employee:
            region_code = sync_employee_region_from_service_location(
                db, contract.user_id, commit=False, approved_by=user.user_id,
            )

        annual_leave_days = resolve_annual_leave_days(
            db,
            contract_type_code,
            region_code=region_code,
        )
        sick_leave_days = 0

        contract.contract_type_code = contract_type_code
        contract.start_date = start_date
        contract.end_date = end_date
        contract.annual_leave_days = annual_leave_days
        contract.sick_leave_days = sick_leave_days
        contract.service_deduction_days = service_deduction_days
        contract.description = description.strip() or None

        if msem.is_conscript(db, contract_type_code):
            start_date = _apply_conscript_fields(
                db,
                contract,
                contract_type_code=contract_type_code,
                form=form,
                start_date=start_date,
            )
            start_j = jdatetime.date.fromgregorian(date=start_date)
            end_date = contract.end_date
            service_deduction_days = contract.service_deduction_days
        else:
            contract.dispatch_date = None
            contract.unit_entry_date = None
            contract.clinic_entry_date = None
            contract.is_native = None
            contract.service_duty_region_code = None

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

        used_by_year = parse_used_by_year_from_form(form)
        current_year = jdatetime.date.today().year
        needs_history = (
            msem.is_permanent(db, contract_type_code) and start_j.year < current_year
        )

        if needs_history:
            # سال‌های قبل فقط از تاریخچه؛ پروراتا فقط سال جاری را لمس کند
            hist_years = set(range(start_j.year, current_year))
            changes = update_leave_for_contract(
                db=db,
                contract=contract,
                old_annual_leave=old_annual,
                old_sick_leave=old_sick,
                old_start_date=old_start,
                old_end_date=old_end,
                old_deduction=old_deduction,
                old_type_code=old_type_code,
                skip_years=hist_years,
            )
            hist = apply_permanent_history(
                db, contract, used_by_year, commit=True
            )
            changes.setdefault(current_year, {})['CW'] = hist['stored_cw']
            changes.setdefault(current_year, {})['BB'] = hist['buyback']
        else:
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
            if msem.is_permanent(db, old_type_code) or msem.is_permanent(db, contract_type_code):
                clear_permanent_history(db, contract)
                db.commit()
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

            bb_result = set_buyback_quota_for_year(
                db,
                user_id=contract.user_id,
                year=start_year,
                target_days=buyback_leave_days,
                source='MANUAL',
                notes=f"تنظیم قابل‌بازخرید هنگام ویرایش عضویت #{contract.id} توسط {user.user_id}",
                commit=True,
            )
            if bb_result['diff'] != 0:
                changes.setdefault(start_year, {})['BB'] = bb_result['diff']

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
    enforce_permission(db, user, 'delete_contracts')
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
        if msem.is_permanent(db, contract.contract_type_code):
            clear_permanent_history(db, contract)
            db.flush()
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
    try:
        disk = resolve_contract_file_disk(contract.file_path)
    except ValueError:
        return RedirectResponse(
            url="/admin/contracts?error=فایل قرارداد یافت نشد",
            status_code=302,
        )
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
