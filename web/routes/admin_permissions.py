"""صفحه مدیریت دسترسی‌های کاربران"""
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    get_role_permission_history,
    get_role_permission_map,
    is_role_default_locked,
    role_has_permission_default,
    set_role_permission,
    set_user_permission,
    remove_user_permission,
    list_role_options,
    role_label_map,
    create_role,
    update_role,
    delete_role,
    role_exists,
)
from web.session import make_csrf_token, check_csrf_token
import jdatetime
from datetime import datetime

router = APIRouter(tags=["Admin Permissions"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


# ── نقش‌ها از جدول roles؛ سه نقش سیستمی در نبود جدول fallback می‌شوند ──
def _role_catalog(db):
    return list_role_options(db)


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
    tab: str = Query(None),              # users / perms / roles
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

    role_catalog = _role_catalog(db)
    valid_roles = {item["code"] for item in role_catalog}
    from sqlalchemy import func
    count_map = {
        code: count
        for code, count in db.query(User.role, func.count(User.id)).group_by(User.role).all()
    }
    for item in role_catalog:
        item["user_count"] = count_map.get(item["code"], 0)

    # ---- اعتبارسنجی پرامترهای اختیاری (مقادیر نامعتبر → صادقانه نادیده/گزارش) ----
    permission_error = False
    if permission and permission not in ALL_PERMISSIONS:
        permission_error = True
        permission = None
    role_error = False
    if role and role not in valid_roles:
        role_error = True
        role = None
    if state not in ("allowed", "denied"):
        state = None
    perm_selected = permission in ALL_PERMISSIONS

    if perm_selected:
        active_tab = 'perms'
    elif tab == 'roles':
        active_tab = 'roles'
    elif tab == 'users':
        active_tab = 'users'
    elif tab == 'perms':
        active_tab = 'perms'
    else:
        active_tab = 'users'
    all_permissions = [
        {"code": code, "label": info["label"]}
        for code, info in ALL_PERMISSIONS.items()
    ]
    permission_label = ALL_PERMISSIONS[permission]["label"] if perm_selected else ""
    role_default_self = (
        role_has_permission_default(db, user.role or 'user', permission)
        if perm_selected else None
    )

    # ── نمای Role-Centric: پیش‌فرض نقش از DB (قابل‌ویرایش) ──
    role_selected = active_tab == 'roles' and role in valid_roles
    role_label = ""
    role_perms = []
    role_counts = None
    role_history_list = []
    role_is_system = False
    role_description = ""
    role_user_count = 0
    if role_selected:
        selected_meta = next((r for r in role_catalog if r["code"] == role), None)
        if selected_meta:
            role_is_system = bool(selected_meta["is_system"])
            role_description = selected_meta.get("description") or ""
            role_user_count = selected_meta.get("user_count") or 0
        role_label = next((r["label"] for r in role_catalog if r["code"] == role), role)
        role_map = get_role_permission_map(db, role)
        for code, info in ALL_PERMISSIONS.items():
            active = role_map.get(code, False)
            role_perms.append({
                "code": code,
                "label": info["label"],
                "active": active,
                "locked": is_role_default_locked(role, code),
            })
        granted = sum(1 for rp in role_perms if rp["active"])
        role_counts = {
            "total": len(role_perms),
            "granted": granted,
            "not_granted": len(role_perms) - granted,
        }
        for h in get_role_permission_history(db, role, limit=30):
            role_history_list.append({
                "permission": h.permission,
                "permission_label": ALL_PERMISSIONS.get(h.permission, {}).get(
                    "label", h.permission
                ),
                "action": h.action,
                "granted": h.granted,
                "reason": h.reason,
                "created_by": h.created_by,
                "created_at_j": (
                    jdatetime.datetime.fromgregorian(datetime=h.created_at).strftime(
                        "%Y/%m/%d %H:%M"
                    )
                    if h.created_at else "-"
                ),
            })

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

        # پیش‌فرض نقش‌ها یک‌بار برای نقش‌های موجود در صفحه
        role_defaults_cache = {}
        # مؤثر = نقش + grant/revoke — همان فرمول get_effective_permissions
        perm_rows = []  # (user_id, role, active, source, has_override)
        cnt_eff = cnt_denied = cnt_override = 0
        for uid, urole in matched:
            urole = urole or 'user'
            if urole not in role_defaults_cache:
                role_defaults_cache[urole] = role_has_permission_default(
                    db, urole, permission
                )
            rd = role_defaults_cache[urole]
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

    # ══════════════════ نمای Role-Centric ══════════════════
    elif active_tab == 'roles':
        user_list = []
        perm_counts = None
        total = 0
        total_pages = 1

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

        # پیش‌فرض نقش‌ها یک‌بار برای نقش‌های صفحه
        role_maps_cache = {}
        user_list = []
        perm_counts = None
        for u in users:
            overrides = override_map_all.get(u.user_id, [])
            role_u = u.role or 'user'
            if role_u not in role_maps_cache:
                role_maps_cache[role_u] = get_role_permission_map(db, role_u)
            effective = {
                code for code, granted in role_maps_cache[role_u].items() if granted
            }
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
        "csrf_token": make_csrf_token(user.user_id),
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
        # ── نمای Role-Centric ──
        "all_roles": role_catalog,
        "role_selected": role_selected,
        "role_label": role_label,
        "role_perms": role_perms,
        "role_counts": role_counts,
        "role_error": role_error,
        "role_history_list": role_history_list,
        "role_is_system": role_is_system,
        "role_description": role_description,
        "role_user_count": role_user_count,
    })


