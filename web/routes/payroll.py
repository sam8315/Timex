"""حقوق من — فیش منتشرشده کارمند."""
from __future__ import annotations

from pathlib import Path

import jdatetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_current_user, get_db
from web.services.payroll import run_service
from core.payroll.pdf_payslip import build_payslip_pdf
from core.payroll.payslip_present import fa_digits, line_detail, money_text, payslip_sort
from web.services.payroll.payslip_profile import load_payslip_profile

router = APIRouter(tags=["Payroll"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
templates.env.filters["line_detail"] = line_detail
templates.env.filters["money_text"] = money_text
templates.env.filters["fa_digits"] = fa_digits
templates.env.filters["payslip_sort"] = payslip_sort


@router.get("/payroll", response_class=HTMLResponse)
async def my_payslips(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = jdatetime.date.today()
    year_j = int(request.query_params.get("year") or today.year)
    month_j = int(request.query_params.get("month") or today.month)
    result = run_service.get_published_result_for_user(db, user.user_id, year_j, month_j)
    return templates.TemplateResponse(
        request,
        "payroll/my_payslips.html",
        {
            "user": user,
            "is_admin": user.is_admin,
            "year_j": year_j,
            "month_j": month_j,
            "result": result,
            "items": sorted(result.items, key=lambda i: i.sort_order) if result else [],
            "period_label": f"{year_j}/{month_j:02d}",
        },
    )


@router.get("/payroll/payslip/{result_id}", response_class=HTMLResponse)
async def my_payslip_detail(
    result_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = run_service.get_result(db, result_id)
    if result.user_id != user.user_id or result.run.status != "published":
        return templates.TemplateResponse(
            request,
            "payroll/my_payslips.html",
            {
                "user": user,
                "is_admin": user.is_admin,
                "year_j": jdatetime.date.today().year,
                "month_j": jdatetime.date.today().month,
                "result": None,
                "items": [],
                "period_label": "",
                "error": "فیش در دسترس نیست",
            },
            status_code=403,
        )
    period = result.run.period
    return templates.TemplateResponse(
        request,
        "payroll/payslip_detail.html",
        {
            "user": user,
            "is_admin": user.is_admin,
            "result": result,
            "items": sorted(result.items, key=lambda i: i.sort_order),
            "period_label": f"{period.year_j}/{period.month_j:02d}",
            "profile": load_payslip_profile(db, result),
            "pdf_url": f"/payroll/payslip/{result_id}/pdf",
            "back_url": f"/payroll?year={period.year_j}&month={period.month_j}",
        },
    )


@router.get("/payroll/payslip/{result_id}/pdf")
async def my_payslip_pdf(
    result_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = run_service.get_result(db, result_id)
    if result.user_id != user.user_id or result.run.status != "published":
        return Response(content="Forbidden", status_code=403)
    period = result.run.period
    label = f"{period.year_j}/{period.month_j:02d}"
    data = build_payslip_pdf(
        result,
        result.items,
        label,
        profile=load_payslip_profile(db, result),
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip_{result_id}.pdf"'},
    )
