"""صفحه مدیریت دسترسی‌های کاربران"""
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_super_admin
from models.user import User
from models.employee import Employee
from models.user_permission import UserPermission
from web.permissions import ALL_PERMISSIONS, get_effective_permissions, set_user_permission, remove_user_permission
import jdatetime
from datetime import datetime

router = APIRouter(tags=["Admin Permissions"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/admin/permissions", response_class=HTMLResponse)
async def admin_permissions_page(
    request: Request,
    search: str = Query(None),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """صفحه مدیریت دسترسی‌ها - لیست کاربران"""
    query = db.query(User).outerjoin(Employee, User.user_id == Employee.user_id)

    if search and search.strip():
        term = search.strip()
        from sqlalchemy import or_
        query = query.filter(
            or_(
                User.user_id.ilike(f"%{term}%"),
                User.name.ilike(f"%{term}%"),
                Employee.first_name.ilike(f"%{term}%"),
                Employee.last_name.ilike(f"%{term}%")
            )
        )

    users = query.order_by(User.user_id).all()

    user_list = []
    for u in users:
        emp = db.query(Employee).filter(Employee.user_id == u.user_id).first()
        effective_perms = get_effective_permissions(db, u)
        override_count = db.query(UserPermission).filter(
            UserPermission.user_id == u.user_id
        ).count()

        user_list.append({
            'user': u,
            'employee': emp,
            'effective_perms_count': len(effective_perms),
            'override_count': override_count,
        })

    return templates.TemplateResponse(request, "admin/permissions.html", {
        "user": user,
        "user_list": user_list,
        "search": search or "",
        "is_admin": True,
        "is_super_admin": True,
    })


@router.get("/admin/permissions/{target_user_id}", response_class=HTMLResponse)
async def admin_user_permissions(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """صفحه مدیریت دسترسی‌های یک کاربر خاص"""
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/permissions", status_code=302)

    target_employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()

    # دسترسی‌های مؤثر فعلی
    effective_perms = get_effective_permissions(db, target_user)

    # override‌های موجود
    overrides = db.query(UserPermission).filter(
        UserPermission.user_id == target_user_id
    ).all()
    override_map = {o.permission: o for o in overrides}

    # ساخت لیست دسترسی‌ها با وضعیت هر کدام
    permissions_list = []
    for perm_code, perm_info in ALL_PERMISSIONS.items():
        role_default = perm_info.get(target_user.role or 'user', False)
        override = override_map.get(perm_code)

        if override:
            is_active = override.granted
            source = 'grant' if override.granted else 'revoke'
        else:
            is_active = role_default
            source = 'role'

        permissions_list.append({
            'code': perm_code,
            'label': perm_info['label'],
            'role_default': role_default,
            'is_active': is_active,
            'source': source,  # role / grant / revoke
            'override': override,
        })

    # تاریخچه تغییرات
    history = db.query(UserPermission).filter(
        UserPermission.user_id == target_user_id
    ).order_by(UserPermission.created_at.desc()).all()

    history_list = []
    for h in history:
        history_list.append({
            'permission': h.permission,
            'permission_label': ALL_PERMISSIONS.get(h.permission, {}).get('label', h.permission),
            'granted': h.granted,
            'reason': h.reason,
            'created_by': h.created_by,
            'created_at_j': jdatetime.datetime.fromgregorian(datetime=h.created_at).strftime('%Y/%m/%d %H:%M') if h.created_at else '-',
        })

    return templates.TemplateResponse(request, "admin/user_permissions.html", {
        "user": user,
        "target_user": target_user,
        "target_employee": target_employee,
        "permissions_list": permissions_list,
        "history_list": history_list,
        "effective_count": len(effective_perms),
        "is_admin": True,
        "is_super_admin": True,
    })


@router.post("/admin/permissions/{target_user_id}/toggle")
async def toggle_permission(
    request: Request,
    target_user_id: str,
    permission: str = Form(...),
    action: str = Form(...),  # grant / revoke / reset
    reason: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """تغییر دسترسی یک کاربر"""
    if action == 'reset':
        remove_user_permission(db, target_user_id, permission)
        msg = "دسترسی به پیش‌فرض بازگشت"
    elif action == 'grant':
        set_user_permission(db, target_user_id, permission, True, reason, user.user_id)
        msg = "دسترسی اعطا شد"
    elif action == 'revoke':
        set_user_permission(db, target_user_id, permission, False, reason, user.user_id)
        msg = "دسترسی سلب شد"
    else:
        msg = "عملیات نامعتبر"

    referer = request.headers.get("referer", f"/admin/permissions/{target_user_id}")
    return RedirectResponse(url=f"{referer}?msg={msg}", status_code=302)