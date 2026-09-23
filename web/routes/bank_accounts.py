"""
مدیریت حساب‌های بانکی کاربر (بخش کاربر و ادمین)

لایه نازک: فقط auth/permission + فراخوانی BankAccountService.
قوانین کسب‌وکار (Primary، کارت/شبا، verification) در سرویس می‌مانند.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from models.employee_bank_account import EmployeeBankAccount
from models.user import User
from web.dependencies import get_current_user, get_db, require_admin
from web.permissions import enforce_permission
from web.services.bank_account_service import (
    BankAccountServiceError,
    change_verification_status,
    create_bank_account,
    delete_bank_account,
    get_bank_account,
    list_bank_accounts,
    set_active_bank_account,
    set_primary_bank_account,
    update_bank_account,
)

router = APIRouter(tags=["Bank Accounts"])


def _account_json(acc: EmployeeBankAccount) -> Dict[str, Any]:
    """پاسخ صریح (بدانلود مستقیم مدل ORM) مطابق دیکشنری‌های دستی OTP/گزارش."""
    return {
        "id": acc.id,
        "user_id": acc.user_id,
        "bank_id": acc.bank_id,
        "bank_name": acc.bank_name,
        "branch_name": acc.branch_name,
        "branch_code": acc.branch_code,
        "account_number": acc.account_number,
        "card_number": acc.card_number,
        "sheba": acc.sheba,
        "account_type": acc.account_type,
        "account_title": acc.account_title,
        "description": acc.description,
        "is_primary": acc.is_primary,
        "is_active": acc.is_active,
        "verification_status": acc.verification_status,
        "verified_at": acc.verified_at.isoformat() if acc.verified_at else None,
        "verified_by": acc.verified_by,
        "verification_note": acc.verification_note,
    }


def _opt(value: Optional[str]) -> Optional[str]:
    """رشته فرم خالی => None (پاک‌کردن فیلد اختیاری)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=302)


def _service_redirect(base: str, success: str, exc: Exception) -> RedirectResponse:
    if isinstance(exc, BankAccountServiceError):
        return _redirect(f"{base}?error={exc}")
    return _redirect(f"{base}?error=خطا: {exc}")


# ============================================
# بخش کاربر - حساب‌های بانکی خود
# ============================================

