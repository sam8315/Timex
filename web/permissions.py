"""
🔐 سیستم کنترل دسترسی (RBAC + Per-User Override)

پیش‌فرض نقش از جدول role_permissions خوانده می‌شود (قابل‌ویرایش از UI).
ALL_PERMISSIONS کاتالوگ کد/برچسب و seed اولیه است.
"""
import re
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from models.user import User
from models.user_permission import UserPermission, UserPermissionHistory
from models.role_permission import RolePermission, RolePermissionHistory


# ============================================
# 📋 تعریف همه دسترسی‌ها (کاتالوگ + seed اولیه)
# ============================================
ALL_PERMISSIONS = {
    'view_dashboard':       {'label': 'مشاهده داشبورد مدیریت',     'admin': True,  'super_admin': True},
    'view_all_attendance':  {'label': 'مشاهده تردد همه کارمندان',  'admin': True,  'super_admin': True},
    'view_user_attendance': {'label': 'مشاهده تردد ماهانه کاربر',  'admin': True,  'super_admin': True},
    'approve_leave':        {'label': 'تأیید/رد مرخصی',           'admin': True,  'super_admin': True},
    'add_attendance':       {'label': 'افزودن رکورد تردد دستی',    'admin': False, 'super_admin': True},
    'edit_attendance':      {'label': 'ویرایش رکورد تردد',         'admin': False, 'super_admin': True},
    'delete_attendance':    {'label': 'حذف رکورد تردد',            'admin': False, 'super_admin': True},
    'change_punch':         {'label': 'تغییر وضعیت ورود/خروج',     'admin': False, 'super_admin': True},
    'manage_users':         {'label': 'مدیریت کاربران',            'admin': False, 'super_admin': True},
    'reset_password':       {'label': 'ریست رمز عبور',             'admin': False, 'super_admin': True},
    'change_role':          {'label': 'تغییر نقش کاربر',           'admin': False, 'super_admin': True},
    'toggle_web':           {'label': 'فعال/غیرفعال وب',           'admin': False, 'super_admin': True},
    'upload_photo':         {'label': 'آپلود عکس پروفایل',         'admin': True,  'super_admin': True},
    'edit_profile':         {'label': 'ویرایش پروفایل کارمند',     'admin': False, 'super_admin': True},
    'view_reports':         {'label': 'مشاهده گزارشات',            'admin': True,  'super_admin': True},
    'view_incomplete':      {'label': 'مشاهده ترددهای ناقص',       'admin': True,  'super_admin': True},
    'view_contracts':       {'label': 'مشاهده قراردادها',          'admin': True,  'super_admin': True},
    'add_contracts':        {'label': 'افزودن قرارداد',            'admin': True,  'super_admin': True},
    'edit_contracts':       {'label': 'ویرایش قرارداد',            'admin': True,  'super_admin': True},
    'delete_contracts':     {'label': 'حذف قرارداد',               'admin': True,  'super_admin': True},
    'view_leave_balances':  {'label': 'مشاهده مانده مرخصی',        'admin': True,  'super_admin': True},
    'manage_cities':        {'label': 'مدیریت شهرها',              'admin': True,  'super_admin': True},
    'manage_positions':     {'label': 'مدیریت سمت‌ها',              'admin': True,  'super_admin': True},
    'manage_service_locations': {'label': 'مدیریت محل خدمت',       'admin': True,  'super_admin': True},
    'view_system_monitoring': {'label': 'مشاهده پایش سرویس‌ها',   'admin': True,  'super_admin': True},
    'view_employee_documents': {'label': 'مشاهده مدارک پرسنلی',    'admin': True,  'super_admin': True},
    'manage_employee_documents': {'label': 'مدیریت مدارک پرسنلی', 'admin': True,  'super_admin': True},
    'verify_employee_documents': {'label': 'تأیید/رد مدارک پرسنلی', 'admin': True,  'super_admin': True},
    'manage_employee_document_types': {
        'label': 'مدیریت انواع مدارک پرسنلی',
        'admin': True,
        'super_admin': True,
    },
    'view_employee_relatives': {
        'label': 'مشاهده بستگان کارمند',
        'admin': True,
        'super_admin': True,
    },
    'manage_employee_relatives': {
        'label': 'مدیریت بستگان کارمند',
        'admin': True,
        'super_admin': True,
    },
    'verify_employee_relatives': {
        'label': 'تأیید/رد بستگان کارمند',
        'admin': True,
        'super_admin': True,
    },
    'manage_membership_types': {
        'label': 'مدیریت انواع عضویت',
        'admin': False,
        'super_admin': True,
    },
    'manage_membership_rules': {
        'label': 'مدیریت قواعد عضویت',
        'admin': False,
        'super_admin': True,
    },
    'manage_service_adjustments': {
        'label': 'مدیریت تعدیل خدمت',
        'admin': False,
        'super_admin': True,
    },
    'manage_payroll': {
        'label': 'مدیریت حقوق و دستمزد',
        'admin': False,
        'super_admin': True,
    },
    'view_payroll': {
        'label': 'مشاهده عملیات حقوق',
        'admin': True,
        'super_admin': True,
    },
    'manage_permissions': {
        'label': 'مدیریت دسترسی‌ها و نقش‌ها',
        'admin': False,
        'super_admin': True,
    },
    'manage_policies': {
        'label': 'مدیریت سیاست‌ها',
        'admin': False,
        'super_admin': True,
    },
    'adjust_leave_balance': {
        'label': 'تنظیم دستی مانده مرخصی',
        'admin': False,
        'super_admin': True,
    },
}

