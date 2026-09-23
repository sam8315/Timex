"""
سرویس مدیریت حساب‌های بانکی کارمندان

الگو: مشابه address_service.py
- اعتبارسنجی خالص (بدون دسترسی دیتابیس) از تغییر داده جداست
- تغییرات در یک تراکنش commit می‌شوند
- is_primary با الگوی demote-اول-سپس-promote مدیریت می‌شود؛ ایندکس جزئی
  دیتابیس (user_id WHERE is_primary AND is_active) شبکه ایمنی نهایی است
- اعتبارسنجی الگوریتمی محلی کارت (Luhn) و شبا (MOD-97) در create/update
  اعمال می‌شود و کاملاً از تأیید سازمانی (verification_status) جداست؛
  هیچ‌کدام از فیلدهای تأیید را تغییر نمی‌دهند
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session

from models.bank import Bank
from models.employee_bank_account import (
    EmployeeBankAccount, VERIFICATION_STATUSES,
)
from models.user import User


# ---------------------------------------------------------------------------
# Sentinel: distinguishes "field not provided" from "explicitly set to None"
# ---------------------------------------------------------------------------
_UNSET = object()

logger = logging.getLogger(__name__)

# نگاشت ارقام فارسی و عربی به ارقام ASCII (همانند address_service)
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class BankAccountServiceError(Exception):
    """خطای سرویس حساب بانکی"""
    pass


def _validate_user_exists(db: Session, user_id: str) -> None:
    """بررسی وجود کاربر"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise BankAccountServiceError("کاربر یافت نشد")


def _validate_required_text(value, field_label: str) -> str:
    """اعتبارسنجی فیلد متنی الزامی (مطابق NOT NULL دیتابیس)."""
    if value is None or not str(value).strip():
        raise BankAccountServiceError(f"{field_label} نمی‌تواند خالی باشد")
    return str(value).strip()


def _normalize_optional_text(value) -> Optional[str]:
    """نرمال‌سازی فیلد اختیاری: None/خالی => None، حلقه اطراف حذف."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _luhn_ok(digits: str) -> bool:
    """اعتبارسنجی چک‌سام Luhn (MOD-10) روی رشته ارقام ASCII."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _validate_card_number(card_number) -> str:
    """اعتبارسنجی الگوریتمی شماره کارت بانکی ایرانی (محلی، بدون API).

    - ارقام فارسی/عربی به ASCII تبدیل می‌شوند (الگوی address_service)
    - فقط فاصله و خط تیرهٔ فرمت‌دهی حذف می‌شوند (الگوی phones.normalize_phone)
    - پس از نرمال‌سازی باید دقیقاً ۱۶ رقم ASCII باشد؛ صفرهای ابتدایی حفظ می‌شوند
    - چک‌سام Luhn بررسی می‌شود؛ شمارهٔ تمام‌صفر رد می‌شود
    - صحت مالکیت کارت بررسی نمی‌شود؛ فیلدهای verification تغییر نمی‌کنند
    """
    if card_number is None or not str(card_number).strip():
        raise BankAccountServiceError("شماره کارت نمی‌تواند خالی باشد")
    normalized = (
        str(card_number)
        .translate(_DIGIT_TRANSLATION)
        .strip()
        .replace(" ", "")
        .replace("-", "")
    )
    if not re.fullmatch(r"[0-9]{16}", normalized):
        raise BankAccountServiceError("شماره کارت باید دقیقاً ۱۶ رقم عددی باشد")
    if normalized == "0" * 16:
        raise BankAccountServiceError("شماره کارت نامعتبر است (چک‌سام نادرست)")
    if not _luhn_ok(normalized):
        raise BankAccountServiceError("شماره کارت نامعتبر است (چک‌سام نادرست)")
    return normalized


