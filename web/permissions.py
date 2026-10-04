"""
🔐 سیستم کنترل دسترسی (RBAC + Per-User Override)

پیش‌فرض نقش از جدول role_permissions خوانده می‌شود (قابل‌ویرایش از UI).
ALL_PERMISSIONS کاتالوگ کد/برچسب و seed اولیه است.
"""
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
}

# ترکیب‌هایی که از UI قابل غیرفعال‌کردن نیستند (جلوگیری از قفل‌شدن مدیریت)
LOCKED_ROLE_DEFAULTS = {
    ('super_admin', 'manage_users'),
    ('super_admin', 'change_role'),
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
    if role not in KNOWN_ROLES:
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
