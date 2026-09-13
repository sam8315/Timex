"""Dependency‌های FastAPI"""
from fastapi import Request, Depends, HTTPException
from sqlalchemy.orm import Session
from database.engine import SessionLocal
from web.session import get_session_from_request
from models.user import User
from models.employee import Employee
from web.services.announcement_service import get_unread_count


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """دریافت کاربر فعلی از Session"""
    session = get_session_from_request(request)
    if not session:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    user = db.query(User).filter(User.user_id == session["user_id"]).first()
    if not user or not user.web_enabled:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()
    user.display_name = employee.full_name if employee else (user.name or 'کاربر')
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """اجبار به نقش مدیر"""
    user = get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
    return user


def require_super_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """اجبار به نقش مدیر ارشد"""
    user = get_current_user(request, db)
    if not user.is_super_admin:
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز - فقط مدیر ارشد")
    return user


def check_password_change(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """بررسی نیاز به تغییر رمز و نمایش تازه‌های جدید هنگام ورود به داشبورد."""
    if user.must_change_password and request.url.path != "/change-password":
        raise HTTPException(status_code=307, headers={"Location": "/change-password"})
    if request.url.path == "/dashboard" and get_unread_count(db, user.user_id) > 0:
        raise HTTPException(status_code=303, headers={"Location": "/announcements"})
    return user