def _validate_sheba(sheba) -> str:
    """اعتبارسنجی الگوریتمی شماره شبا/IBAN ایرانی (محلی، بدون API).

    - ارقام فارسی/عربی به ASCII تبدیل می‌شوند
    - فاصله‌های فرمت‌دهی حذف می‌شوند؛ پیشوند کشور به شکل IR (بزرگ) نرمال می‌شود
    - ساختار: IR + ۲۴ رقم (طول کل ۲۶) — استاندارد IBAN ایران
    - چک‌سام MOD-97 بررسی می‌شود
    - رشته ذخیره‌شده رشته می‌ماند (صفرهای ابتدایی حفظ)؛ بدون API خارجی
    - مالکیت حساب/بانک بررسی نمی‌شود؛ فیلدهای verification تغییر نمی‌کنند
    """
    if sheba is None or not str(sheba).strip():
        raise BankAccountServiceError("شماره شبا نمی‌تواند خالی باشد")
    normalized = (
        str(sheba)
        .translate(_DIGIT_TRANSLATION)
        .strip()
        .replace(" ", "")
        .upper()
    )
    if not normalized.startswith("IR"):
        raise BankAccountServiceError("شماره شبا باید با پیشوند IR شروع شود")

    body = normalized[2:]
    if not re.fullmatch(r"[0-9]{24}", body):
        raise BankAccountServiceError(
            "شماره شبا باید پس از IR دقیقاً ۲۴ رقم عددی باشد"
        )

    # IBAN MOD-97: چهار کاراکتر اول (IR + چک‌دیجیت) به انتها منتقل می‌شوند
    full = "IR" + body
    rearranged = full[4:] + full[:4]
    numeric = "".join(
        ch if ch.isdigit() else str(ord(ch) - ord("A") + 10)
        for ch in rearranged
    )
    if int(numeric) % 97 != 1:
        raise BankAccountServiceError("شماره شبا نامعتبر است (چک‌سام نادرست)")
    return full


def _validated_optional_card(value) -> Optional[str]:
    """نرمال‌سازی و اعتبارسنجی اختیاری شماره کارت (None => None)."""
    text = _normalize_optional_text(value)
    if text is None:
        return None
    return _validate_card_number(text)


def _validated_optional_sheba(value) -> Optional[str]:
    """نرمال‌سازی و اعتبارسنجی اختیاری شبا (None => None)."""
    text = _normalize_optional_text(value)
    if text is None:
        return None
    return _validate_sheba(text)


def _validate_verification_status(status) -> str:
    """اعتبارسنجی وضعیت تأیید (unverified / verified / rejected)."""
    normalized = str(status).strip().lower()
    if normalized not in VERIFICATION_STATUSES:
        raise BankAccountServiceError(
            "وضعیت تأیید نامعتبر است. مقادیر مجاز: "
            + ", ".join(VERIFICATION_STATUSES.keys())
        )
    return normalized


def _parse_bank_id(bank_id) -> int:
    """تبدیل ورایشی شناسه بانک به int (بدون دسترسی دیتابیس)."""
    if bank_id is None:
        raise BankAccountServiceError("شناسه بانک نمی‌تواند خالی باشد")
    try:
        return int(bank_id)
    except (TypeError, ValueError):
        raise BankAccountServiceError("شناسه بانک نامعتبر است")


def _get_bank_or_raise(db: Session, bank_id) -> Bank:
    """بازیابی بانک مرجع یا خطا"""
    bank = db.query(Bank).filter(Bank.id == _parse_bank_id(bank_id)).first()
    if not bank:
        raise BankAccountServiceError("بانک یافت نشد")
    return bank


def _validate_new_bank_id(db: Session, bank_id) -> Bank:
    """اعتبارسنجی مرجع بانک برای ایجاد/تغییر؛ فقط بانک فعال قابل انتخاب است."""
    bank = _get_bank_or_raise(db, bank_id)
    if not bank.is_active:
        raise BankAccountServiceError("بانک غیرفعال است و قابل انتخاب نیست")
    return bank


def _get_account_for_user(
    db: Session, user_id: str, account_id: int
) -> EmployeeBankAccount:
    """دریافت حساب متعلق به کاربر مشخص"""
    account = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == account_id,
        EmployeeBankAccount.user_id == user_id,
    ).first()
    if not account:
        raise BankAccountServiceError("حساب بانکی یافت نشد")
    return account


def _demote_primaries(db: Session, user_id: str) -> None:
    """خلع همه primaryهای کاربر (بدون commit؛ هم‌تراکنش با عملیات بعدی)."""
    db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user_id,
        EmployeeBankAccount.is_primary == True,  # noqa: E712
    ).update({EmployeeBankAccount.is_primary: False})


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_bank_accounts(db: Session, user_id: str) -> List[EmployeeBankAccount]:
    """لیست حساب‌های بانکی یک کاربر (اصلی اول؛ سپس قدیمی‌ترین)"""
    _validate_user_exists(db, user_id)
    return (
        db.query(EmployeeBankAccount)
        .filter(EmployeeBankAccount.user_id == user_id)
        .order_by(
            EmployeeBankAccount.is_primary.desc(),
            EmployeeBankAccount.created_at.asc(),
        )
        .all()
    )


