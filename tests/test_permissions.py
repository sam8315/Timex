"""Tests for the per-user permission override system (grant / revoke / reset).

Covers the logic in web.permissions (get_effective_permissions, set/remove)
and the HTTP enforcement that require_admin routes now apply via
enforce_permission — i.e. that revoking view_reports from an admin really
blocks /reports, and that granting a super-only permission opens it.
"""
import re

import jdatetime
import pytest

from .conftest import login_as

from models.user_permission import UserPermission
from web.permissions import (
    ALL_PERMISSIONS,
    get_effective_permissions,
    get_permission_history,
    has_permission,
    remove_user_permission,
    set_user_permission,
)


# ---------------------------------------------------------------------------
# Function-level: effective-permission computation & overrides
# ---------------------------------------------------------------------------
def test_grant_adds_super_only_permission_to_admin(db, make_user):
    creds = make_user(role="admin")
    from models.user import User
    user = db.query(User).filter(User.user_id == creds["user_id"]).first()

    # add_attendance is admin:False, so an admin does not have it by default
    assert not has_permission(db, user, "add_attendance")

    assert set_user_permission(db, creds["user_id"], "add_attendance", True,
                               created_by=creds["user_id"]) is True
    assert has_permission(db, user, "add_attendance") is True
    assert "add_attendance" in get_effective_permissions(db, user)


def test_revoke_removes_role_default_permission(db, make_user):
    creds = make_user(role="admin")
    from models.user import User
    user = db.query(User).filter(User.user_id == creds["user_id"]).first()

    assert has_permission(db, user, "view_reports")  # admin default yes

    set_user_permission(db, creds["user_id"], "view_reports", False,
                        reason="عدم نیاز", created_by=creds["user_id"])
    assert has_permission(db, user, "view_reports") is False
    assert "view_reports" not in get_effective_permissions(db, user)


def test_revoke_applies_to_super_admin_too(db, make_user):
    creds = make_user(role="super_admin")
    from models.user import User
    user = db.query(User).filter(User.user_id == creds["user_id"]).first()

    set_user_permission(db, creds["user_id"], "view_contracts", False,
                        created_by=creds["user_id"])
    assert has_permission(db, user, "view_contracts") is False


def test_reset_restores_role_default(db, make_user):
    creds = make_user(role="admin")
    from models.user import User
    user = db.query(User).filter(User.user_id == creds["user_id"]).first()

    set_user_permission(db, creds["user_id"], "view_reports", False,
                        created_by=creds["user_id"])
    assert has_permission(db, user, "view_reports") is False

    assert remove_user_permission(db, creds["user_id"], "view_reports",
                                  created_by=creds["user_id"]) is True
    assert has_permission(db, user, "view_reports") is True  # role default back


def test_grant_then_revoke_keeps_single_row(db, make_user):
    """یک ردیف در جدول فعلی؛ تاریخچه جداگانه رشد میکند."""
    creds = make_user(role="user")
    set_user_permission(db, creds["user_id"], "view_reports", True,
                        created_by=creds["user_id"])
    set_user_permission(db, creds["user_id"], "view_reports", False,
                        created_by=creds["user_id"])

    rows = db.query(UserPermission).filter(
        UserPermission.user_id == creds["user_id"],
        UserPermission.permission == "view_reports").all()
    assert len(rows) == 1
    assert rows[0].granted is False


def test_history_logs_grant_revoke_reset(db, make_user):
    creds = make_user(role="admin")
    set_user_permission(db, creds["user_id"], "view_reports", False,
                        reason="r", created_by=creds["user_id"])
    set_user_permission(db, creds["user_id"], "view_reports", True,
                        reason="g", created_by=creds["user_id"])
    remove_user_permission(db, creds["user_id"], "view_reports",
                           reason="x", created_by=creds["user_id"])

    history = get_permission_history(db, creds["user_id"])
    actions = [h.action for h in history if h.permission == "view_reports"]
    # جدیدترین اول: reset (آخرین)، سپس grant، سپس revoke
    assert actions[:3] == ["reset", "grant", "revoke"]
    # دلیل ثبت شده است
    by_action = {h.action: h for h in history if h.permission == "view_reports"}
    assert by_action["revoke"].reason == "r"
    assert by_action["grant"].reason == "g"
    assert by_action["reset"].reason == "x"
    assert by_action["grant"].created_by == creds["user_id"]


def test_invalid_permission_rejected(db, make_user):
    creds = make_user(role="admin")
    assert set_user_permission(db, creds["user_id"], "no_such_perm", True) is False


# ---------------------------------------------------------------------------
# HTTP-level: enforce_permission inside require_admin routes
# ---------------------------------------------------------------------------
def test_revoked_admin_blocked_from_reports(client, db, make_user):
    creds = make_user(role="admin")
    set_user_permission(db, creds["user_id"], "view_reports", False,
                        created_by="SYS")
    db.commit()

    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    assert client.get("/reports").status_code == 403


def test_reset_unblocks_admin_reports(client, db, make_user):
    creds = make_user(role="admin")
    set_user_permission(db, creds["user_id"], "view_reports", False)
    db.commit()
    remove_user_permission(db, creds["user_id"], "view_reports")
    db.commit()

    login_as(client, creds["national_code"])
    assert client.get("/reports").status_code == 200


