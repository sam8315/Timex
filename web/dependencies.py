"""Dependency‌های FastAPI"""
from fastapi import Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database.engine import SessionLocal
from web.session import get_session_from_request
from models.user import User


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

    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """اجبار به نقش مدیر"""
    user = get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
    return user


def check_password_change(request: Request, user: User = Depends(get_current_user)):
    """بررسی نیاز به تغییر رمز"""
    if user.must_change_password and request.url.path != "/change-password":
        raise HTTPException(status_code=307, headers={"Location": "/change-password"})
    return user