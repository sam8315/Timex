"""ایجاد کاربر + پروفایل کارمند (فرم ترکیبی اتمیک)."""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from web.dependencies import get_db, require_super_admin
from models.user import User
from models.employee import Employee
from web.security import hash_password
from web.session import make_csrf_token, check_csrf_token
import jdatetime

router = APIRouter(tags=["Admin User Create"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

REGION_OPTIONS = [
    {"code": "NORMAL", "label": "عادی"},
    {"code": "GRADE_1", "label": "درجه یک"},
    {"code": "GRADE_2", "label": "درجه دو"},
    {"code": "GRADE_3", "label": "درجه سه"},
]


def _j_to_g(date_str: str):
    """تبدیل تاریخ شمسی (YYYY/MM/DD) به میلادی — همان فرمت edit_user.html."""
    if not date_str or not date_str.strip():
        return None
    return jdatetime.datetime.strptime(date_str.strip(), "%Y/%m/%d").date().togregorian()


@router.get("/admin/users/create", response_class=HTMLResponse)
async def create_user_form(
    request: Request,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """نمایش فرم ایجاد کاربر + کارمند (فقط سوپرادمین)."""
    return templates.TemplateResponse(request, "admin/create_user.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "csrf_token": make_csrf_token(user.user_id),
        "region_options": REGION_OPTIONS,
        "error": None,
        "form": {},
    })


@router.post("/admin/users/create")
async def create_user_submit(
    request: Request,
    user_id: str = Form(""),
    name: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date_str: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    email: str = Form(""),
    hire_date_str: str = Form(""),
    department: str = Form(""),
    position: str = Form(""),
    region_code: str = Form("NORMAL"),
    notes: str = Form(""),
    is_active: str = Form("on"),
    csrf_token: str = Form(""),
    cur_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """ایجاد ترکیبی User + Employee در یک تراکنش اتمیک."""
    if not check_csrf_token(csrf_token, cur_user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")

    # ── مقادیر پاک‌شده ──
    uid = user_id.strip()
    uname = name.strip()
    fn = first_name.strip()
    ln = last_name.strip()
    nc = national_code.strip()

    # ── اعتبارسنجی ──
    # user_id: ۱ تا ۵۰ کاراکتر، فقط حروف، عدد، _ و -
    if not uid or len(uid) > 50:
        return _form_response(request, cur_user, "شناسه کاربری باید ۱ تا ۵۰ کاراکتر باشد.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)
    if not all(c.isalnum() or c in "_-" for c in uid):
        return _form_response(request, cur_user, "شناسه کاربری فقط حروف، عدد، زیرخط و خط تیره مجاز است.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    # national_code: دقیقاً ۱۰ رقم
    if not nc or len(nc) != 10 or not nc.isdigit():
        return _form_response(request, cur_user, "کد ملی باید دقیقاً ۱۰ رقم باشد.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    # نام و نام خانوادگی الزامی
    if not fn:
        return _form_response(request, cur_user, "نام الزامی است.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)
    if not ln:
        return _form_response(request, cur_user, "نام خانوادگی الزامی است.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    # تکراری: user_id
    if db.query(User).filter(User.user_id == uid).first():
        return _form_response(request, cur_user, "این شناسه کاربری قبلاً ثبت شده است.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    # تکراری: national_code
    if db.query(Employee).filter(Employee.national_code == nc).first():
        return _form_response(request, cur_user, "این کد ملی قبلاً ثبت شده است.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    # ── ایجاد اتمیک ──
    try:
        new_user = User(
            user_id=uid,
            name=uname or f"{fn} {ln}",
            password_hash=hash_password(nc),
            must_change_password=True,
            role="user",
            web_enabled=True,
            privilege=0,
        )
        db.add(new_user)

        birth = _j_to_g(birth_date_str)
        hire = _j_to_g(hire_date_str)
        emp = Employee(
            user_id=uid,
            first_name=fn,
            last_name=ln,
            father_name=father_name.strip() or None,
            national_code=nc,
            gender=gender or None,
            marital_status=marital_status or None,
            email=email.strip() or None,
            department=department.strip() or None,
            position=position.strip() or None,
            region_code=region_code or "NORMAL",
            notes=notes.strip() or None,
            is_active=(is_active == "on"),
        )
        if birth:
            emp.birth_date = birth
        if hire:
            emp.hire_date = hire
        db.add(emp)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _form_response(request, cur_user, "خطای یکپارچگی: ممکن است این شناسه یا کد ملی هم‌اکنون ثبت شده باشد.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)
    except Exception:
        db.rollback()
        return _form_response(request, cur_user, "خطای سرور هنگام ایجاد کاربر. لطفاً دوباره تلاش کنید.",
                              uid, uname, fn, ln, nc, father_name, birth_date_str,
                              gender, marital_status, email, hire_date_str, department,
                              position, region_code, notes)

    return RedirectResponse(url=f"/admin/profile/{uid}?created=1", status_code=302)


def _form_response(request, cur_user, error,
                   uid="", uname="", fn="", ln="", nc="",
                   father_name="", birth_date_str="", gender="",
                   marital_status="", email="", hire_date_str="",
                   department="", position="", region_code="NORMAL", notes=""):
    """رندر مجدد فرم با پیام خطا و مقادیر قبلی."""
    return templates.TemplateResponse(request, "admin/create_user.html", {
        "user": cur_user,
        "is_admin": True,
        "is_super_admin": True,
        "csrf_token": make_csrf_token(cur_user.user_id),
        "region_options": REGION_OPTIONS,
        "error": error,
        "form": {
            "user_id": uid,
            "name": uname,
            "first_name": fn,
            "last_name": ln,
            "father_name": father_name,
            "national_code": nc,
            "birth_date_str": birth_date_str,
            "gender": gender,
            "marital_status": marital_status,
            "email": email,
            "hire_date_str": hire_date_str,
            "department": department,
            "position": position,
            "region_code": region_code,
            "notes": notes,
        },
    })