def test_granted_admin_can_add_attendance(client, db, make_user):
    """add_attendance admin:False — grant آن مسیر را برای مدیریت باز میکند."""
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])

    # بدون grant → 403
    today_j = jdatetime.date.today().strftime("%Y/%m/%d")
    denied = client.post(
        "/admin/attendance/edit/add",
        data={"user_id": creds["user_id"], "date_str": today_j,
              "time_str": "09:00", "punch": "1"},
        follow_redirects=False,
    )
    assert denied.status_code == 403

    # با grant → عملیات میپذیرد (302)
    set_user_permission(db, creds["user_id"], "add_attendance", True,
                        created_by="SYS")
    db.commit()
    allowed = client.post(
        "/admin/attendance/edit/add",
        data={"user_id": creds["user_id"], "date_str": today_j,
              "time_str": "09:00", "punch": "1"},
        follow_redirects=False,
    )
    assert allowed.status_code == 302


def _revoke_contract_mutations(db, user_id):
    for perm in ("add_contracts", "edit_contracts", "delete_contracts"):
        set_user_permission(db, user_id, perm, False, created_by="SYS")
    db.commit()


def test_view_only_admin_can_list_contracts_but_not_mutate(client, db, make_user):
    """view_contracts بدون add/edit/delete فقط لیست را باز می‌کند."""
    from models.contract import Contract

    admin = make_user(role="admin")
    target = make_user(role="user", balance_al=None)
    _revoke_contract_mutations(db, admin["user_id"])

    login_as(client, admin["national_code"])
    assert client.get("/admin/contracts").status_code == 200

    today_j = jdatetime.date.today().strftime("%Y/%m/%d")
    add_denied = client.post(
        "/admin/contracts/add",
        data={
            "user_id": target["user_id"],
            "contract_type_code": "4",
            "start_date_str": today_j,
            "end_date_str": "",
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
            "buyback_leave_days": "0",
        },
        follow_redirects=False,
    )
    assert add_denied.status_code == 403

    contract = (
        db.query(Contract)
        .filter(Contract.user_id == target["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract is not None

    edit_denied = client.post(
        f"/admin/contracts/{contract.id}/edit",
        data={
            "contract_type_code": "4",
            "start_date_str": today_j,
            "end_date_str": "",
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
            "buyback_leave_days": "0",
            "description": "",
        },
        follow_redirects=False,
    )
    assert edit_denied.status_code == 403

    delete_denied = client.post(
        f"/admin/contracts/{contract.id}/delete",
        follow_redirects=False,
    )
    assert delete_denied.status_code == 403


def test_contract_mutation_permissions_open_matching_routes(client, db, make_user):
    """grant جداگانهٔ add/edit/delete مسیر مربوطه را باز می‌کند."""
    from models.contract import Contract

    admin = make_user(role="admin")
    target = make_user(role="user", balance_al=None)
    _revoke_contract_mutations(db, admin["user_id"])
    login_as(client, admin["national_code"])

    today_j = jdatetime.date.today()
    start_j = today_j.replace(day=1).strftime("%Y/%m/%d")
    # قرارداد fixture ممکن است هم‌پوشانی بسازد؛ برای add یک کاربر بدون قرارداد بسازیم
    db.query(Contract).filter(Contract.user_id == target["user_id"]).delete()
    db.commit()

    set_user_permission(db, admin["user_id"], "add_contracts", True, created_by="SYS")
    db.commit()
    add_ok = client.post(
        "/admin/contracts/add",
        data={
            "user_id": target["user_id"],
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": "",
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
            "buyback_leave_days": "0",
        },
        follow_redirects=False,
    )
    assert add_ok.status_code == 302

    db.expire_all()
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == target["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract is not None

    set_user_permission(db, admin["user_id"], "edit_contracts", True, created_by="SYS")
    db.commit()
    edit_ok = client.post(
        f"/admin/contracts/{contract.id}/edit",
        data={
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": "",
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
            "buyback_leave_days": "0",
            "description": "perm-test",
        },
        follow_redirects=False,
    )
    assert edit_ok.status_code == 302

    set_user_permission(db, admin["user_id"], "delete_contracts", True, created_by="SYS")
    db.commit()
    delete_ok = client.post(
        f"/admin/contracts/{contract.id}/delete",
        follow_redirects=False,
    )
    assert delete_ok.status_code == 302


# ---------------------------------------------------------------------------
# CSRF on the toggle endpoint
# ---------------------------------------------------------------------------
def _csrf_from_html(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf hidden input not found in page"
    return m.group(1)


def test_toggle_rejects_missing_csrf(client, db, make_user):
    target = make_user(role="admin")
    super_user = make_user(role="super_admin")
    login_as(client, super_user["national_code"])

    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={"permission": "view_reports", "action": "revoke", "csrf_token": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    # هیچ تغییری اعمال نشده
    assert db.query(UserPermission).filter(
        UserPermission.user_id == target["user_id"],
        UserPermission.permission == "view_reports").first() is None


def test_toggle_accepts_valid_csrf_and_writes_history(client, db, make_user):
    target = make_user(role="admin")
    super_user = make_user(role="super_admin")
    login_as(client, super_user["national_code"])

    page = client.get(f"/admin/permissions/{target['user_id']}")
    assert page.status_code == 200
    token = _csrf_from_html(page.text)

    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={"permission": "view_reports", "action": "revoke",
              "reason": "تست", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    row = db.query(UserPermission).filter(
        UserPermission.user_id == target["user_id"],
        UserPermission.permission == "view_reports").first()
    assert row is not None and row.granted is False

    history = get_permission_history(db, target["user_id"])
    assert history and history[0].action == "revoke"
    assert history[0].reason == "تست"