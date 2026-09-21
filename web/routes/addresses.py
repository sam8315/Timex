"""
مدیریت آدرس‌های کاربر
"""
from datetime import date
from decimal import Decimal, InvalidOperation

import jdatetime
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from web.dependencies import get_db, get_current_user, require_admin
from models.user import User
from web.permissions import enforce_permission
from web.services.address_service import (
    AddressServiceError,
    list_addresses,
    get_address,
    create_address,
    update_address,
    delete_address,
    set_primary_address,
    get_primary_address,
)

router = APIRouter(tags=["Addresses"])


def _parse_decimal(value: str):
    """تبدیل رشته به Decimal"""
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        raise AddressServiceError("مقدار عددی نامعتبر است")


def _parse_date(value: str):
    """تبدیل رشته تاریخ به date (میلادی ISO یا شمسی YYYY/MM/DD).

    رشته خالی => None (فیلد اختیاری پاک می‌شود).
    فرمت شمسی (حاوی /) => تبدیل به میلادی.
    فرمت ISO (YYYY-MM-DD) => مستقیم.
    """
    if not value or not value.strip():
        return None
    text = value.strip()
    # شمسی: 1405/06/30
    if "/" in text:
        try:
            return jdatetime.datetime.strptime(text, "%Y/%m/%d").date().togregorian()
        except ValueError:
            raise AddressServiceError("فرمت تاریخ نامعتبر است (مثال: 1405/06/30)")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise AddressServiceError("فرمت تاریخ نامعتبر است (مثال: 1405/06/30)")


# ============================================
# بخش کاربر - مدیریت آدرس‌های خود
# ============================================