def get_bank_account(
    db: Session, user_id: str, account_id: int
) -> EmployeeBankAccount:
    """دریافت یک حساب بر اساس ID (scoped به کاربر)"""
    _validate_user_exists(db, user_id)
    return _get_account_for_user(db, user_id, account_id)


# ---------------------------------------------------------------------------
# Create / Update / Delete
# ---------------------------------------------------------------------------

def create_bank_account(
    db: Session,
    user_id: str,
    bank_id: int,
    account_number: str,
    branch_name: Optional[str] = None,
    branch_code: Optional[str] = None,
    card_number: Optional[str] = None,
    sheba: Optional[str] = None,
    account_type: Optional[str] = None,
    account_title: Optional[str] = None,
    description: Optional[str] = None,
    is_primary: bool = False,
    is_active: bool = True,
) -> EmployeeBankAccount:
    """ایجاد حساب بانکی جدید

    bank_name به‌صورت خودکار از ردیف مرجع Bank اسنپ‌شات می‌شود
    (همانند شهر در address_service؛ ورودی دستی برای نام بانک گرفته نمی‌شود).

    اگر حساب جدید primary باشد، primary قبلی همین کاربر ابتدا خلع
    می‌شود؛ سپس حساب درج می‌شود (demote-اول، الگوی address_service).

    حساب غیرفعال نمی‌تواند primary باشد.
    شماره حساب رشته می‌ماند. کارت/شبا در صورت ورود، اعتبارسنجی
    الگوریتمی محلی می‌شوند (بدون تغییر verification_*).
    """
    _validate_user_exists(db, user_id)
    account_number = _validate_required_text(account_number, "شماره حساب")
    bank = _validate_new_bank_id(db, bank_id)
    card_number = _validated_optional_card(card_number)
    sheba = _validated_optional_sheba(sheba)
    if is_primary and not is_active:
        raise BankAccountServiceError("حساب غیرفعال نمی‌تواند اصلی باشد")

    if is_primary:
        _demote_primaries(db, user_id)

    new_account = EmployeeBankAccount(
        user_id=user_id,
        bank_id=bank.id,
        bank_name=bank.name,
        branch_name=_normalize_optional_text(branch_name),
        branch_code=_normalize_optional_text(branch_code),
        account_number=account_number,
        card_number=card_number,
        sheba=sheba,
        account_type=_normalize_optional_text(account_type),
        account_title=_normalize_optional_text(account_title),
        description=_normalize_optional_text(description),
        is_primary=is_primary,
        is_active=bool(is_active),
    )
    db.add(new_account)
    db.flush()
    db.commit()
    db.refresh(new_account)
    return new_account


def update_bank_account(
    db: Session,
    user_id: str,
    account_id: int,
    bank_id=_UNSET,
    branch_name=_UNSET,
    branch_code=_UNSET,
    account_number=_UNSET,
    card_number=_UNSET,
    sheba=_UNSET,
    account_type=_UNSET,
    account_title=_UNSET,
    description=_UNSET,
) -> EmployeeBankAccount:
    """ویرایش حساب بانکی

    Param defaults use _UNSET sentinel so callers can:
      - omit a param  => keep existing value
      - pass None     => clear the field (optional fields only)
      - pass a value  => update the field

    account_number هرگز None/خالی نمی‌پذیرد (NOT NULL دیتابیس).

    bank_id مرجع بانک است؛ با تغییر آن، اسنپ‌شات bank_name از ردیف
    مرجع بازسازی می‌شود (الگوی city_id در address_service). نگه‌داشتن
    همان شناسه بانکِ غیرفعال، اسنپ‌شات موجود را دست‌نخورده حفظ می‌کند.

    is_primary / is_active / وضعیت تأیید با عملیات مخصوص خود تغییر
    می‌کنند و موضوع این تابع نیستند.

    card_number / sheba در صورت ارسال (شامل None برای پاک‌کردن) با
    اعتبارسنجی الگوریتمی محلی بررسی می‌شوند؛ فیلدهای verification
    دست نمی‌خورند.
    """
    _validate_user_exists(db, user_id)
    account = _get_account_for_user(db, user_id, account_id)

    if bank_id is not _UNSET:
        new_bank_id = _parse_bank_id(bank_id)
        if new_bank_id == account.bank_id:
            bank = _get_bank_or_raise(db, new_bank_id)
            if bank.is_active:
                account.bank_name = bank.name
        else:
            bank = _validate_new_bank_id(db, new_bank_id)
            account.bank_id = bank.id
            account.bank_name = bank.name

    if account_number is not _UNSET:
        account.account_number = _validate_required_text(
            account_number, "شماره حساب"
        )
    if branch_name is not _UNSET:
        account.branch_name = _normalize_optional_text(branch_name)
    if branch_code is not _UNSET:
        account.branch_code = _normalize_optional_text(branch_code)
    if card_number is not _UNSET:
        account.card_number = _validated_optional_card(card_number)
    if sheba is not _UNSET:
        account.sheba = _validated_optional_sheba(sheba)
    if account_type is not _UNSET:
        account.account_type = _normalize_optional_text(account_type)
    if account_title is not _UNSET:
        account.account_title = _normalize_optional_text(account_title)
    if description is not _UNSET:
        account.description = _normalize_optional_text(description)

    db.commit()
    db.refresh(account)
    return account