# ترکیب‌هایی که از UI قابل غیرفعال‌کردن نیستند (جلوگیری از قفل‌شدن مدیریت)
LOCKED_ROLE_DEFAULTS = {
    ('super_admin', 'manage_users'),
    ('super_admin', 'change_role'),
    ('super_admin', 'manage_permissions'),
}

KNOWN_ROLES = ('user', 'admin', 'super_admin')


def catalog_role_default(permission: str, role: str) -> bool:
    """پیش‌فرض seed داخل کد (fallback و مقدار اولیه seed)."""
    info = ALL_PERMISSIONS.get(permission)
    if not info:
        return False
    return bool(info.get(role or 'user', False))


def is_role_default_locked(role: str, permission: str) -> bool:
    return (role, permission) in LOCKED_ROLE_DEFAULTS


def get_role_permission_map(db: Session, role: str) -> dict[str, bool]:
    """
    نقشهٔ پیش‌فرض دسترسی برای یک نقش.
    ردیف DB اولویت دارد؛ در نبود ردیف → seed کد.
    """
    role = role or 'user'
    result = {
        code: catalog_role_default(code, role)
        for code in ALL_PERMISSIONS
    }
    try:
        rows = db.query(RolePermission).filter(RolePermission.role == role).all()
    except Exception:
        return result
    for row in rows:
        if row.permission in result:
            result[row.permission] = bool(row.granted)
    return result


def role_has_permission_default(db: Session, role: str, permission: str) -> bool:
    if permission not in ALL_PERMISSIONS:
        return False
    return get_role_permission_map(db, role).get(permission, False)


def get_effective_permissions(db: Session, user: User) -> set:
    """
    محاسبه دسترسی‌های مؤثر کاربر
    = دسترسی‌های نقش (از DB) + grant‌های دستی - revoke‌های دستی
    """
    if not user:
        return set()

    role = user.role or 'user'
    role_map = get_role_permission_map(db, role)
    base_perms = {code for code, granted in role_map.items() if granted}

    overrides = db.query(UserPermission).filter(
        UserPermission.user_id == user.user_id
    ).all()

    for override in overrides:
        if override.granted:
            base_perms.add(override.permission)
        else:
            base_perms.discard(override.permission)

    return base_perms


def has_permission(db: Session, user: User, permission: str) -> bool:
    """بررسی اینکه آیا کاربر دسترسی مشخصی دارد یا خیر"""
    if permission not in ALL_PERMISSIONS:
        return False
    effective = get_effective_permissions(db, user)
    return permission in effective


def enforce_permission(db: Session, user: User, permission: str) -> None:
    """اعمال دسترسی؛ در صورت نداشتن، خطای 403 می‌دهد.

    برای صفحات HTML ادمین که قبلاً با require_admin گیت شده‌اند،
    این تابع لایه دوم (override فردی) را اعمال می‌کند.
    """
    if not has_permission(db, user, permission):
        raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")


