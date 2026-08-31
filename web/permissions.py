"""
🔐 سیستم کنترل دسترسی (RBAC + Per-User Override)
"""
from functools import lru_cache
from sqlalchemy.orm import Session
from models.user import User
from models.user_permission import UserPermission


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
    'view_contracts':       {'label': 'مشاهده قراردادها',          'admin': False, 'super_admin': True},
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
    effective = get_effective_permissions(db, user)
    return permission in effective


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
    else:
        new_perm = UserPermission(
            user_id=user_id,
            permission=permission,
            granted=granted,
            reason=reason,
            created_by=created_by
        )
        db.add(new_perm)

    db.commit()
    return True


def remove_user_permission(db: Session, user_id: str, permission: str) -> bool:
    """حذف override دسترسی (بازگشت به پیش‌فرض نقش)"""
    existing = db.query(UserPermission).filter(
        UserPermission.user_id == user_id,
        UserPermission.permission == permission
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return True
    return False