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


# ============================================
# 🔐 تأیید شماره با کد یکبار مصرف (OTP)
# ============================================
import random
from datetime import datetime, timedelta
from fastapi import Form
from core.sms_service import SmsService

# 🆕 ذخیره‌سازی موقت کدها در حافظه
# ساختار: {phone: {'code': '123456', 'user_id': '...', 'expires_at': datetime}}
otp_store = {}

# ⏱️ مدت اعتبار کد (دقیقه)
OTP_EXPIRY_MINUTES = 5


def _normalize_phone(phone: str) -> str:
    """نرمال‌سازی شماره موبایل ایرانی"""
    phone = phone.strip().replace(' ', '').replace('-', '')
    phone = phone.replace('+98', '0').replace('98', '0', 1)
    if not phone.startswith('0') and len(phone) == 10:
        phone = '0' + phone
    return phone


def _generate_otp() -> str:
    """تولید کد ۶ رقمی تصادفی"""
    return ''.join(random.choices('0123456789', k=6))


@router.post("/profile/phones/send-otp")
async def send_phone_otp(
    request: Request,
    phone_number: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🆕 ارسال کد یکبار مصرف به شماره"""
    try:
        phone = _normalize_phone(phone_number)

        # اعتبارسنجی شماره
        if not phone.startswith('09') or len(phone) != 11 or not phone.isdigit():
            return {"success": False, "message": "شماره موبایل نامعتبر است"}

        # بررسی تکراری نبودن
        existing = db.query(EmployeePhone).filter(
            EmployeePhone.phone_number == phone
        ).first()
        if existing:
            if existing.user_id == user.user_id:
                return {"success": False, "message": "این شماره قبلاً برای شما ثبت شده است"}
            return {"success": False, "message": "این شماره برای کاربر دیگری ثبت شده است"}

        # 🆕 محدودیت ارسال: هر شماره حداکثر یک بار در دقیقه
        existing_otp = otp_store.get(phone)
        if existing_otp:
            sent_at = existing_otp.get('sent_at')
            if sent_at and (datetime.now() - sent_at).total_seconds() < 60:
                remaining = 60 - int((datetime.now() - sent_at).total_seconds())
                return {"success": False, "message": f"لطفاً {remaining} ثانیه صبر کنید"}

        # تولید کد
        otp_code = _generate_otp()

        # ذخیره در حافظه
        otp_store[phone] = {
            'code': otp_code,
            'user_id': user.user_id,
            'expires_at': datetime.now() + timedelta(minutes=OTP_EXPIRY_MINUTES),
            'sent_at': datetime.now(),
            'attempts': 0
        }

        # ارسال پیامک
        sms = SmsService()
        message = (
            f"🔐 کد تأیید شما: {otp_code}\n"
            f"این کد تا {OTP_EXPIRY_MINUTES} دقیقه معتبر است.\n"
            f"سامانه حضور و غیاب"
        )
        sms_result = sms.send_sms([phone], message)

        if not sms_result.get('success'):
            # اگر ارسال پیامک ناموفق بود، کد را در کنسول نمایش بده (برای تست)
            print(f"⚠️ ارسال پیامک ناموفق بود. کد تأیید {user.user_id}: {otp_code}")
            return {
                "success": False,
                "message": "خطا در ارسال پیامک. لطفاً دوباره تلاش کنید."
            }

        return {
            "success": True,
            "message": f"کد تأیید به شماره {phone} ارسال شد"
        }

    except Exception as e:
        return {"success": False, "message": f"خطا: {str(e)}"}


@router.post("/profile/phones/verify-otp")
async def verify_phone_otp(
    request: Request,
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    label: str = Form(""),
    is_default: str = Form("off"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🆕 تأیید کد و ذخیره شماره"""
    try:
        phone = _normalize_phone(phone_number)
        otp_data = otp_store.get(phone)

        # بررسی وجود کد
        if not otp_data:
            return {"success": False, "message": "کد تأییدی ارسال نشده است"}

        # بررسی مالکیت کد
        if otp_data['user_id'] != user.user_id:
            return {"success": False, "message": "این کد برای شما نیست"}

        # بررسی انقضا
        if datetime.now() > otp_data['expires_at']:
            del otp_store[phone]
            return {"success": False, "message": "کد تأیید منقضی شده است"}

        # بررسی تعداد تلاش‌ها (حداکثر ۵ بار)
        if otp_data['attempts'] >= 5:
            del otp_store[phone]
            return {"success": False, "message": "تعداد تلاش‌ها بیش از حد مجاز است"}

        # بررسی کد
        if otp_data['code'] != otp_code.strip():
            otp_data['attempts'] += 1
            remaining = 5 - otp_data['attempts']
            return {"success": False, "message": f"کد تأیید نادرست است ({remaining} تلاش باقی مانده)"}

        # ✅ کد درست است → ذخیره شماره
        new_phone = EmployeePhone(
            user_id=user.user_id,
            phone_number=phone,
            label=label.strip() or None,
            is_default=(is_default == "on")
        )

        # اگر این شماره پیش‌فرض است، سایر شماره‌ها را از حالت پیش‌فرض خارج کن
        if is_default == "on":
            db.query(EmployeePhone).filter(
                EmployeePhone.user_id == user.user_id,
                EmployeePhone.is_default == True
            ).update({"is_default": False})

        db.add(new_phone)
        db.commit()

        # حذف کد از حافظه
        del otp_store[phone]

        return {"success": True, "message": "شماره با موفقیت اضافه شد"}

    except Exception as e:
        db.rollback()
        return {"success": False, "message": f"خطا: {str(e)}"}