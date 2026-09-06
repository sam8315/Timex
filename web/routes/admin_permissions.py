"""صفحه مدیریت دسترسی‌های کاربران"""
from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_super_admin
from models.user import User
from models.employee import Employee
from models.user_permission import UserPermission
from web.permissions import (
    ALL_PERMISSIONS,
    get_effective_permissions,
    get_permission_history,
    set_user_permission,
    remove_user_permission,
)
from web.session import make_csrf_token, check_csrf_token
import jdatetime
from datetime import datetime

router = APIRouter(tags=["Admin Permissions"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/admin/permissions", response_class=HTMLResponse)
async def admin_permissions_page(
    request: Request,
    search: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
    permission: str = Query(None),
    role: str = Query(None),
    state: str = Query(None),            # allowed / denied
    only_override: bool = Query(False),
    tab: str = Query(None),              # users / perms
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """لیست کاربران (User-Centric) یا نمای Permission-Centric («چه کسانی این دسترسی را دارند»).

    بدون پرامتر permission رفتار قبلی/فاز ۴ دقیقاً حفظ می‌شود.
    با پرامتر permission، برای همان دسترسیِ انتخاب‌شده، وضعیت مؤثر هر کاربر
    (نقش + override — دقیقاً معادل منطق get_effective_permissions) محاسبه و
    شمارش‌های سراسری قبل از pagination به نمایش درمی‌آید (هرگز از صفحهٔ جاری حدس زده نمی‌شود).
    """
    from sqlalchemy import or_

    # ---- اعتبارسنجی پرامترهای اختیاری (مقادیر نامعتبر → صادقانه نادیده/گزارش) ----
    permission_error = False
    if permission and permission not in ALL_PERMISSIONS:
        permission_error = True
        permission = None
    if role not in ("user", "admin", "super_admin"):
        role = None
    if state not in ("allowed", "denied"):
        state = None
    perm_selected = permission in ALL_PERMISSIONS

    active_tab = 'perms' if (tab == 'perms' or perm_selected) else 'users'
    all_permissions = [
        {"code": code, "label": info["label"]}
        for code, info in ALL_PERMISSIONS.items()
    ]
    permission_label = ALL_PERMISSIONS[permission]["label"] if perm_selected else ""
    role_default_self = (
        ALL_PERMISSIONS[permission].get(user.role or 'user', False)
        if perm_selected else None
    )

    query = db.query(User).outerjoin(Employee, User.user_id == Employee.user_id)

    if search and search.strip():
        term = search.strip()
        query = query.filter(
            or_(
                User.user_id.ilike(f"%{term}%"),
                User.name.ilike(f"%{term}%"),
                Employee.first_name.ilike(f"%{term}%"),
                Employee.last_name.ilike(f"%{term}%")
            )
        )

    if perm_selected and role:
        query = query.filter(User.role == role)

    # ══════════════════ نمای Permission-Centric ══════════════════
    if perm_selected:
        # کل مجموعهٔ منطبق (فیلتر search/role) — بدون pagination، برای شمارش صادق
        matched = query.with_entities(User.user_id, User.role).order_by(User.user_id).all()
        matched_ids = [m[0] for m in matched]

        # override های همین دسترسی روی کل set (یک کوئری دسته‌ای، بدون N+1)
        ov_map = {}
        if matched_ids:
            for ov in db.query(UserPermission).filter(
                UserPermission.user_id.in_(matched_ids),
                UserPermission.permission == permission,
            ).all():
                ov_map[ov.user_id] = ov

        # مؤثر = نقش + grant/revoke — همان فرمول get_effective_permissions (ترکیب نقش/override)
        perm_rows = []  # (user_id, role, active, source, has_override)
        cnt_eff = cnt_denied = cnt_override = 0
        for uid, urole in matched:
            rd = ALL_PERMISSIONS[permission].get(urole or 'user', False)
            ov = ov_map.get(uid)
            has_ov = ov is not None
            active = ov.granted if has_ov else rd
            source = 'grant' if (has_ov and ov.granted) else ('revoke' if has_ov else 'role')
            if state == 'allowed' and not active:
                continue
            if state == 'denied' and active:
                continue
            if only_override and not has_ov:
                continue
            perm_rows.append((uid, urole, active, source, has_ov))
            if active:
                cnt_eff += 1
            else:
                cnt_denied += 1
            if has_ov:
                cnt_override += 1

        perm_counts = {
            "total": len(perm_rows),
            "effective": cnt_eff,
            "denied": cnt_denied,
            "override": cnt_override,
        }
        total = len(perm_rows)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)

        page_ids = [r[0] for r in perm_rows[(page - 1) * per_page: page * per_page]]
        page_state = {uid: (active, source) for uid, _r, active, source, _h in perm_rows}

        emp_map = {}
        if page_ids:
            for emp in db.query(Employee).filter(Employee.user_id.in_(page_ids)).all():
                emp_map[emp.user_id] = emp
        users_by_id = {}
        if page_ids:
            for u in db.query(User).filter(User.user_id.in_(page_ids)).all():
                users_by_id[u.user_id] = u

        user_list = []
        for uid in page_ids:
            active, source = page_state[uid]
            real_u = users_by_id.get(uid)
            if real_u is None:
                continue
            user_list.append({
                "user": real_u,
                "employee": emp_map.get(uid),
                "perm_active": active,
                "perm_source": source,
            })

    # ══════════════════ نمای User-Centric (فاز ۴ — بدون تغییر) ══════════════════
    else:
        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        users = query.order_by(User.user_id).offset((page - 1) * per_page).limit(per_page).all()

        # Batch fetch برای حذف N+1
        user_ids = [u.user_id for u in users]
        emp_map = {}
        if user_ids:
            for emp in db.query(Employee).filter(Employee.user_id.in_(user_ids)).all():
                emp_map[emp.user_id] = emp
        override_map_all: dict[str, list] = {uid: [] for uid in user_ids}
        if user_ids:
            for ov in db.query(UserPermission).filter(UserPermission.user_id.in_(user_ids)).all():
                override_map_all.setdefault(ov.user_id, []).append(ov)

        user_list = []
        perm_counts = None
        for u in users:
            overrides = override_map_all.get(u.user_id, [])
            role_u = u.role or 'user'
            effective = {code for code, info in ALL_PERMISSIONS.items() if info.get(role_u, False)}
            for ov in overrides:
                if ov.granted:
                    effective.add(ov.permission)
                else:
                    effective.discard(ov.permission)
            user_list.append({
                'user': u,
                'employee': emp_map.get(u.user_id),
                'effective_perms_count': len(effective),
                'override_count': len(overrides),
            })

    return templates.TemplateResponse(request, "admin/permissions.html", {
        "user": user,
        "user_list": user_list,
        "search": search or "",
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "is_admin": True,
        "is_super_admin": True,
        # ── نمای Permission-Centric ──
        "active_tab": active_tab,
        "all_permissions": all_permissions,
        "permission": permission if perm_selected else "",
        "permission_label": permission_label,
        "permission_error": permission_error,
        "role_default_self": role_default_self,
        "selected_role": role or "",
        "selected_state": state or "",
        "only_override": only_override,
        "perm_counts": perm_counts,
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

    # تاریخچه تغییرات (از جدول الحاقی؛ fallback داخلی دارد)
    history = get_permission_history(db, target_user_id, limit=50)

    history_list = []
    for h in history:
        action = getattr(h, 'action', None)
        if action is None:
            # ردیف قدیمی از جدول user_permissions
            action = 'grant' if getattr(h, 'granted', False) else 'revoke'
        history_list.append({
            'permission': h.permission,
            'permission_label': ALL_PERMISSIONS.get(h.permission, {}).get('label', h.permission),
            'granted': h.granted,
            'action': action,
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
        "csrf_token": make_csrf_token(user.user_id),
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
    csrf_token: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """تغییر دسترسی یک کاربر"""
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    if permission not in ALL_PERMISSIONS:
        msg = "دسترسی نامعتبر"
    elif action == 'reset':
        remove_user_permission(db, target_user_id, permission, reason, user.user_id)
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