def get_permission_history(db: Session, user_id: str, limit: int = 50) -> list:
    """تاریخچه الحاقی تغییرات (جدیدترین اول)"""
    try:
        return (
            db.query(UserPermissionHistory)
            .filter(UserPermissionHistory.user_id == user_id)
            .order_by(UserPermissionHistory.created_at.desc(), UserPermissionHistory.id.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        # اگر جدول history هنوز migrate نشده، fallback به جدول فعلی
        return (
            db.query(UserPermission)
            .filter(UserPermission.user_id == user_id)
            .order_by(UserPermission.created_at.desc())
            .limit(limit)
            .all()
        )


def get_role_permission_history(db: Session, role: str, limit: int = 50) -> list:
    """تاریخچه تغییرات پیش‌فرض یک نقش."""
    try:
        return (
            db.query(RolePermissionHistory)
            .filter(RolePermissionHistory.role == role)
            .order_by(
                RolePermissionHistory.created_at.desc(),
                RolePermissionHistory.id.desc(),
            )
            .limit(limit)
            .all()
        )
    except Exception:
        return []


def _log_history(
    db: Session,
    user_id: str,
    permission: str,
    action: str,
    granted,
    reason: str = "",
    created_by: str = "",
) -> None:
    try:
        db.add(UserPermissionHistory(
            user_id=user_id,
            permission=permission,
            action=action,
            granted=granted,
            reason=reason,
            created_by=created_by,
        ))
    except Exception:
        pass


def _log_role_history(
    db: Session,
    role: str,
    permission: str,
    action: str,
    granted,
    reason: str = "",
    created_by: str = "",
) -> None:
    try:
        db.add(RolePermissionHistory(
            role=role,
            permission=permission,
            action=action,
            granted=granted,
            reason=reason,
            created_by=created_by,
        ))
    except Exception:
        pass


def set_user_permission(
    db: Session,
    user_id: str,
    permission: str,
    granted: bool,
    reason: str = "",
    created_by: str = ""
) -> bool:
    """تنظیم دسترسی فردی برای یک کاربر"""
    if permission not in ALL_PERMISSIONS:
        return False

    existing = db.query(UserPermission).filter(
        UserPermission.user_id == user_id,
        UserPermission.permission == permission
    ).first()

    if existing:
        existing.granted = granted
        existing.reason = reason
        existing.created_by = created_by
        try:
            existing.updated_at = datetime.now()
        except Exception:
            pass
    else:
        new_perm = UserPermission(
            user_id=user_id,
            permission=permission,
            granted=granted,
            reason=reason,
            created_by=created_by
        )
        db.add(new_perm)

    _log_history(db, user_id, permission, 'grant' if granted else 'revoke',
                 granted, reason, created_by)
    db.commit()
    return True


def remove_user_permission(
    db: Session,
    user_id: str,
    permission: str,
    reason: str = "",
    created_by: str = "",
) -> bool:
    """حذف override دسترسی (بازگشت به پیش‌فرض نقش) + ثبت در تاریخچه"""
    existing = db.query(UserPermission).filter(
        UserPermission.user_id == user_id,
        UserPermission.permission == permission
    ).first()

    if existing:
        db.delete(existing)
        _log_history(db, user_id, permission, 'reset', None, reason, created_by)
        db.commit()
        return True
    # حتی اگر override فعالی نبود، reset را لاگ کن تا نیت مدیر ثبت شود
    _log_history(db, user_id, permission, 'reset', None, reason, created_by)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return False


def set_role_permission(
    db: Session,
    role: str,
    permission: str,
    granted: bool,
    reason: str = "",
    created_by: str = "",
) -> tuple[bool, str]:
    """
    تنظیم پیش‌فرض دسترسی یک نقش.
    برمی‌گرداند: (موفقیت، پیام خطا/خالی)
    """
    if not role_exists(db, role):
        return False, "نقش نامعتبر"
    if permission not in ALL_PERMISSIONS:
        return False, "دسترسی نامعتبر"
    if is_role_default_locked(role, permission) and not granted:
        return False, "این پیش‌فرض برای مدیر ارشد قفل است"

    existing = db.query(RolePermission).filter(
        RolePermission.role == role,
        RolePermission.permission == permission,
    ).first()

    if existing:
        existing.granted = granted
        existing.reason = reason
        existing.updated_by = created_by
        try:
            existing.updated_at = datetime.now()
        except Exception:
            pass
    else:
        db.add(RolePermission(
            role=role,
            permission=permission,
            granted=granted,
            reason=reason,
            updated_by=created_by,
        ))

    action = 'enable' if granted else 'disable'
    _log_role_history(db, role, permission, action, granted, reason, created_by)
    db.commit()
    return True, ""


ROLE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")

SYSTEM_ROLE_SEED = (
    ("user", "کاربر", "نقش پایهٔ کارکنان"),
    ("admin", "مدیر", "نقش مدیریتی سیستمی"),
    ("super_admin", "مدیر ارشد", "نقش سیستمی با دسترسی کامل پیش‌فرض"),
)


def role_exists(db: Session, role: str) -> bool:
    """نقش در جدول roles هست، یا هنوز جدول ساخته نشده و کد سیستمی است."""
    from models.role import Role

    code = (role or "").strip()
    if not code:
        return False
    try:
        found = db.query(Role.id).filter(Role.code == code).first()
    except Exception:
        return code in KNOWN_ROLES
    if found:
        return True
    try:
        has_any = db.query(Role.id).first()
    except Exception:
        return code in KNOWN_ROLES
    if has_any is None:
        return code in KNOWN_ROLES
    return False


def list_role_options(db: Session) -> list[dict]:
    """کاتالوگ نقش برای فرم‌ها. اگر جدول خالی باشد سه نقش سیستمی برمی‌گردد."""
    from models.role import Role

    try:
        rows = db.query(Role).order_by(Role.is_system.desc(), Role.label.asc()).all()
    except Exception:
        rows = []
    if not rows:
        return [
            {
                "code": code,
                "label": label,
                "description": description,
                "is_system": True,
            }
            for code, label, description in SYSTEM_ROLE_SEED
        ]
    return [
        {
            "code": row.code,
            "label": row.label,
            "description": row.description or "",
            "is_system": bool(row.is_system),
        }
        for row in rows
    ]


def role_label_map(db: Session) -> dict[str, str]:
    return {item["code"]: item["label"] for item in list_role_options(db)}


def _validate_role_code(code: str) -> str:
    code = (code or "").strip().lower()
    if not ROLE_CODE_RE.match(code):
        raise ValueError("کد نقش فقط حروف کوچک انگلیسی، رقم و _ است و باید با حرف شروع شود")
    return code


def _validate_role_label(label: str) -> str:
    label = (label or "").strip()
    if not label or len(label) > 100:
        raise ValueError("برچسب نقش الزامی است و حداکثر ۱۰۰ نویسه دارد")
    return label


def create_role(
    db: Session,
    code: str,
    label: str,
    description: str = "",
    copy_from: str = "user",
    created_by: str = "",
) -> tuple[bool, str]:
    """ساخت نقش و کپی پیش‌فرض دسترسی‌ها از یک نقش موجود."""
    from models.role import Role

    try:
        code = _validate_role_code(code)
        label = _validate_role_label(label)
    except ValueError as exc:
        return False, str(exc)

    description = (description or "").strip()
    if len(description) > 500:
        return False, "توضیح نقش حداکثر ۵۰۰ نویسه است"

    if db.query(Role.id).filter(Role.code == code).first():
        return False, "این کد نقش قبلاً ثبت شده است"

    source = (copy_from or "user").strip() or "user"
    if not role_exists(db, source):
        return False, "نقش مبدأ برای کپی دسترسی معتبر نیست"

    db.add(Role(
        code=code,
        label=label,
        description=description or None,
        is_system=False,
    ))
    source_map = get_role_permission_map(db, source)
    for permission, granted in source_map.items():
        db.add(RolePermission(
            role=code,
            permission=permission,
            granted=bool(granted),
            reason=f"کپی از {source}",
            updated_by=created_by or None,
        ))
    db.commit()
    return True, ""


def update_role(
    db: Session,
    code: str,
    label: str,
    description: str = "",
) -> tuple[bool, str]:
    """ویرایش برچسب و توضیح. کد نقش ثابت می‌ماند."""
    from models.role import Role

    role = db.query(Role).filter(Role.code == (code or "").strip()).first()
    if not role:
        return False, "نقش یافت نشد"
    try:
        role.label = _validate_role_label(label)
    except ValueError as exc:
        return False, str(exc)
    description = (description or "").strip()
    if len(description) > 500:
        return False, "توضیح نقش حداکثر ۵۰۰ نویسه است"
    role.description = description or None
    db.commit()
    return True, ""


def delete_role(db: Session, code: str) -> tuple[bool, str]:
    """حذف نقش غیرسیستمی که هیچ کاربری ندارد، همراه با پیش‌فرض دسترسی‌هایش."""
    from models.role import Role
    from models.user import User

    code = (code or "").strip()
    role = db.query(Role).filter(Role.code == code).first()
    if not role:
        return False, "نقش یافت نشد"
    if role.is_system:
        return False, "نقش سیستمی قابل حذف نیست"
    assigned = db.query(User.id).filter(User.role == code).count()
    if assigned:
        return False, f"این نقش به {assigned} کاربر اختصاص دارد و قابل حذف نیست"
    db.query(RolePermission).filter(RolePermission.role == code).delete()
    db.delete(role)
    db.commit()
    return True, ""