def delete_bank_account(
    db: Session, user_id: str, account_id: int
) -> None:
    """حذف حساب بانکی

    الگوی address_service: حذف انجام می‌شود؛ هیچ حساب دیگری به‌طور
    خودکار primary نمی‌شود (سیاست جایگزینی خودکار اختراع نشده است).
    """
    _validate_user_exists(db, user_id)
    account = _get_account_for_user(db, user_id, account_id)
    db.delete(account)
    db.commit()


# ---------------------------------------------------------------------------
# Primary / Active
# ---------------------------------------------------------------------------

def set_primary_bank_account(
    db: Session, user_id: str, account_id: int
) -> EmployeeBankAccount:
    """تنظیم حساب اصلیِ فعلی کاربر

    ابتدا همه primaryهای قبلیِ کاربر خلع می‌شوند، سپس حساب هدف
    primary می‌شود؛ همه در یک تراکنش. ایندکس یکتای جزئی
    (user_id WHERE is_primary AND is_active) شبکه ایمنی نهایی است.

    حساب غیرفعال نمی‌تواند primary شود.
    """
    _validate_user_exists(db, user_id)
    account = _get_account_for_user(db, user_id, account_id)
    if not account.is_active:
        raise BankAccountServiceError("حساب غیرفعال نمی‌تواند اصلی باشد")

    _demote_primaries(db, user_id)
    account.is_primary = True
    db.flush()
    db.commit()
    db.refresh(account)
    return account


def set_active_bank_account(
    db: Session, user_id: str, account_id: int, active: bool
) -> EmployeeBankAccount:
    """فعال/غیرفعال کردن حساب بانکی

    غیرفعال‌کردن حساب اصلیِ فعال مجاز است:
    - is_primary حفظ می‌شود (علائم داده دست‌نخورده می‌مانند)
    - هیچ حساب دیگری به‌طور خودکار primary نمی‌شود
      (الگوی address_service؛ سیاست جایگزینی خودکار اختراع نشده)
    - کاربر تا فعال‌سازی مجدد یا set_primary دیگر، حساب اصلیِ فعال
      نخواهد داشت؛ ایندکس جزئی همچنان حداکثر یک اصلیِ فعال را تضمین می‌کند
    """
    _validate_user_exists(db, user_id)
    account = _get_account_for_user(db, user_id, account_id)
    account.is_active = bool(active)
    db.commit()
    db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Organizational verification (separate from algorithmic validation)
# ---------------------------------------------------------------------------

def change_verification_status(
    db: Session,
    user_id: str,
    account_id: int,
    status: str,
    changed_by: Optional[str] = None,
    note: Optional[str] = None,
) -> EmployeeBankAccount:
    """تغییر وضعیت تأیید سازمانی حساب (unverified / verified / rejected)

    verified/rejected:
      - verification_status، verified_at (اکنون)، verified_by (changed_by
        الزامی) و verification_note به‌روز می‌شوند
    unverified:
      - verified_at / verified_by پاک می‌شوند (الگوی خلاف‌گیری در
        education.py)؛ verification_note مقدار داده‌شده را می‌گیرد

    changed_by فقط در verified_by ذخیره می‌شود؛ FK ندارد (مطابق
    education.verified_by). هیچ اعتبارسنجی الگوریتمی کارت/شبا در
    این تابع انجام نمی‌شود.
    """
    _validate_user_exists(db, user_id)
    account = _get_account_for_user(db, user_id, account_id)
    normalized = _validate_verification_status(status)
    note = _normalize_optional_text(note)

    if normalized in ("verified", "rejected"):
        changed_by = _validate_required_text(changed_by, "انجام‌دهنده تغییر")
        account.verified_at = datetime.now(timezone.utc)
        account.verified_by = changed_by
    else:
        account.verified_at = None
        account.verified_by = None

    account.verification_status = normalized
    account.verification_note = note
    db.commit()
    db.refresh(account)
    return account
