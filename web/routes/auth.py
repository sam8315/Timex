"""مسیرهای احراز هویت"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from urllib.parse import quote as _quote

from web.dependencies import get_db
from web.security import verify_password, hash_password
from web.session import (
    set_session_cookie, clear_session_cookie, get_session_from_request,
    set_reset_cookie, clear_reset_cookie, get_reset_context,
)
from models.user import User
from models.employee import Employee
from models.employee_phone import EmployeePhone
from models.password_reset import PasswordResetRequest
from web.services.password_reset_service import PasswordResetService

router = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)
    msg = request.query_params.get("msg")
    return templates.TemplateResponse(request, "login.html", {"error": None, "msg": msg})


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
    clear_reset_cookie(response)
    return response


def _redirect_with_msg(url: str, msg: str) -> RedirectResponse:
    """ریدایرکت با پیام URL-encod شده."""
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url=f"{url}{sep}msg={_quote(msg, safe='')}", status_code=303)


def _mask_phone(phone: str) -> str:
    """شماره تلفن را ماسک می‌کند، مثال: ۰۹۱۲***۴۵۶۷"""
    if not phone or len(phone) < 8:
        return phone or ""
    visible_start = phone[:4]
    visible_end = phone[-4:]
    return f"{visible_start}***{visible_end}"


def _get_reset_service(db: Session) -> PasswordResetService:
    """ساخت سرویس بازنشانی رمز عبور با وابستگی به دیتابیس."""
    return PasswordResetService(db_session=db)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    """صفحه ورود کد ملی برای بازیابی رمز عبور."""
    session = get_session_from_request(request)
    if session:
        response = RedirectResponse(url="/dashboard", status_code=302)
        return response
    return templates.TemplateResponse(request, "forgot_password.html", {
        "error": None,
        "success": None,
    })


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    national_code: str = Form(...),
    db: Session = Depends(get_db),
):
    """پردازش درخواست بازنشانی رمز عبور با پیام عمومی برای جلوگیری از شناسایی حساب."""
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)

    svc = _get_reset_service(db)
    success, message = svc.create_password_reset_request(national_code.strip())

    # همیشه پیام عمومی نشان می‌دهیم؛ شناسایی حساب جلوگیری می‌شود
    success_message = "اگر اطلاعات واردشده صحیح باشد، کد بازیابی به شماره ثبت‌شده ارسال خواهد شد."

    if not success:
        return templates.TemplateResponse(request, "forgot_password.html", {
            "error": None,
            "success": success_message,
        })

    # یافتن درخواست برای ذخیره در cookie امضاشده
    employee = db.query(Employee).filter(
        Employee.national_code == national_code.strip()
    ).first()

    response = RedirectResponse(url="/verify-reset-code", status_code=303)
    if employee:
        request_obj = svc.get_latest_active_request(employee.user_id)
        if request_obj:
            set_reset_cookie(response, request_obj.id)
        else:
            clear_reset_cookie(response)
    else:
        clear_reset_cookie(response)
    return response


@router.get("/verify-reset-code", response_class=HTMLResponse)
async def verify_reset_code_page(
    request: Request,
    db: Session = Depends(get_db),
):
    """صفحه وارد کردن کد OTP."""
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)

    reset_ctx = get_reset_context(request)
    if not reset_ctx:
        return RedirectResponse(url="/login", status_code=302)

    masked_phone = None
    cooldown_remaining = 0

    reset_req = db.query(PasswordResetRequest).filter(
        PasswordResetRequest.id == reset_ctx["rid"]
    ).first()

    if reset_req:
        masked_phone = _mask_phone(reset_req.phone_number)
        eligible, remaining = PasswordResetService(db).check_resend_eligibility(
            reset_req.user_id
        )
        cooldown_remaining = remaining if remaining else 0

    return templates.TemplateResponse(request, "verify_reset_code.html", {
        "error": request.query_params.get("msg"),
        "masked_phone": masked_phone,
        "cooldown_remaining": cooldown_remaining,
    })


@router.post("/verify-reset-code", response_class=HTMLResponse)
async def verify_reset_code_submit(
    request: Request,
    db: Session = Depends(get_db),
    otp: str = Form(None),
    resend: str = Form(None),
):
    """اعتبارسنجی OTP یا ارسال مجدد کد."""
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)

    reset_ctx = get_reset_context(request)
    if not reset_ctx:
        return RedirectResponse(url="/login", status_code=302)

    svc = _get_reset_service(db)
    reset_req = db.query(PasswordResetRequest).filter(
        PasswordResetRequest.id == reset_ctx["rid"]
    ).first()

    if not reset_req:
        response = RedirectResponse(url="/login", status_code=302)
        clear_reset_cookie(response)
        return response

    # ----- Resend OTP -----
    if resend:
        employee_for_resend = db.query(Employee).filter(
            Employee.user_id == reset_req.user_id
        ).first()
        if employee_for_resend:
            success, message = svc.create_password_reset_request(
                employee_for_resend.national_code
            )
        else:
            success, message = False, "خطا در ارسال مجدد کد"

        if not success:
            eligible, remaining = svc.check_resend_eligibility(reset_req.user_id)
            if remaining:
                return _redirect_with_msg("/verify-reset-code", message)

        # به‌روزرسانی reset context با درخواست جدید
        new_req = svc.get_latest_active_request(reset_req.user_id)
        if new_req:
            response = RedirectResponse(url="/verify-reset-code", status_code=303)
            set_reset_cookie(response, new_req.id)
            return response
        return RedirectResponse(url="/login", status_code=303)

    # ----- Verify OTP -----
    if not otp:
        return _redirect_with_msg("/verify-reset-code", "کد بازیابی وارد نشده است")

    # نرمال‌سازی OTP: تبدیل فارسی/عربی به انگلیسی، حذف غیرعددی، حداکثر ۶ رقم
    import re as _re
    otp = _re.sub(r'[۰-۹]', lambda m: chr(ord(m.group()) - 0x06F0 + ord('0')), otp)
    otp = _re.sub(r'[٠-٩]', lambda m: chr(ord(m.group()) - 0x0660 + ord('0')), otp)
    otp = _re.sub(r'[^0-9]', '', otp)[:6]

    is_valid, message, validated_request = svc.validate_otp(
        reset_req.user_id, reset_req.phone_number, otp
    )

    if not is_valid:
        return _redirect_with_msg("/verify-reset-code", message)

    # موفقیت‌آمیز: تنظیم زمینه بازنشانی موقت
    response = RedirectResponse(url="/reset-password", status_code=303)
    clear_reset_cookie(response)
    set_reset_cookie(response, validated_request.id)
    return response


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    db: Session = Depends(get_db),
):
    """صفحه تنظیم رمز عبور جدید."""
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)

    reset_ctx = get_reset_context(request)
    if not reset_ctx:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(request, "reset_password.html", {
        "error": None,
    })


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    db: Session = Depends(get_db),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    """به‌روزرسانی رمز عبور و خاتمه جریان بازنشانی."""
    session = get_session_from_request(request)
    if session:
        return RedirectResponse(url="/dashboard", status_code=302)

    reset_ctx = get_reset_context(request)
    if not reset_ctx:
        return RedirectResponse(url="/login", status_code=302)

    svc = _get_reset_service(db)
    reset_req = db.query(PasswordResetRequest).filter(
        PasswordResetRequest.id == reset_ctx["rid"]
    ).first()

    if not reset_req or reset_req.consumed_at:
        response = RedirectResponse(url="/login", status_code=302)
        clear_reset_cookie(response)
        return response

    user = db.query(User).filter(User.user_id == reset_req.user_id).first()
    employee = db.query(Employee).filter(
        Employee.user_id == reset_req.user_id
    ).first()

    # اعتبارسنجی‌های رمز عبور
    if new_password != confirm_password:
        return templates.TemplateResponse(request, "reset_password.html", {
            "error": "❌ رمز عبور جدید و تکرار آن یکسان نیستند",
        })

    if len(new_password) < 6:
        return templates.TemplateResponse(request, "reset_password.html", {
            "error": "❌ رمز عبور باید حداقل ۶ کاراکتر باشد",
        })

    if employee and employee.national_code and new_password == employee.national_code:
        return templates.TemplateResponse(request, "reset_password.html", {
            "error": "❌ رمز عبور نمی‌تواند کد ملی باشد",
        })

    # به‌روزرسانی کاربر
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()

    # مصرف درخواست بازنشانی
    svc.consume_request(reset_req)
    svc.invalidate_all_user_requests(reset_req.user_id)

    response = RedirectResponse(
        url="/login?msg=رمز عبور با موفقیت تغییر کرد. لطفاً وارد شوید.",
        status_code=303,
    )
    clear_reset_cookie(response)
    return response