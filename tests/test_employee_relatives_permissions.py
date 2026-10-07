"""Permission tests for employee relatives admin routes."""
from models.user_permission import UserPermission
from web.services.employee_relative_service import create_relative
from .conftest import login_as


def _revoke(db, user_id: str, permission: str):
    db.add(UserPermission(
        user_id=user_id,
        permission=permission,
        granted=False,
    ))
    db.commit()


def test_admin_has_manage_by_default(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/add",
        data={
            "first_name": "سارا",
            "last_name": "تست",
            "relationship_type": "CHILD",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]


def test_manage_revoked_returns_403(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "manage_employee_relatives")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/add",
        data={
            "first_name": "سارا",
            "last_name": "تست",
            "relationship_type": "CHILD",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_view_without_manage_can_see_section_but_not_mutate(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "manage_employee_relatives")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="فرزند",
        last_name="نمونه",
        relationship_type="CHILD",
    )

    resp = client.get(
        f"/admin/profile/{target['user_id']}",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "بستگان" in resp.text
    assert "فرزند نمونه" in resp.text
    assert "adminAddRelativeModal" not in resp.text

    resp_del = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/delete",
        follow_redirects=False,
    )
    assert resp_del.status_code == 403


def test_both_perms_revoked_hides_section(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "view_employee_relatives")
    _revoke(db, admin["user_id"], "manage_employee_relatives")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)
    create_relative(
        db,
        user_id=target["user_id"],
        first_name="مخفی",
        last_name="شده",
        relationship_type="CHILD",
    )

    resp = client.get(
        f"/admin/profile/{target['user_id']}",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "مخفی شده" not in resp.text
    # Section title may still appear elsewhere; ensure add modal/action absent
    assert "adminAddRelativeModal" not in resp.text
    assert "/relatives/add" not in resp.text


def test_regular_user_cannot_access_admin_routes(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    resp = client.post(
        f"/admin/profile/{me['user_id']}/relatives/add",
        data={
            "first_name": "سارا",
            "last_name": "تست",
            "relationship_type": "CHILD",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 403, 307)


def test_verify_revoked_returns_403(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "verify_employee_relatives")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
    )
    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/verify",
        follow_redirects=False,
    )
    assert resp.status_code == 403
