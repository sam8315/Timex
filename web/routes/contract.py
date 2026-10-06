"""صفحه قراردادها (نمای کاربر + دادهٔ مشترک برای ادمین)."""
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.contract import Contract
from web.services.contract_file_storage import resolve_contract_file_disk
from web.services.service_adjustment_service import list_adjustments_for_contract
from web.services import membership_semantics as msem
from web.services.conscript_service_context import build_conscript_service_context
from web.services.service_duty_region_service import get_duty_region
from web.services.leave_service import calculate_prorated_leave_by_year

router = APIRouter(tags=["Contract"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _jdate(d: Optional[date]) -> Optional[str]:
    if d is None:
        return None
    return jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')


def _conscript_fields(db: Session, c: Contract) -> Dict[str, Any]:
    """Extra display fields for conscript contracts (empty for others)."""
    empty = {
        'is_conscript': False,
        'dispatch_j': None,
        'unit_entry_j': None,
        'clinic_entry_j': None,
        'duty_region_code': None,
        'duty_region_name': None,
        'is_native': None,
        'native_label': None,
        'leave_start_basis': None,
        'leave_start_basis_label': None,
        'leave_start_j': None,
        'period_entitlement_rounded': None,
    }
    if not msem.is_conscript(db, c.contract_type_code):
        return empty

    duty_name = None
    if c.service_duty_region_code:
        region = get_duty_region(db, c.service_duty_region_code)
        duty_name = region.name if region else c.service_duty_region_code

    leave_basis = msem.resolve_leave_start_basis(
        db, c.contract_type_code, on_date=c.start_date or date.today()
    )
    leave_start = msem.resolve_conscript_leave_start(db, c)
    period_ent = None
    try:
        prorated = calculate_prorated_leave_by_year(
            c, db=db, annual_override=c.annual_leave_days
        )
        period_ent = sum(round(v.get('AL', 0)) for v in prorated.values())
    except Exception:
        period_ent = None

    try:
        ctx = build_conscript_service_context(db, c)
        leave_basis = ctx.leave_start_date_basis or leave_basis
        leave_start = ctx.leave_entitlement_start or leave_start
    except Exception:
        pass

    native_label = None
    if c.is_native is True:
        native_label = 'بومی'
    elif c.is_native is False:
        native_label = 'غیر بومی'

    return {
        'is_conscript': True,
        'dispatch_j': _jdate(c.dispatch_date or c.start_date),
        'unit_entry_j': _jdate(c.unit_entry_date),
        'clinic_entry_j': _jdate(c.clinic_entry_date),
        'duty_region_code': c.service_duty_region_code,
        'duty_region_name': duty_name,
        'is_native': c.is_native,
        'native_label': native_label,
        'leave_start_basis': leave_basis,
        'leave_start_basis_label': msem.leave_start_basis_label(leave_basis),
        'leave_start_j': _jdate(leave_start),
        'period_entitlement_rounded': period_ent,
    }


def build_user_contract_page_data(
    db: Session,
    user_id: str,
    *,
    file_url_prefix: str = "/contract",
) -> Dict[str, Any]:
    """ساخت دادهٔ نمایش صفحه قرارداد از نگاه یک کاربر."""
    today_g = date.today()
    today_j = jdatetime.date.today()

    contracts_raw = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.desc())
        .all()
    )

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

        j_start = jdatetime.date.fromgregorian(date=c.start_date)
        j_end = (
            jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None
        )
        j_actual_end = (
            jdatetime.date.fromgregorian(date=c.actual_end_date)
            if c.actual_end_date
            else None
        )

        duration_days = c.contract_duration_days
        duration_text = f"{duration_days} روز" if duration_days else 'باز'

        days_elapsed = (
            (today_g - c.start_date).days
            if c.is_active or today_g > c.start_date
            else 0
        )
        days_elapsed = max(0, days_elapsed)

        if c.actual_end_date:
            days_remaining = max(0, (c.actual_end_date - today_g).days)
            total_days = (c.actual_end_date - c.start_date).days
            progress_percent = (
                round((days_elapsed / total_days * 100), 1) if total_days > 0 else 0
            )
        else:
            days_remaining = None
            total_days = None
            progress_percent = None

        contract_data = {
            'id': c.id,
            'contract_type_code': c.contract_type_code,
            'contract_type_name': c.contract_type_name,
            'start_date_j': j_start.strftime('%Y/%m/%d'),
            'end_date_j': j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود',
            'actual_end_date_j': (
                j_actual_end.strftime('%Y/%m/%d') if j_actual_end else 'نامحدود'
            ),
            'annual_leave_days': c.annual_leave_days,
            'sick_leave_days': c.sick_leave_days,
            'prorated_annual_leave': c.prorated_annual_leave,
            'prorated_sick_leave': c.prorated_sick_leave,
            'service_deduction_days': c.service_deduction_days,
            'allow_service_deduction': c.allow_service_deduction,
            'adjustments': list_adjustments_for_contract(
                db, c.id, active_only=True
            ),
            'is_active': c.is_active,
            'status_name': c.status_name,
            'duration_days': duration_days,
            'duration_text': duration_text,
            'days_elapsed': days_elapsed,
            'days_remaining': days_remaining,
            'total_days': total_days,
            'progress_percent': progress_percent,
            'description': c.description or '-',
            'has_file': c.file_path is not None,
            'file_url': (
                f"{file_url_prefix}/{c.id}/file" if c.file_path else None
            ),
            **_conscript_fields(db, c),
        }

        contracts.append(contract_data)

        if c.is_active and active_contract is None:
            active_contract = contract_data

        if c.is_active:
            stats['active_contracts'] += 1
        elif c.status_name == '⏰ منقضی':
            stats['expired_contracts'] += 1
        else:
            stats['pending_contracts'] += 1

    return {
        'today_j': today_j,
        'contracts': contracts,
        'active_contract': active_contract,
        'stats': stats,
    }


@router.get("/contract", response_class=HTMLResponse)
async def contract_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    """صفحه قراردادهای کاربر"""
    data = build_user_contract_page_data(db, user.user_id)
    return templates.TemplateResponse(request, "contract.html", {
        "user": user,
        "today_j": data["today_j"],
        "contracts": data["contracts"],
        "active_contract": data["active_contract"],
        "stats": data["stats"],
        "is_admin": user.is_admin,
        "viewing_as_admin": False,
        "target_user_id": user.user_id,
        "target_display_name": None,
    })


@router.get("/contract/{contract_id}/file")
async def view_own_contract_file(
    contract_id: int,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db),
):
    """دانلود فایل قرارداد فقط برای مالک قرارداد."""
    contract = db.query(Contract).filter(
        Contract.id == contract_id,
        Contract.user_id == user.user_id,
    ).first()
    if not contract or not contract.file_path:
        return RedirectResponse(url="/contract?error=فایل قرارداد یافت نشد", status_code=302)

    try:
        disk = resolve_contract_file_disk(contract.file_path)
    except ValueError:
        return RedirectResponse(url="/contract?error=فایل قرارداد یافت نشد", status_code=302)

    if not disk.is_file():
        return RedirectResponse(
            url="/contract?error=فایل قرارداد روی دیسک موجود نیست",
            status_code=302,
        )

    return FileResponse(
        path=str(disk),
        filename=disk.name,
        media_type=None,
        content_disposition_type="inline",
    )