@router.post("/profile/addresses/add")
async def add_address(
    request: Request,
    address_type: str = Form(...),
    residence_status: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    district: str = Form(""),
    postal_code: str = Form(...),
    address_text: str = Form(...),
    is_primary: bool = Form(False),
    latitude: str = Form(""),
    longitude: str = Form(""),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    notes: str = Form(""),
    gnaf_id: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """افزودن آدرس جدید"""
    try:
        create_address(
            db=db,
            user_id=user.user_id,
            address_type=address_type,
            residence_status=residence_status,
            province=province,
            city=city,
            district=district or None,
            postal_code=postal_code,
            address_text=address_text,
            is_primary=is_primary,
            latitude=_parse_decimal(latitude),
            longitude=_parse_decimal(longitude),
            valid_from=_parse_date(valid_from),
            valid_to=_parse_date(valid_to),
            notes=notes or None,
            gnaf_id=gnaf_id or None,
        )
        return RedirectResponse(
            url="/profile?success=آدرس با موفقیت اضافه شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/profile?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/profile?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/profile/addresses/{address_id}/delete")
async def delete_own_address(
    request: Request,
    address_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """حذف آدرس کاربر"""
    try:
        delete_address(db, user.user_id, address_id)
        return RedirectResponse(
            url="/profile?success=آدرس حذف شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/profile?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/profile?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/profile/addresses/{address_id}/set-primary")
async def set_own_primary_address(
    request: Request,
    address_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تنظیم آدرس اصلی"""
    try:
        set_primary_address(db, user.user_id, address_id)
        return RedirectResponse(
            url="/profile?success=آدرس اصلی تنظیم شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/profile?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/profile?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/profile/addresses/{address_id}/update")
async def update_own_address(
    request: Request,
    address_id: int,
    address_type: str = Form(...),
    residence_status: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    district: str = Form(""),
    postal_code: str = Form(...),
    address_text: str = Form(...),
    is_primary: bool = Form(False),
    latitude: str = Form(""),
    longitude: str = Form(""),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    notes: str = Form(""),
    gnaf_id: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ویرایش آدرس کاربر (رشته خالی => پاک کردن فیلد اختیاری)"""
    try:
        update_address(
            db=db,
            user_id=user.user_id,
            address_id=address_id,
            address_type=address_type,
            residence_status=residence_status,
            province=province,
            city=city,
            district=district or None,
            postal_code=postal_code,
            address_text=address_text,
            latitude=_parse_decimal(latitude),
            longitude=_parse_decimal(longitude),
            valid_from=_parse_date(valid_from),
            valid_to=_parse_date(valid_to),
            notes=notes or None,
            gnaf_id=gnaf_id or None,
        )
        if is_primary:
            set_primary_address(db, user.user_id, address_id)
        return RedirectResponse(
            url="/profile?success=آدرس با موفقیت ویرایش شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/profile?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/profile?error=خطا: {str(e)}",
            status_code=302,
        )


# ============================================
# بخش ادمین - مدیریت آدرس‌های کاربران
# ============================================

@router.post("/admin/profile/{target_user_id}/addresses/add")
async def admin_add_address(
    request: Request,
    target_user_id: str,
    address_type: str = Form(...),
    residence_status: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    district: str = Form(""),
    postal_code: str = Form(...),
    address_text: str = Form(...),
    is_primary: bool = Form(False),
    latitude: str = Form(""),
    longitude: str = Form(""),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    notes: str = Form(""),
    gnaf_id: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """افزودن آدرس برای کاربر (توسط ادمین)"""
    enforce_permission(db, user, 'edit_profile')
    try:
        create_address(
            db=db,
            user_id=target_user_id,
            address_type=address_type,
            residence_status=residence_status,
            province=province,
            city=city,
            district=district or None,
            postal_code=postal_code,
            address_text=address_text,
            is_primary=is_primary,
            latitude=_parse_decimal(latitude),
            longitude=_parse_decimal(longitude),
            valid_from=_parse_date(valid_from),
            valid_to=_parse_date(valid_to),
            notes=notes or None,
            gnaf_id=gnaf_id or None,
        )
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=آدرس با موفقیت اضافه شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/admin/profile/{target_user_id}/addresses/{address_id}/delete")
async def admin_delete_address(
    request: Request,
    target_user_id: str,
    address_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """حذف آدرس کاربر (توسط ادمین)"""
    enforce_permission(db, user, 'edit_profile')
    try:
        delete_address(db, target_user_id, address_id)
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=آدرس حذف شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/admin/profile/{target_user_id}/addresses/{address_id}/set-primary")
async def admin_set_primary_address(
    request: Request,
    target_user_id: str,
    address_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """تنظیم آدرس اصلی کاربر (توسط ادمین)"""
    enforce_permission(db, user, 'edit_profile')
    try:
        set_primary_address(db, target_user_id, address_id)
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=آدرس اصلی تنظیم شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}",
            status_code=302,
        )


@router.post("/admin/profile/{target_user_id}/addresses/{address_id}/update")
async def admin_update_address(
    request: Request,
    target_user_id: str,
    address_id: int,
    address_type: str = Form(...),
    residence_status: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    district: str = Form(""),
    postal_code: str = Form(...),
    address_text: str = Form(...),
    is_primary: bool = Form(False),
    latitude: str = Form(""),
    longitude: str = Form(""),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    notes: str = Form(""),
    gnaf_id: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ویرایش آدرس کاربر (توسط ادمین)"""
    enforce_permission(db, user, 'edit_profile')
    try:
        # فرم ویرایش همیشه همه فیلدها را ارسال می‌کند؛
        # رشته خالی => پاک کردن فیلد اختیاری (None).
        update_address(
            db=db,
            user_id=target_user_id,
            address_id=address_id,
            address_type=address_type,
            residence_status=residence_status,
            province=province,
            city=city,
            district=district or None,
            postal_code=postal_code,
            address_text=address_text,
            latitude=_parse_decimal(latitude),
            longitude=_parse_decimal(longitude),
            valid_from=_parse_date(valid_from),
            valid_to=_parse_date(valid_to),
            notes=notes or None,
            gnaf_id=gnaf_id or None,
        )
        if is_primary:
            set_primary_address(db, target_user_id, address_id)
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?success=آدرس با موفقیت ویرایش شد",
            status_code=302,
        )
    except AddressServiceError as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error={str(e)}",
            status_code=302,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=خطا: {str(e)}",
            status_code=302,
        )
