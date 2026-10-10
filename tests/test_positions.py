"""Tests for Position CRUD, employee FK, users filter, and print."""
import re

from .conftest import login_as
from models.user import User
from models.employee import Employee
from models.position import Position
from models.employee_region import EmployeeRegion

HTML_ACCEPT = {"Accept": "text/html"}


def _cleanup_users(db, *uids):
    for uid in uids:
        try:
            db.query(EmployeeRegion).filter(EmployeeRegion.user_id == uid).delete()
            db.query(User).filter(User.user_id == uid).delete()
            db.commit()
        except Exception:
            db.rollback()


def _cleanup_positions(db, *names):
    for name in names:
        try:
            db.query(Position).filter(Position.name == name).delete()
            db.commit()
        except Exception:
            db.rollback()


def _make_position(db, name="سمت-تست", is_active=True, sort_order=0):
    _cleanup_positions(db, name)
    pos = Position(name=name, is_active=is_active, sort_order=sort_order)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------
def test_position_create_edit_toggle_delete(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    _cleanup_positions(db, "سمت الف", "سمت الف ویرایش")

    resp = client.post(
        "/admin/positions/add",
        data={"name": "سمت الف", "sort_order": "1", "is_active": "on"},
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    pos = db.query(Position).filter(Position.name == "سمت الف").first()
    assert pos is not None
    assert pos.is_active is True

    resp = client.post(
        f"/admin/positions/{pos.id}/edit",
        data={"name": "سمت الف ویرایش", "sort_order": "2", "is_active": "on"},
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    db.refresh(pos)
    assert pos.name == "سمت الف ویرایش"
    assert pos.sort_order == 2

    resp = client.post(
        f"/admin/positions/{pos.id}/toggle",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    db.refresh(pos)
    assert pos.is_active is False

    resp = client.post(
        f"/admin/positions/{pos.id}/delete",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    assert "success" in (resp.headers.get("location") or "")
    assert db.query(Position).filter(Position.id == pos.id).first() is None


def test_position_delete_rejected_when_in_use(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    pos = _make_position(db, "سمت استفاده‌شده")

    u = make_user(role="user")
    emp = db.query(Employee).filter(Employee.user_id == u["user_id"]).first()
    emp.position_id = pos.id
    db.commit()

    resp = client.post(
        f"/admin/positions/{pos.id}/delete",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    assert "error" in (resp.headers.get("location") or "")
    assert db.query(Position).filter(Position.id == pos.id).first() is not None

    emp.position_id = None
    db.commit()
    _cleanup_positions(db, "سمت استفاده‌شده")


# ---------------------------------------------------------------------------
# Create user with position_id
# ---------------------------------------------------------------------------
def _csrf(client, url):
    resp = client.get(url, headers=HTML_ACCEPT)
    assert resp.status_code == 200
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    assert m, "CSRF token not found"
    return m.group(1)


def _valid_create(**overrides):
    data = {
        "user_id": "POS-USER-01",
        "name": "کاربر سمت",
        "first_name": "کاربر",
        "last_name": "سمت",
        "father_name": "",
        "national_code": "1098765432",
        "birth_date_str": "",
        "gender": "",
        "marital_status": "",
        "email": "",
        "hire_date_str": "",
        "membership_type_code": "1",
        "department_id": "",
        "position_id": "",
        "notes": "",
        "is_active": "on",
    }
    data.update(overrides)
    return data


def test_create_user_with_valid_position(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    pos = _make_position(db, "برنامه‌نویس تست")
    _cleanup_users(db, "POS-USER-01")

    token = _csrf(client, "/admin/users/create")
    resp = client.post(
        "/admin/users/create",
        data=_valid_create(csrf_token=token, position_id=str(pos.id)),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    emp = db.query(Employee).filter(Employee.user_id == "POS-USER-01").first()
    assert emp is not None
    assert emp.position_id == pos.id
    assert emp.position_name == "برنامه‌نویس تست"
    _cleanup_users(db, "POS-USER-01")
    _cleanup_positions(db, "برنامه‌نویس تست")


def test_create_user_without_position(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    _cleanup_users(db, "POS-USER-01")

    token = _csrf(client, "/admin/users/create")
    resp = client.post(
        "/admin/users/create",
        data=_valid_create(csrf_token=token, position_id=""),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    emp = db.query(Employee).filter(Employee.user_id == "POS-USER-01").first()
    assert emp is not None
    assert emp.position_id is None
    _cleanup_users(db, "POS-USER-01")


def test_create_user_invalid_position(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    _cleanup_users(db, "POS-USER-01")

    token = _csrf(client, "/admin/users/create")
    resp = client.post(
        "/admin/users/create",
        data=_valid_create(csrf_token=token, position_id="999999"),
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "یافت نشد" in resp.text or "نامعتبر" in resp.text
    assert db.query(User).filter(User.user_id == "POS-USER-01").first() is None


def test_create_user_inactive_position_rejected(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    pos = _make_position(db, "سمت غیرفعال تست", is_active=False)
    _cleanup_users(db, "POS-USER-01")

    token = _csrf(client, "/admin/users/create")
    resp = client.post(
        "/admin/users/create",
        data=_valid_create(csrf_token=token, position_id=str(pos.id)),
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "غیرفعال" in resp.text
    assert db.query(User).filter(User.user_id == "POS-USER-01").first() is None
    _cleanup_positions(db, "سمت غیرفعال تست")


def test_edit_user_position(client, db, make_user):
    admin = make_user(role="super_admin")
    login_as(client, admin["national_code"])
    pos = _make_position(db, "سمت ویرایش کاربر")
    target = make_user(role="user")
    emp = db.query(Employee).filter(Employee.user_id == target["user_id"]).first()

    resp = client.post(
        f"/admin/profile/{target['user_id']}/edit",
        data={
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "father_name": emp.father_name or "",
            "national_code": emp.national_code or "",
            "birth_date_str": "",
            "gender": emp.gender or "",
            "marital_status": emp.marital_status or "",
            "email": emp.email or "",
            "hire_date_str": "",
            "membership_type_code": emp.membership_type_code or "",
            "department_id": str(emp.department_id or ""),
            "position_id": str(pos.id),
            "notes": "",
            "is_active": "on",
            "termination_date_str": "",
            "termination_reason": "",
        },
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    db.refresh(emp)
    assert emp.position_id == pos.id
    emp.position_id = None
    db.commit()
    _cleanup_positions(db, "سمت ویرایش کاربر")


# ---------------------------------------------------------------------------
# Users filter + print
# ---------------------------------------------------------------------------
def test_users_filter_by_position(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    pos = _make_position(db, "فیلتر سمت")
    u1 = make_user(role="user")
    u2 = make_user(role="user")
    e1 = db.query(Employee).filter(Employee.user_id == u1["user_id"]).first()
    e1.position_id = pos.id
    db.commit()

    resp = client.get(
        f"/admin/users?position_id={pos.id}",
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 200
    assert u1["user_id"] in resp.text
    assert u2["user_id"] not in resp.text

    e1.position_id = None
    db.commit()
    _cleanup_positions(db, "فیلتر سمت")


def test_users_print_selected_fields_and_ids(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    pos = _make_position(db, "چاپ سمت")
    u1 = make_user(role="user")
    u2 = make_user(role="user")
    e1 = db.query(Employee).filter(Employee.user_id == u1["user_id"]).first()
    e1.position_id = pos.id
    db.commit()

    resp = client.post(
        "/admin/users/print",
        data={
            "user_ids": u1["user_id"],
            "fields": ["user_id", "name", "position"],
        },
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 200
    assert u1["user_id"] in resp.text
    assert u2["user_id"] not in resp.text
    assert "چاپ سمت" in resp.text
    # Header for national_code should be absent
    assert ">کد ملی<" not in resp.text
    assert ">سمت<" in resp.text

    e1.position_id = None
    db.commit()
    _cleanup_positions(db, "چاپ سمت")


def test_users_print_requires_admin(client, db, make_user):
    normal = make_user(role="user")
    login_as(client, normal["national_code"])
    resp = client.post(
        "/admin/users/print",
        data={"user_ids": normal["user_id"], "fields": "user_id"},
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code in (302, 303, 401, 403)
