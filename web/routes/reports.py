"""
پنل گزارشات مدیریتی
"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from typing import Optional
import jdatetime

from web.dependencies import get_db, require_admin
from models.user import User
from models.employee import Employee
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import os

# 🆕 import کلاس گزارش - مسیر را بر اساس محل فایل تنظیم کنید
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2

router = APIRouter(tags=["Reports"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# نام ماه‌های شمسی
JALALI_MONTHS = {
    1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
    4: 'تیر', 5: 'مرداد', 6: 'شهریور',
    7: 'مهر', 8: 'آبان', 9: 'آذر',
    10: 'دی', 11: 'بهمن', 12: 'اسفند'
}


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """صفحه اصلی گزارشات"""
    # سال‌های موجود برای انتخاب
    current_year_j = jdatetime.date.today().year
    available_years = list(range(current_year_j - 3, current_year_j + 1))

    return templates.TemplateResponse(request, "admin/reports.html", {
        "user": user,
        "available_years": available_years,
        "current_year": current_year_j,
        "current_month": jdatetime.date.today().month,
        "is_admin": True,
    })


@router.get("/reports/monthly-detailed", response_class=HTMLResponse)
async def monthly_detailed_report_form(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """فرم انتخاب کاربر و ماه برای گزارش تفصیلی"""
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

    # سال‌های موجود
    current_year_j = jdatetime.date.today().year
    available_years = list(range(current_year_j - 3, current_year_j + 1))

    return templates.TemplateResponse(request, "admin/report_monthly_detailed.html", {
        "user": user,
        "employees": employees_list,
        "available_years": available_years,
        "jalali_months": JALALI_MONTHS,
        "current_year": current_year_j,
        "current_month": jdatetime.date.today().month,
        "report": None,
        "is_admin": True,
    })


@router.post("/reports/monthly-detailed")
async def monthly_detailed_report_generate(
        request: Request,
        target_user_id: str = Form(...),
        year: int = Form(...),
        month: int = Form(...),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تولید گزارش تفصیلی ماهانه"""
    try:
        # اعتبارسنجی ماه
        if month < 1 or month > 12:
            raise ValueError("ماه نامعتبر است")

        # تولید گزارش با کلاس گزارش‌ساز
        generator = DetailedMonthlyReportGeneratorV2()
        try:
            report = generator.generate_detailed_report(target_user_id, year, month)
        finally:
            generator.close()

        if not report.get('success'):
            raise ValueError(report.get('message', 'خطا در تولید گزارش'))

        # دریافت لیست کارمندان برای فرم
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

        current_year_j = jdatetime.date.today().year
        available_years = list(range(current_year_j - 3, current_year_j + 1))

        return templates.TemplateResponse(request, "admin/report_monthly_detailed.html", {
            "user": user,
            "employees": employees_list,
            "available_years": available_years,
            "jalali_months": JALALI_MONTHS,
            "current_year": current_year_j,
            "current_month": jdatetime.date.today().month,
            "report": report,
            "selected_user_id": target_user_id,
            "selected_year": year,
            "selected_month": month,
            "is_admin": True,
        })
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/reports/monthly-detailed?error={str(e)}",
            status_code=302
        )


# ============================================
# 🆕 تبدیل ساعت اعشاری به فرمت HH:MM
# ============================================
def format_hhmm(hours):
    """تبدیل ساعت اعشاری به فرمت HH:MM"""
    if hours is None or hours == 0:
        return '-'
    total_minutes = int(round(hours * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


# ثبت filter در Jinja2
templates.env.filters['hhmm'] = format_hhmm


# ============================================
# 🆕 گزارش کامل ماهانه (شبیه PDF)
# ============================================

@router.get("/reports/monthly-full", response_class=HTMLResponse)
async def monthly_full_report_form(
        request: Request,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """فرم گزارش کامل ماهانه (شبیه PDF)"""
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

    current_year_j = jdatetime.date.today().year
    available_years = list(range(current_year_j - 3, current_year_j + 1))

    return templates.TemplateResponse(request, "admin/report_monthly_full.html", {
        "user": user,
        "employees": employees_list,
        "available_years": available_years,
        "jalali_months": JALALI_MONTHS,
        "current_year": current_year_j,
        "current_month": jdatetime.date.today().month,
        "report": None,
        "is_admin": True,
    })


@router.post("/reports/monthly-full")
async def monthly_full_report_generate(
        request: Request,
        target_user_id: str = Form(...),
        year: int = Form(...),
        month: int = Form(...),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تولید گزارش کامل ماهانه (شبیه PDF)"""
    try:
        if month < 1 or month > 12:
            raise ValueError("ماه نامعتبر است")

        generator = DetailedMonthlyReportGeneratorV2()
        try:
            report = generator.generate_detailed_report(target_user_id, year, month)
        finally:
            generator.close()

        if not report.get('success'):
            raise ValueError(report.get('message', 'خطا در تولید گزارش'))

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

        current_year_j = jdatetime.date.today().year
        available_years = list(range(current_year_j - 3, current_year_j + 1))

        return templates.TemplateResponse(request, "admin/report_monthly_full.html", {
            "user": user,
            "employees": employees_list,
            "available_years": available_years,
            "jalali_months": JALALI_MONTHS,
            "current_year": current_year_j,
            "current_month": jdatetime.date.today().month,
            "report": report,
            "selected_user_id": target_user_id,
            "selected_year": year,
            "selected_month": month,
            "is_admin": True,
        })
    except Exception as e:
        return RedirectResponse(
            url=f"/reports/monthly-full?error={str(e)}",
            status_code=302
        )