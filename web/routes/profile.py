"""صفحه پروفایل کاربر"""
from datetime import date
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
import jdatetime

from web.dependencies import get_db, check_password_change
from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone

router = APIRouter(tags=["Profile"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# رنگ‌های آواتار بر اساس hash نام
AVATAR_COLORS = [
    'primary', 'success', 'info', 'warning',
    'danger', 'secondary', 'dark'
]


def calculate_age(birth_date: date) -> int:
    """محاسبه سن"""
    today = date.today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def calculate_service_years(hire_date: date) -> dict:
    """محاسبه سابقه کار به سال و ماه"""
    today = date.today()
    years = today.year - hire_date.year
    months = today.month - hire_date.month

    if today.day < hire_date.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12

    return {'years': years, 'months': months}


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    """صفحه پروفایل کاربر"""
    employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()

    today_j = jdatetime.date.today()

    # محاسبات
    age = None
    age_j_display = None
    if employee and employee.birth_date:
        age = calculate_age(employee.birth_date)
        j_birth = jdatetime.date.fromgregorian(date=employee.birth_date)
        age_j_display = j_birth.strftime('%Y/%m/%d')

    service = None
    hire_j_display = None
    if employee and employee.hire_date:
        service = calculate_service_years(employee.hire_date)
        hire_j_display = jdatetime.date.fromgregorian(date=employee.hire_date).strftime('%Y/%m/%d')

    # حروف اول نام برای آواتار
    avatar_initials = ""
    avatar_color = "primary"
    if employee:
        avatar_initials = f"{employee.first_name[0] if employee.first_name else ''}{employee.last_name[0] if employee.last_name else ''}"
        # رنگ بر اساس hash نام
        name_hash = sum(ord(c) for c in employee.full_name)
        avatar_color = AVATAR_COLORS[name_hash % len(AVATAR_COLORS)]

    # تاریخ‌های شمسی
    birth_j_display = None
    if employee and employee.birth_date:
        birth_j_display = jdatetime.date.fromgregorian(date=employee.birth_date).strftime('%Y/%m/%d')

    termination_j_display = None
    if employee and employee.termination_date:
        termination_j_display = jdatetime.date.fromgregorian(date=employee.termination_date).strftime('%Y/%m/%d')

    # 🆕 خواندن آخرین ورود قبلی از session
    last_login_display = None
    previous_login_str = request.session.get('previous_login')
    if previous_login_str:
        try:
            from datetime import datetime
            previous_login = datetime.fromisoformat(previous_login_str)
            last_login_j = jdatetime.datetime.fromgregorian(datetime=previous_login)
            last_login_display = last_login_j.strftime('%Y/%m/%d - %H:%M')
        except Exception:
            last_login_display = previous_login_str
    else:
        last_login_display = "اولین ورود شما"

    # 🆕 دریافت شماره‌های تلفن کاربر
    phones = db.query(EmployeePhone).filter(
        EmployeePhone.user_id == user.user_id
    ).order_by(EmployeePhone.is_default.desc(), EmployeePhone.created_at).all()

    # 🆕 دریافت آدرس‌های کاربر از طریق سرویس
    from models.city import City
    from web.services.address_service import list_addresses
    addresses = list_addresses(db, user.user_id)
    cities = db.query(City).filter(City.is_active == True).order_by(
        City.province, City.name).all()
    # تاریخ‌های شمسی برای نمایش در قالب (مشابه پنل ادمین)
    for addr in addresses:
        try:
            addr.valid_from_j = (
                jdatetime.date.fromgregorian(date=addr.valid_from).strftime('%Y/%m/%d')
                if addr.valid_from else ""
            )
        except Exception:
            addr.valid_from_j = ""
        try:
            addr.valid_to_j = (
                jdatetime.date.fromgregorian(date=addr.valid_to).strftime('%Y/%m/%d')
                if addr.valid_to else ""
            )
        except Exception:
            addr.valid_to_j = ""
    # شهرهای غیرفعالِ مرتبط با آدرس موجود: فقط برای نمایش در فرم ویرایش همان آدرس
    active_city_ids = {c.id for c in cities}
    orphan_city_ids = {a.city_id for a in addresses
                       if a.city_id and a.city_id not in active_city_ids}
    inactive_linked = {}
    if orphan_city_ids:
        for linked in db.query(City).filter(City.id.in_(orphan_city_ids)).all():
            for addr in addresses:
                if addr.city_id == linked.id:
                    inactive_linked[addr.id] = linked

    return templates.TemplateResponse(request, "profile.html", {
        "user": user,
        "employee": employee,
        "today_j": today_j,
        "age": age,
        "birth_j_display": birth_j_display,
        "service": service,
        "hire_j_display": hire_j_display,
        "avatar_initials": avatar_initials,
        "avatar_color": avatar_color,
        "termination_j_display": termination_j_display,
        "is_admin": user.is_admin,
        "photo_path": employee.photo_path if employee else None,
        "last_login_display": last_login_display,
        "phones": phones,
        "addresses": addresses,
        "cities": cities,
        "inactive_linked": inactive_linked,
    })