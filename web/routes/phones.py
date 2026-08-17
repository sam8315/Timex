"""
مدیریت شماره‌های تلفن کاربر
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import re

from web.dependencies import get_db, get_current_user
from models.user import User
from models.employee_phone import EmployeePhone
from web.dependencies import get_db, get_current_user, require_admin  # 🆕 require_admin

router = APIRouter(tags=["Phones"])

# الگوی شماره موبایل ایرانی
IRAN_PHONE_PATTERN = re.compile(r'^09\d{9}$')


def normalize_phone(phone: str) -> str:
    """نرمال‌سازی شماره تلفن به فرمت 09121234567"""
    phone = phone.strip().replace(' ', '').replace('-', '')
    if phone.startswith('+98'):
        phone = '0' + phone[3:]
    elif phone.startswith('0098'):
        phone = '0' + phone[4:]
    elif phone.startswith('98') and len(phone) == 12:
        phone = '0' + phone[2:]
    return phone


def validate_phone(phone: str) -> bool:
    """اعتبارسنجی شماره موبایل ایرانی"""
    return bool(IRAN_PHONE_PATTERN.match(phone))


@router.post("/profile/phones/add")
async def add_phone(
        request: Request,
        phone_number: str = Form(...),
        label: str = Form("همراه"),
        is_default: bool = Form(False),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """افزودن شماره تلفن جدید"""
    try:
        # نرمال‌سازی و اعتبارسنجی
        normalized = normalize_phone(phone_number)
        if not validate_phone(normalized):
            return RedirectResponse(
                url="/profile?error=شماره تلفن نامعتبر است (مثال: 09121234567)",
                status_code=302
            )

        # بررسی تکراری نبودن
        existing = db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user.user_id,
            EmployeePhone.phone_number == normalized
        ).first()
        if existing:
            return RedirectResponse(
                url="/profile?error=این شماره قبلاً ثبت شده است",
                status_code=302
            )

        # اگر پیش‌فرض انتخاب شد، بقیه را غیر پیش‌فرض کن
        if is_default:
            db.query(EmployeePhone).filter(
                EmployeePhone.user_id == user.user_id
            ).update({EmployeePhone.is_default: False})

        # اگر اولین شماره است، به صورت خودکار پیش‌فرض باشد
        phone_count = db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user.user_id
        ).count()

        new_phone = EmployeePhone(
            user_id=user.user_id,
            phone_number=normalized,
            label=label,
            is_default=is_default or phone_count == 0
        )
        db.add(new_phone)
        db.commit()

        return RedirectResponse(
            url="/profile?success=شماره تلفن با موفقیت اضافه شد",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(url=f"/profile?error=خطا: {str(e)}", status_code=302)


@router.post("/profile/phones/{phone_id}/delete")
async def delete_phone(
        request: Request,
        phone_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """حذف شماره تلفن"""
    try:
        phone = db.query(EmployeePhone).filter(
            EmployeePhone.id == phone_id,
            EmployeePhone.user_id == user.user_id
        ).first()

        if not phone:
            return RedirectResponse(url="/profile?error=شماره یافت نشد", status_code=302)

        was_default = phone.is_default
        db.delete(phone)
        db.commit()

        # اگر شماره پیش‌فرض حذف شد، اولین شماره باقی‌مانده را پیش‌فرض کن
        if was_default:
            remaining = db.query(EmployeePhone).filter(
                EmployeePhone.user_id == user.user_id
            ).order_by(EmployeePhone.created_at).first()
            if remaining:
                remaining.is_default = True
                db.commit()

        return RedirectResponse(url="/profile?success=شماره تلفن حذف شد", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/profile?error=خطا: {str(e)}", status_code=302)


@router.post("/profile/phones/{phone_id}/set-default")
async def set_default_phone(
        request: Request,
        phone_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """تنظیم شماره پیش‌فرض"""
    try:
        phone = db.query(EmployeePhone).filter(
            EmployeePhone.id == phone_id,
            EmployeePhone.user_id == user.user_id
        ).first()

        if not phone:
            return RedirectResponse(url="/profile?error=شماره یافت نشد", status_code=302)

        # غیر پیش‌فرض کردن بقیه
        db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user.user_id
        ).update({EmployeePhone.is_default: False})

        phone.is_default = True
        db.commit()

        return RedirectResponse(url="/profile?success=شماره پیش‌فرض تنظیم شد", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/profile?error=خطا: {str(e)}", status_code=302)


# ============================================
# 🆕 بخش ادمین - مدیریت تلفن‌های کاربران
# ============================================

@router.post("/admin/profile/{target_user_id}/phones/add")
async def admin_add_phone(
        request: Request,
        target_user_id: str,
        phone_number: str = Form(...),
        label: str = Form("همراه"),
        is_default: bool = Form(False),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """افزودن شماره تلفن برای کاربر (توسط ادمین)"""
    try:
        # بررسی وجود کاربر
        from models.employee import Employee
        employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
        if not employee:
            return RedirectResponse(url="/admin/users?error=کاربر یافت نشد", status_code=302)

        # نرمال‌سازی و اعتبارسنجی
        normalized = normalize_phone(phone_number)
        if not validate_phone(normalized):
            return RedirectResponse(
                url=f"/admin/profile/{target_user_id}?error=شماره تلفن نامعتبر است (مثال: 09121234567)",
                status_code=302
            )

        # بررسی تکراری نبودن
        existing = db.query(EmployeePhone).filter(
            EmployeePhone.user_id == target_user_id,
            EmployeePhone.phone_number == normalized
        ).first()
        if existing:
            return RedirectResponse(
                url=f"/admin/profile/{target_user_id}?error=این شماره قبلاً ثبت شده است",
                status_code=302
            )

        # اگر پیش‌فرض انتخاب شد، بقیه را غیر پیش‌فرض کن
        if is_default:
            db.query(EmployeePhone).filter(
                EmployeePhone.user_id == target_user_id
            ).update({EmployeePhone.is_default: False})

        # اگر اولین شماره است، پیش‌فرض باشد
        phone_count = db.query(EmployeePhone).filter(
            EmployeePhone.user_id == target_user_id
        ).count()

        new_phone = EmployeePhone(
            user_id=target_user_id,
            phone_number=normalized,
            label=label,
            is_default=is_default or phone_count == 0
        )
        db.add(new_phone)
        db.commit()

        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=شماره تلفن با موفقیت اضافه شد",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}", status_code=302)


@router.post("/admin/profile/{target_user_id}/phones/{phone_id}/delete")
async def admin_delete_phone(
        request: Request,
        target_user_id: str,
        phone_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """حذف شماره تلفن کاربر (توسط ادمین)"""
    try:
        phone = db.query(EmployeePhone).filter(
            EmployeePhone.id == phone_id,
            EmployeePhone.user_id == target_user_id
        ).first()

        if not phone:
            return RedirectResponse(
                url=f"/admin/profile/{target_user_id}?error=شماره یافت نشد",
                status_code=302
            )

        was_default = phone.is_default
        db.delete(phone)
        db.commit()

        # اگر شماره پیش‌فرض حذف شد، اولین شماره باقی‌مانده را پیش‌فرض کن
        if was_default:
            remaining = db.query(EmployeePhone).filter(
                EmployeePhone.user_id == target_user_id
            ).order_by(EmployeePhone.created_at).first()
            if remaining:
                remaining.is_default = True
                db.commit()

        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=شماره تلفن حذف شد",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}", status_code=302)


@router.post("/admin/profile/{target_user_id}/phones/{phone_id}/set-default")
async def admin_set_default_phone(
        request: Request,
        target_user_id: str,
        phone_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تنظیم شماره پیش‌فرض کاربر (توسط ادمین)"""
    try:
        phone = db.query(EmployeePhone).filter(
            EmployeePhone.id == phone_id,
            EmployeePhone.user_id == target_user_id
        ).first()

        if not phone:
            return RedirectResponse(
                url=f"/admin/profile/{target_user_id}?error=شماره یافت نشد",
                status_code=302
            )

        # غیر پیش‌فرض کردن بقیه
        db.query(EmployeePhone).filter(
            EmployeePhone.user_id == target_user_id
        ).update({EmployeePhone.is_default: False})

        phone.is_default = True
        db.commit()

        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=شماره پیش‌فرض تنظیم شد",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}", status_code=302)