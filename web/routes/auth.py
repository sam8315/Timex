"""مسیرهای احراز هویت"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from web.dependencies import get_db
from web.security import verify_password, hash_password
from web.session import (
    set_session_cookie, clear_session_cookie, get_session_from_request
)
from models.user import User
from models.employee import Employee

router = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    national_code: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # پیدا کردن employee با کد ملی
    employee = db.query(Employee).filter(
        Employee.national_code == national_code.strip()
    ).first()

    if not employee:
        return templates.TemplateResponse(request, "login.html", {
            "error": "❌ کد ملی یا رمز عبور اشتباه است"
        })

    # پیدا کردن user
    user = db.query(User).filter(User.user_id == employee.user_id).first()
    if not user:
        return templates.TemplateResponse(request, "login.html", {
            "error": "❌ کد ملی یا رمز عبور اشتباه است"
        })

    # بررسی فعال بودن وب
    if not user.web_enabled:
        return templates.TemplateResponse(request, "login.html", {
            "error": "❌ دسترسی وب برای این حساب غیرفعال است"
        })

    # بررسی قفل بودن
    if user.is_locked:
        return templates.TemplateResponse(request, "login.html", {
            "error": "⏱️ حساب قفل است. ۳۰ دقیقه صبر کنید"
        })

    # بررسی رمز عبور
    if not user.password_hash or not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= 5:
            user.locked_until = datetime.now() + timedelta(minutes=30)
            user.failed_attempts = 0
        db.commit()
        return templates.TemplateResponse(request, "login.html", {
            "error": "❌ کد ملی یا رمز عبور اشتباه است"
        })

    # موفق
    user.failed_attempts = 0
    user.locked_until = None
    # 🆕 ذخیره آخرین ورود قبلی در session (قبل از آپدیت)
    if user.last_login:
        request.session['previous_login'] = user.last_login.isoformat()
    else:
        request.session['previous_login'] = None

    # آپدیت last_login به زمان فعلی
    user.last_login = datetime.now()
    db.commit()

    # Redirect
    if user.must_change_password:
        response = RedirectResponse(url="/change-password", status_code=302)
    else:
        response = RedirectResponse(url="/dashboard", status_code=302)

    set_session_cookie(response, user.user_id, user.role)
    return response


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request, db: Session = Depends(get_db)):
    session = get_session_from_request(request)
    if not session:
        return RedirectResponse(url="/login", status_code=302)

    # 🆕 دریافت اطلاعات کاربر برای بررسی حالت اجباری
    user = db.query(User).filter(User.user_id == session["user_id"]).first()
    must_change = user.must_change_password if user else False

    return templates.TemplateResponse(request, "change_password.html", {
        "error": None,
        "success": None,
        "must_change": must_change,  # 🆕
    })


@router.post("/change-password")
async def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    session = get_session_from_request(request)
    if not session:
        return RedirectResponse(url="/login", status_code=302)

    user = db.query(User).filter(User.user_id == session["user_id"]).first()
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # بررسی رمز فعلی
    if not user.password_hash or not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(request, "change_password.html", {
            "error": "❌ رمز عبور فعلی اشتباه است",
            "success": None
        })

    # بررسی تطابق
    if new_password != confirm_password:
        return templates.TemplateResponse(request, "change_password.html", {
            "error": "❌ رمز جدید و تکرار آن یکسان نیستند",
            "success": None
        })

    # بررسی طول
    if len(new_password) < 6:
        return templates.TemplateResponse(request, "change_password.html", {
            "error": "❌ رمز عبور باید حداقل ۶ کاراکتر باشد",
            "success": None
        })

    # بررسی کد ملی نبودن
    employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()
    if employee and employee.national_code and new_password == employee.national_code:
        return templates.TemplateResponse(request, "change_password.html", {
            "error": "❌ رمز عبور نمی‌تواند کد ملی باشد",
            "success": None
        })

    # ذخیره
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()

    return templates.TemplateResponse(request, "change_password.html", {
        "error": None,
        "success": "✅ رمز عبور تغییر کرد. در حال انتقال..."
    })


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    clear_session_cookie(response)
    return response