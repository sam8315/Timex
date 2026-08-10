"""صفحه قراردادها"""
from datetime import date
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.contract import Contract

router = APIRouter(tags=["Contract"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

CONTRACT_TYPE_NAMES = {
    'رسمی': 'رسمی',
    'وظیفه': 'وظیفه',
    'خریدخدمت': 'خرید خدمت',
    'قراردادی': 'قراردادی',
    'پزشک': 'پزشک',
}


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

    for c in contracts_raw:
        j_start = jdatetime.date.fromgregorian(date=c.start_date)
        j_end = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else None

        # بررسی فعال بودن
        is_active = (
            c.start_date <= today_g and
            (c.end_date is None or c.end_date >= today_g)
        )

        contract_data = {
            'id': c.id,
            'contract_type': c.contract_type_name,
            'contract_type_name': CONTRACT_TYPE_NAMES.get(c.contract_type, c.contract_type),
            'start_date_j': j_start.strftime('%Y/%m/%d'),
            'end_date_j': j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود',
            'annual_leave_days': c.annual_leave_days,
            'sick_leave_days': c.sick_leave_days,
            'reward_leave_days': c.reward_leave_days,
            'unpaid_leave_days': c.unpaid_leave_days,
            'description': c.description or '-',
            'is_active': is_active,
        }

        contracts.append(contract_data)

        if is_active:
            active_contract = contract_data

    return templates.TemplateResponse(request, "contract.html", {
        "user": user,
        "today_j": today_j,
        "contracts": contracts,
        "active_contract": active_contract,
        "is_admin": user.is_admin,
    })