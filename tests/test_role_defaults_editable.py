"""Editable role-default permissions (role_permissions table + UI toggle)."""
import re

from .conftest import login_as

from models.role_permission import RolePermission, RolePermissionHistory
from models.user import User
from web.permissions import (
    ALL_PERMISSIONS,
    get_effective_permissions,
    get_role_permission_map,
    has_permission,
    set_role_permission,
)

HTML_ACCEPT = {"Accept": "text/html"}


def _csrf_from_html(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf hidden input not found"
    return m.group(1)


def test_seed_matches_catalog_defaults(db):
    role_map = get_role_permission_map(db, "admin")
    for code, info in ALL_PERMISSIONS.items():
        assert role_map[code] is bool(info.get("admin", False))


def test_set_role_permission_affects_effective(db, make_user):
    admin = make_user(role="admin")
    user = db.query(User).filter(User.user_id == admin["user_id"]).first()

    assert has_permission(db, user, "view_system_monitoring") is True

    ok, err = set_role_permission(
        db, "admin", "view_system_monitoring", False,
        reason="فقط مدیر ارشد", created_by="SYS",
    )
    assert ok and err == ""
    db.refresh(user)
    assert has_permission(db, user, "view_system_monitoring") is False
    assert "view_system_monitoring" not in get_effective_permissions(db, user)

    # super_admin still has it via role default
    super_u = make_user(role="super_admin")
    suser = db.query(User).filter(User.user_id == super_u["user_id"]).first()
    assert has_permission(db, suser, "view_system_monitoring") is True


def test_locked_super_admin_defaults_cannot_disable(db):
    ok, err = set_role_permission(
        db, "super_admin", "manage_users", False, created_by="SYS"
    )
    assert ok is False
    assert "قفل" in err
    assert get_role_permission_map(db, "super_admin")["manage_users"] is True


def test_role_toggle_ui_disables_admin_monitoring(client, db, make_user):
    super_u = make_user(role="super_admin")
    admin = make_user(role="admin")
    login_as(client, super_u["national_code"])

    page = client.get(
        "/admin/permissions?tab=roles&role=admin", headers=HTML_ACCEPT
    )
    assert page.status_code == 200
    assert 'action="/admin/permissions/roles/toggle"' in page.text
    token = _csrf_from_html(page.text)

    resp = client.post(
        "/admin/permissions/roles/toggle",
        data={
            "role": "admin",
            "permission": "view_system_monitoring",
            "action": "disable",
            "reason": "تست UI",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "tab=roles" in resp.headers["location"]
    assert "role=admin" in resp.headers["location"]

    row = db.query(RolePermission).filter(
        RolePermission.role == "admin",
        RolePermission.permission == "view_system_monitoring",
    ).first()
    assert row is not None and row.granted is False

    hist = (
        db.query(RolePermissionHistory)
        .filter(
            RolePermissionHistory.role == "admin",
            RolePermissionHistory.permission == "view_system_monitoring",
        )
        .order_by(RolePermissionHistory.id.desc())
        .first()
    )
    assert hist is not None
    assert hist.action == "disable"
    assert hist.reason == "تست UI"

    # Admin loses the permission; monitoring endpoint returns 403
    login_as(client, admin["national_code"])
    denied = client.get("/admin/system", headers=HTML_ACCEPT)
    assert denied.status_code == 403


def test_role_toggle_rejects_missing_csrf(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    resp = client.post(
        "/admin/permissions/roles/toggle",
        data={
            "role": "admin",
            "permission": "view_system_monitoring",
            "action": "disable",
            "csrf_token": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_roles_tab_shows_actions_not_readonly_hint(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    body = client.get("/admin/permissions?tab=roles", headers=HTML_ACCEPT).text
    assert "این نما فقط‌خواندنی است" not in body
    body2 = client.get(
        "/admin/permissions?tab=roles&role=admin", headers=HTML_ACCEPT
    ).text
    assert "غیرفعال" in body2 or "فعال" in body2
    assert 'name="action" value="disable"' in body2