@router.post("/admin/permissions/roles/toggle")
async def toggle_role_permission(
    request: Request,
    role: str = Form(...),
    permission: str = Form(...),
    action: str = Form(...),  # enable / disable
    reason: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """تغییر پیش‌فرض دسترسی یک نقش (قابل‌ویرایش از تب نقش‌ها)."""
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")

    if action == "enable":
        ok, err = set_role_permission(
            db, role, permission, True, reason, user.user_id
        )
        msg = "پیش‌فرض نقش فعال شد" if ok else (err or "عملیات ناموفق")
    elif action == "disable":
        ok, err = set_role_permission(
            db, role, permission, False, reason, user.user_id
        )
        msg = "پیش‌فرض نقش غیرفعال شد" if ok else (err or "عملیات ناموفق")
    else:
        ok = False
        msg = "عملیات نامعتبر"

    if _wants_json(request):
        role_map = get_role_permission_map(db, role) if role_exists(db, role) else {}
        granted = sum(1 for value in role_map.values() if value)
        return JSONResponse({
            "ok": ok,
            "message": msg,
            "permission": permission,
            "permission_label": ALL_PERMISSIONS.get(permission, {}).get("label", permission),
            "active": bool(role_map.get(permission, False)),
            "locked": is_role_default_locked(role, permission),
            "granted": granted,
            "not_granted": max(len(ALL_PERMISSIONS) - granted, 0),
            "action": action if ok else "",
            "reason": reason,
            "created_by": user.user_id,
            "created_at_j": jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M"),
        })

    redirect_role = role if role_exists(db, role) else ""
    return RedirectResponse(
        url=(
            f"/admin/permissions?tab=roles&role={quote(redirect_role)}"
            f"&msg={quote(msg)}"
        ),
        status_code=302,
    )


def _roles_redirect(role: str, msg: str, *, error: bool = False) -> RedirectResponse:
    key = "err" if error else "msg"
    role_q = f"&role={quote(role)}" if role else ""
    return RedirectResponse(
        url=f"/admin/permissions?tab=roles{role_q}&{key}={quote(msg)}",
        status_code=302,
    )


@router.post("/admin/permissions/roles/create")
async def create_role_action(
    request: Request,
    label: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    copy_from: str = Form("user"),
    csrf_token: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ok, err = create_role(
        db,
        code=code,
        label=label,
        description=description,
        copy_from=copy_from,
        created_by=user.user_id,
    )
    if not ok:
        return _roles_redirect("", err, error=True)
    return _roles_redirect(code.strip().lower(), "نقش جدید ساخته شد")


@router.post("/admin/permissions/roles/update")
async def update_role_action(
    request: Request,
    role: str = Form(...),
    label: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ok, err = update_role(db, role, label, description)
    if not ok:
        return _roles_redirect(role, err, error=True)
    return _roles_redirect(role, "نقش ویرایش شد")


@router.post("/admin/permissions/roles/delete")
async def delete_role_action(
    request: Request,
    role: str = Form(...),
    csrf_token: str = Form(""),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if not check_csrf_token(csrf_token, user.user_id):
        raise HTTPException(status_code=403, detail="توکن امنیتی نامعتبر")
    ok, err = delete_role(db, role)
    if not ok:
        return _roles_redirect(role, err, error=True)
    return _roles_redirect("", "نقش حذف شد")


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

    role_map = get_role_permission_map(db, target_user.role or 'user')

    # ساخت لیست دسترسی‌ها با وضعیت هر کدام
    permissions_list = []
    for perm_code, perm_info in ALL_PERMISSIONS.items():
        role_default = role_map.get(perm_code, False)
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
        "role_labels": role_label_map(db),
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

    if _wants_json(request):
        target = db.query(User).filter(User.user_id == target_user_id).first()
        role_map = get_role_permission_map(db, (target.role if target else None) or "user")
        override = db.query(UserPermission).filter(
            UserPermission.user_id == target_user_id,
            UserPermission.permission == permission,
        ).first() if permission in ALL_PERMISSIONS else None
        role_default = bool(role_map.get(permission, False))
        if override:
            source = "grant" if override.granted else "revoke"
            is_active = bool(override.granted)
            shown_reason = override.reason or ""
        else:
            source = "role"
            is_active = role_default
            shown_reason = ""
        effective = get_effective_permissions(db, target) if target else set()
        overrides = db.query(UserPermission).filter(
            UserPermission.user_id == target_user_id
        ).all() if target else []
        granted_n = sum(1 for row in overrides if row.granted)
        revoked_n = sum(1 for row in overrides if not row.granted)
        return JSONResponse({
            "ok": permission in ALL_PERMISSIONS and action in ("grant", "revoke", "reset"),
            "message": msg,
            "permission": permission,
            "permission_label": ALL_PERMISSIONS.get(permission, {}).get("label", permission),
            "is_active": is_active,
            "source": source,
            "role_default": role_default,
            "reason": shown_reason,
            "effective_count": len(effective),
            "override_count": len(overrides),
            "granted_count": granted_n,
            "revoked_count": revoked_n,
            "role_count": len(ALL_PERMISSIONS) - len(overrides),
            "action": action if permission in ALL_PERMISSIONS else "",
            "created_by": user.user_id,
            "created_at_j": jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M"),
        })

    referer = request.headers.get("referer", f"/admin/permissions/{target_user_id}")
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(url=f"{referer}{sep}msg={quote(msg)}", status_code=302)
