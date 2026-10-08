"""Dependency‌های FastAPI"""
from fastapi import Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database.engine import SessionLocal
from web.session import get_session_from_request
from models.user import User
from models.employee import Employee  # 🆕


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """دریافت کاربر فعلی از Session"""
    session = get_session_from_request(request)
    # #region agent log
    try:
        import json, time
        _p = r"d:\Projects\Timex\debug-cc9069.log"
        with open(_p, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({
                "sessionId": "cc9069", "runId": "pre-fix", "hypothesisId": "A,B",
                "location": "web/dependencies.py:get_current_user",
                "message": "auth check entry",
                "data": {
                    "path": str(request.url.path),
                    "has_session": bool(session),
                    "session_user_id": (session or {}).get("user_id"),
                    "has_cookie": bool(request.cookies.get("timex_session") or request.cookies),
                    "cookie_keys": list(request.cookies.keys())[:8],
                },
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
    if not session:
        # #region agent log
        try:
            import json, time
            with open(r"d:\Projects\Timex\debug-cc9069.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "sessionId": "cc9069", "runId": "pre-fix", "hypothesisId": "B",
                    "location": "web/dependencies.py:get_current_user:no_session",
                    "message": "redirect login: no session",
                    "data": {"path": str(request.url.path)},
                    "timestamp": int(time.time() * 1000),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion
        raise HTTPException(status_code=307, headers={"Location": "/login"})

    user = db.query(User).filter(User.user_id == session["user_id"]).first()
    if not user or not user.web_enabled:
        # #region agent log
        try:
            import json, time
            with open(r"d:\Projects\Timex\debug-cc9069.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "sessionId": "cc9069", "runId": "pre-fix", "hypothesisId": "A",
                    "location": "web/dependencies.py:get_current_user:bad_user",
                    "message": "redirect login: user missing or web disabled",
                    "data": {
                        "path": str(request.url.path),
                        "session_user_id": session.get("user_id"),
                        "user_found": bool(user),
                        "web_enabled": bool(user.web_enabled) if user else None,
                    },
                    "timestamp": int(time.time() * 1000),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion
        raise HTTPException(status_code=307, headers={"Location": "/login"})
        # 🆕 اضافه کردن نام کامل از جدول Employee
    if user:
        employee = db.query(Employee).filter(
            Employee.user_id == user.user_id
        ).first()
        # ذخیره نام کامل به صورت ویژگی پویا
        user.display_name = employee.full_name if employee else (user.name or 'کاربر')
        from web.permissions import get_effective_permissions
        user.effective_permissions = get_effective_permissions(db, user)

    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """ورود به بخش مدیریت: کاربر حداقل یک دسترسی مؤثر داشته باشد."""
    user = get_current_user(request, db)
    if not user.effective_permissions:
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
    return user


def require_permission(permission: str):
    """گیت یک دسترسی مشخص از کاتالوگ."""
    def _require(request: Request, db: Session = Depends(get_db)) -> User:
        from web.permissions import enforce_permission

        user = get_current_user(request, db)
        enforce_permission(db, user, permission)
        return user

    return _require


def require_super_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """سازگاری: مدیریت دسترسی‌ها. گیت نام نقش نیست."""
    return require_permission("manage_permissions")(request, db)


def check_password_change(request: Request, user: User = Depends(get_current_user)):
    """بررسی نیاز به تغییر رمز"""
    # #region agent log
    try:
        import json, time
        with open(r"d:\Projects\Timex\debug-cc9069.log", "a", encoding="utf-8") as _f:
            _f.write(json.dumps({
                "sessionId": "cc9069", "runId": "pre-fix", "hypothesisId": "C,D",
                "location": "web/dependencies.py:check_password_change",
                "message": "password-change gate",
                "data": {
                    "path": str(request.url.path),
                    "user_id": getattr(user, "user_id", None),
                    "must_change_password": bool(getattr(user, "must_change_password", False)),
                    "has_display_name": hasattr(user, "display_name"),
                },
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
    if user.must_change_password and request.url.path != "/change-password":
        raise HTTPException(status_code=307, headers={"Location": "/change-password"})
        # 🆕 اگر از قبل اضافه نشده
    if user and not hasattr(user, 'display_name'):
        # #region agent log
        try:
            import json, time
            with open(r"d:\Projects\Timex\debug-cc9069.log", "a", encoding="utf-8") as _f:
                _f.write(json.dumps({
                    "sessionId": "cc9069", "runId": "pre-fix", "hypothesisId": "C",
                    "location": "web/dependencies.py:check_password_change:display_name_branch",
                    "message": "entering display_name branch (uses undefined db?)",
                    "data": {"path": str(request.url.path)},
                    "timestamp": int(time.time() * 1000),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion
        employee = db.query(Employee).filter(
            Employee.user_id == user.user_id
        ).first()
        user.display_name = employee.full_name if employee else (user.name or 'کاربر')

    return user