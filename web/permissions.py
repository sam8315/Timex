"""
🔐 سیستم کنترل دسترسی (RBAC + Per-User Override)
"""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from models.user import User
from models.user_permission import UserPermission, UserPermissionHistory


# ============================================
# 📋 تعریف همه دسترسی‌ها
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
    'view_leave_balances':  {'label': 'مشاهده مانده مرخصی',        'admin': True,  'super_admin': True},
}


def get_effective_permissions(db: Session, user: User) -> set:
    """
    محاسبه دسترسی‌های مؤثر کاربر
    = دسترسی‌های نقش + grant‌های دستی - revoke‌های دستی
    """
    if not user:
        return set()

    # ۱. دسترسی‌های پایه از نقش
    role = user.role or 'user'
    base_perms = set()
    for perm_code, perm_info in ALL_PERMISSIONS.items():
        if perm_info.get(role, False):
            base_perms.add(perm_code)

    # ۲. اعمال override‌های فردی
    overrides = db.query(UserPermission).filter(
        UserPermission.user_id == user.user_id
    ).all()

    for override in overrides:
        if override.granted:
            base_perms.add(override.permission)      # اعطا
        else:
            base_perms.discard(override.permission)  # سلب

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