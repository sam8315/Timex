"""ساخت، ویرایش و حذف نقش، و گیت پنل بر اساس دسترسی."""
import re

from .conftest import login_as

from models.role import Role
from models.user import User
from web.permissions import (
    create_role,
    delete_role,
    get_role_permission_map,
    set_role_permission,
    update_role,
)

HTML_ACCEPT = {"Accept": "text/html"}


def _csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "csrf hidden input not found"
    return match.group(1)


def test_create_role_copies_permissions_and_edit_label(db):
    ok, err = create_role(
        db, code="hr_officer", label="کارشناس منابع", copy_from="admin", created_by="SYS",
    )
    assert ok, err
    role = db.query(Role).filter(Role.code == "hr_officer").first()
    assert role is not None
    assert role.is_system is False
    assert get_role_permission_map(db, "hr_officer")["view_reports"] is True
    assert get_role_permission_map(db, "hr_officer")["manage_users"] is False

    ok, err = update_role(db, "hr_officer", "کارشناس ارشد منابع", "توضیح آزمایشی")
    assert ok, err
    db.refresh(role)
    assert role.label == "کارشناس ارشد منابع"
    assert role.description == "توضیح آزمایشی"
    assert role.code == "hr_officer"


def test_cannot_delete_system_role(db):
    ok, err = delete_role(db, "super_admin")
    assert ok is False
    assert "سیستمی" in err
    assert db.query(Role).filter(Role.code == "super_admin").first() is not None


def test_cannot_delete_role_assigned_to_user(db, make_user):
    ok, err = create_role(db, code="shift_lead", label="سرشیفت", copy_from="user")
    assert ok, err
    make_user(role="shift_lead")
    ok, err = delete_role(db, "shift_lead")
    assert ok is False
    assert "1" in err
    assert db.query(Role).filter(Role.code == "shift_lead").first() is not None


def test_delete_empty_custom_role(db):
    ok, err = create_role(db, code="temp_role", label="موقت", copy_from="user")
    assert ok, err
    ok, err = delete_role(db, "temp_role")
    assert ok, err
    assert db.query(Role).filter(Role.code == "temp_role").first() is None


def test_custom_role_reaches_only_granted_pages(client, db, make_user):
    ok, err = create_role(db, code="report_only", label="فقط گزارش", copy_from="user")
    assert ok, err
    ok, err = set_role_permission(
        db, "report_only", "view_reports", True, reason="تست", created_by="SYS",
    )
    assert ok, err

    creds = make_user(role="report_only")
    login_as(client, creds["national_code"])

    reports = client.get("/reports", headers=HTML_ACCEPT)
    assert reports.status_code == 200

    denied = client.get("/admin/permissions", headers=HTML_ACCEPT, follow_redirects=False)
    assert denied.status_code == 403


def test_roles_tab_create_form(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    page = client.get("/admin/permissions?tab=roles", headers=HTML_ACCEPT)
    assert page.status_code == 200
    assert 'action="/admin/permissions/roles/create"' in page.text
    token = _csrf_from_html(page.text)
    resp = client.post(
        "/admin/permissions/roles/create",
        data={
            "label": "نگهبان",
            "code": "guard",
            "description": "",
            "copy_from": "user",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "role=guard" in resp.headers["location"]
    assert db.query(Role).filter(Role.code == "guard").first() is not None