@router.get("/profile/bank-accounts")
async def list_own_bank_accounts(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """لیست حساب‌های بانکی کاربر فعلی"""
    try:
        accounts = list_bank_accounts(db, user.user_id)
        return [_account_json(a) for a in accounts]
    except BankAccountServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/profile/bank-accounts/{account_id}")
async def get_own_bank_account(
    request: Request,
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """دریافت یک حساب بانکی کاربر فعلی (scoped به کاربر)"""
    try:
        acc = get_bank_account(db, user.user_id, account_id)
        return _account_json(acc)
    except BankAccountServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/profile/bank-accounts/add")
async def add_own_bank_account(
    request: Request,
    bank_id: str = Form(...),
    account_number: str = Form(...),
    branch_name: str = Form(""),
    branch_code: str = Form(""),
    card_number: str = Form(""),
    sheba: str = Form(""),
    account_type: str = Form(""),
    account_title: str = Form(""),
    description: str = Form(""),
    is_primary: bool = Form(False),
    is_active: bool = Form(True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """افزودن حساب بانکی جدید"""
    base = "/profile"
    try:
        create_bank_account(
            db=db,
            user_id=user.user_id,
            bank_id=bank_id,
            account_number=account_number,
            branch_name=_opt(branch_name),
            branch_code=_opt(branch_code),
            card_number=_opt(card_number),
            sheba=_opt(sheba),
            account_type=_opt(account_type),
            account_title=_opt(account_title),
            description=_opt(description),
            is_primary=is_primary,
            is_active=is_active,
        )
        return _redirect(f"{base}?success=حساب بانکی با موفقیت اضافه شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/profile/bank-accounts/{account_id}/update")
async def update_own_bank_account(
    request: Request,
    account_id: int,
    bank_id: str = Form(""),
    account_number: str = Form(""),
    branch_name: str = Form(""),
    branch_code: str = Form(""),
    card_number: str = Form(""),
    sheba: str = Form(""),
    account_type: str = Form(""),
    account_title: str = Form(""),
    description: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ویرایش حساب بانکی کاربر (رشته خالی فیلد اختیاری => پاک‌کردن)"""
    base = "/profile"
    try:
        kwargs: Dict[str, Any] = {}
        if bank_id.strip():
            kwargs["bank_id"] = bank_id.strip()
        if account_number.strip():
            kwargs["account_number"] = account_number.strip()
        # فیلدهای اختیاری فقط وقتی در فرم آمده‌اند اعمال می‌شوند
        form = await request.form()
        optional_fields = (
            "branch_name", "branch_code", "card_number", "sheba",
            "account_type", "account_title", "description",
        )
        for field in optional_fields:
            if field in form:
                kwargs[field] = _opt(form.get(field))
        update_bank_account(
            db=db,
            user_id=user.user_id,
            account_id=account_id,
            **kwargs,
        )
        return _redirect(f"{base}?success=حساب بانکی با موفقیت ویرایش شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/profile/bank-accounts/{account_id}/delete")
async def delete_own_bank_account(
    request: Request,
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """حذف حساب بانکی کاربر"""
    base = "/profile"
    try:
        delete_bank_account(db, user.user_id, account_id)
        return _redirect(f"{base}?success=حساب بانکی حذف شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/profile/bank-accounts/{account_id}/set-primary")
async def set_primary_own_bank_account(
    request: Request,
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تنظیم حساب بانکی اصلی"""
    base = "/profile"
    try:
        set_primary_bank_account(db, user.user_id, account_id)
        return _redirect(f"{base}?success=حساب بانکی اصلی تنظیم شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/profile/bank-accounts/{account_id}/set-active")
async def set_active_own_bank_account(
    request: Request,
    account_id: int,
    active: bool = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """فعال/غیرفعال کردن حساب بانکی"""
    base = "/profile"
    try:
        set_active_bank_account(db, user.user_id, account_id, active)
        if active:
            return _redirect(f"{base}?success=حساب بانکی فعال شد")
        return _redirect(f"{base}?success=حساب بانکی غیرفعال شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/profile/bank-accounts/{account_id}/verification")
async def change_own_bank_verification(
    request: Request,
    account_id: int,
    status: str = Form(...),
    note: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """تغییر وضعیت تأیید سازمانی حساب کاربر فعلی

    تأیید سازمانی فقط از مسیر مجوز edit_profile (همانند مسیر ادمین)؛
    کاربر عادی نمی‌تواند حساب خود را verified/rejected کند.
    """
    enforce_permission(db, user, "edit_profile")
    base = "/profile"
    try:
        change_verification_status(
            db,
            user.user_id,
            account_id,
            status,
            changed_by=user.user_id,
            note=_opt(note),
        )
        return _redirect(f"{base}?success=وضعیت تأیید حساب بانکی به‌روزرسانی شد")
    except Exception as e:
        return _service_redirect(base, "", e)


# ============================================
# بخش ادمین - حساب‌های بانکی کاربران
# ============================================

@router.get("/admin/profile/{target_user_id}/bank-accounts")
async def admin_list_bank_accounts(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """لیست حساب‌های بانکی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    try:
        accounts = list_bank_accounts(db, target_user_id)
        return [_account_json(a) for a in accounts]
    except BankAccountServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/admin/profile/{target_user_id}/bank-accounts/{account_id}")
async def admin_get_bank_account(
    request: Request,
    target_user_id: str,
    account_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """دریافت یک حساب بانکی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    try:
        acc = get_bank_account(db, target_user_id, account_id)
        return _account_json(acc)
    except BankAccountServiceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/profile/{target_user_id}/bank-accounts/add")
async def admin_add_bank_account(
    request: Request,
    target_user_id: str,
    bank_id: str = Form(...),
    account_number: str = Form(...),
    branch_name: str = Form(""),
    branch_code: str = Form(""),
    card_number: str = Form(""),
    sheba: str = Form(""),
    account_type: str = Form(""),
    account_title: str = Form(""),
    description: str = Form(""),
    is_primary: bool = Form(False),
    is_active: bool = Form(True),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """افزودن حساب بانکی برای کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        create_bank_account(
            db=db,
            user_id=target_user_id,
            bank_id=bank_id,
            account_number=account_number,
            branch_name=_opt(branch_name),
            branch_code=_opt(branch_code),
            card_number=_opt(card_number),
            sheba=_opt(sheba),
            account_type=_opt(account_type),
            account_title=_opt(account_title),
            description=_opt(description),
            is_primary=is_primary,
            is_active=is_active,
        )
        return _redirect(f"{base}?success=حساب بانکی با موفقیت اضافه شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/admin/profile/{target_user_id}/bank-accounts/{account_id}/update")
async def admin_update_bank_account(
    request: Request,
    target_user_id: str,
    account_id: int,
    bank_id: str = Form(""),
    account_number: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ویرایش حساب بانکی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        kwargs: Dict[str, Any] = {}
        if bank_id.strip():
            kwargs["bank_id"] = bank_id.strip()
        if account_number.strip():
            kwargs["account_number"] = account_number.strip()
        form = await request.form()
        optional_fields = (
            "branch_name", "branch_code", "card_number", "sheba",
            "account_type", "account_title", "description",
        )
        for field in optional_fields:
            if field in form:
                kwargs[field] = _opt(form.get(field))
        update_bank_account(
            db=db,
            user_id=target_user_id,
            account_id=account_id,
            **kwargs,
        )
        return _redirect(f"{base}?success=حساب بانکی با موفقیت ویرایش شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/admin/profile/{target_user_id}/bank-accounts/{account_id}/delete")
async def admin_delete_bank_account(
    request: Request,
    target_user_id: str,
    account_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """حذف حساب بانکی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        delete_bank_account(db, target_user_id, account_id)
        return _redirect(f"{base}?success=حساب بانکی حذف شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/admin/profile/{target_user_id}/bank-accounts/{account_id}/set-primary")
async def admin_set_primary_bank_account(
    request: Request,
    target_user_id: str,
    account_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """تنظیم حساب بانکی اصلی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        set_primary_bank_account(db, target_user_id, account_id)
        return _redirect(f"{base}?success=حساب بانکی اصلی تنظیم شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/admin/profile/{target_user_id}/bank-accounts/{account_id}/set-active")
async def admin_set_active_bank_account(
    request: Request,
    target_user_id: str,
    account_id: int,
    active: bool = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """فعال/غیرفعال کردن حساب بانکی کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        set_active_bank_account(db, target_user_id, account_id, active)
        if active:
            return _redirect(f"{base}?success=حساب بانکی فعال شد")
        return _redirect(f"{base}?success=حساب بانکی غیرفعال شد")
    except Exception as e:
        return _service_redirect(base, "", e)


@router.post("/admin/profile/{target_user_id}/bank-accounts/{account_id}/verification")
async def admin_change_bank_verification(
    request: Request,
    target_user_id: str,
    account_id: int,
    status: str = Form(...),
    note: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """تغییر وضعیت تأیید سازمانی حساب کاربر (توسط ادمین)"""
    enforce_permission(db, user, "edit_profile")
    base = f"/admin/profile/{target_user_id}"
    try:
        change_verification_status(
            db,
            target_user_id,
            account_id,
            status,
            changed_by=user.user_id,
            note=_opt(note),
        )
        return _redirect(f"{base}?success=وضعیت تأیید حساب بانکی به‌روزرسانی شد")
    except Exception as e:
        return _service_redirect(base, "", e)
