"""
مدیریت متمرکز خطاهای HTTP

قواعد:
- 403 برای درخواست صفحه وب (HTML) → صفحه ۴۰۳ اختصاصی و هماهنگ با قالب پنل
- 403 برای درخواست API/JSON → پاسخ JSON (بدون تبدیل به HTML)
- سایر کدها (۴۰۴، ۳۰۷ و ...) → رفتار پیش‌فرض FastAPI:
    JSONResponse با حفظ هدرهای exception (مثلاً Location در ریدایرکت ۳۰۷ به /login)،
    و پاسخ بدون بدنه برای status‌هایی که body ندارند (204/304).
  (رفتار پیش‌فرض FastAPI از روی fastapi/exception_handlers.py بازتولید شده است.)

هیچ اطلاعات حساسی (مسیر، نقش، دسترسی، توکن، traceback) به کاربر نمایش داده نمی‌شود.
"""
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _wants_html(request: Request) -> bool:
    """تفکیک درخواست صفحه وب از API بر اساس مسیر و هدر Accept."""
    if request.url.path.startswith("/api/"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _resolve_current_user(request: Request):
    """یافتن کاربر جاری برای رندر درست سایدبار/توپبار.

    اگر نشست یا کاربر موجود نباشد، یا هر خطای دیتابیس رخ دهد،
    (None, False, False) برمی‌گرداند تا صفحه ۴۰۳ همیشه بدون شکست رندر شود.
    """
    try:
        from web.session import get_session_from_request
        from database.engine import SessionLocal
        from models.user import User
        from models.employee import Employee

        session = get_session_from_request(request)
        if not session:
            return None, False, False

        db = SessionLocal()
        try:
            user = db.query(User).filter(
                User.user_id == session["user_id"]
            ).first()
            if not user or not user.web_enabled:
                return None, False, False

            emp = db.query(Employee).filter(
                Employee.user_id == user.user_id
            ).first()
            user.display_name = emp.full_name if emp else (user.name or "کاربر")
            return user, bool(user.is_admin), bool(user.is_super_admin)
        finally:
            db.close()
    except Exception:
        return None, False, False


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """هندلر سراسری HTTPException."""
    if exc.status_code == 403 and _wants_html(request):
        user, is_admin, is_super_admin = _resolve_current_user(request)
        return TEMPLATES.TemplateResponse(
            request,
            "403.html",
            {
                "user": user,
                "is_admin": is_admin,
                "is_super_admin": is_super_admin,
            },
            status_code=403,
        )

    # سایر موارد: رفتار پیش‌فرض FastAPI (مطابق fastapi.exception_handlers.http_exception_handler)
    if not is_body_allowed_for_status_code(exc.status_code):
        # 204/304 و مشابه: پاسخ بدون بدنه، بدون content-type JSON
        return Response(status_code=exc.status_code, headers=exc.headers)
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
