"""Tests for user+employee creation (Phase 7).

Atomic combined form: create User + Employee in one POST.
Rules:
- Super-admin only (require_super_admin gate).
- CSRF token enforced (check_csrf_token).
- Atomic: if any DB write fails, both User and Employee are rolled back.
- user_id: 1-50 chars, alphanumeric + _ - only.
- national_code: exactly 10 digits.
- first_name, last_name: non-empty.
- Duplicate user_id or national_code → error, no rows created.
- After creation: redirect to /admin/profile/{uid}?created=1.
- Initial password = national_code hash + must_change_password=True.

Note: the test DB is persistent across pytest runs (create_all, no drop), so
every test cleans up the users it creates.
"""
import re
from .conftest import login_as

from models.user import User
from models.employee import Employee
from models.employee_region import EmployeeRegion

HTML_ACCEPT = {"Accept": "text/html"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _csrf(client, url):
    """Extract CSRF token from form page."""
    resp = client.get(url, headers=HTML_ACCEPT)
    assert resp.status_code == 200
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.text)
    assert m, "CSRF token not found"
    return m.group(1)


def _cleanup(db, *uids):
    """Delete test-created users (mirrors make_user teardown: region, then user)."""
    for uid in uids:
        try:
            db.query(EmployeeRegion).filter(EmployeeRegion.user_id == uid).delete()
            db.query(User).filter(User.user_id == uid).delete()
            db.commit()
        except Exception:
            db.rollback()


def _seed_user(db, user_id, national_code, name="Seed"):
    """Insert a User + Employee row directly (setup for conflict tests).

    Self-healing: the test DB is persistent, so first remove any prior row
    with the same user_id or national_code (leftover from an interrupted run).
    """
    from web.security import hash_password
    _cleanup(db, user_id)
    try:
        db.query(Employee).filter(Employee.national_code == national_code).delete()
        db.commit()
    except Exception:
        db.rollback()
    u = User(user_id=user_id, name=name, password_hash=hash_password("1234567890"),
             must_change_password=False, role="user", web_enabled=True)
    db.add(u)
    db.add(Employee(user_id=user_id, first_name="Seed", last_name=name,
                     national_code=national_code))
    db.commit()


def _valid_payload(**overrides):
    data = {
        "user_id": "TEST-CREATE-01",
        "name": "علی رضایی",
        "first_name": "علی",
        "last_name": "رضایی",
        "father_name": "محمد",
        "national_code": "1234567890",
        "birth_date_str": "1370/05/15",
        "gender": "M",
        "marital_status": "M",
        "email": "ali@test.com",
        "hire_date_str": "1400/01/01",
        "department": "1",
        "position": "برنامه‌نویس",
        "region_code": "NORMAL",
        "notes": "تست ایجاد",
        "is_active": "on",
    }
    data.update(overrides)
    return data


def _create(client, data):
    """POST the create form; returns the response."""
    return client.post("/admin/users/create", data=data, follow_redirects=False)


# ---------------------------------------------------------------------------
# 1. Success
# ---------------------------------------------------------------------------
def test_create_success(client, db, make_user):
    """Valid POST creates both User + Employee, redirects to profile."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    resp = _create(client, _valid_payload(csrf_token=token))
    assert resp.status_code == 302
    assert "/admin/profile/TEST-CREATE-01?created=1" in resp.headers["location"]

    user = db.query(User).filter(User.user_id == "TEST-CREATE-01").first()
    assert user is not None
    assert user.role == "user"
    assert user.must_change_password is True
    assert user.web_enabled is True

    emp = db.query(Employee).filter(Employee.user_id == "TEST-CREATE-01").first()
    assert emp is not None
    assert emp.first_name == "علی"
    assert emp.last_name == "رضایی"
    assert emp.national_code == "1234567890"
    assert emp.is_active is True

    # Initial password = national_code hash
    from web.security import verify_password
    assert verify_password("1234567890", user.password_hash)

    _cleanup(db, "TEST-CREATE-01")


def test_login_redirects_to_change_password(client, db, make_user):
    """New user logging in with national_code must be forced to /change-password."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    _create(client, _valid_payload(csrf_token=token))

    # Log out, then log in as the new user
    client.cookies.clear()
    resp = client.post(
        "/login",
        data={"national_code": "1234567890", "password": "1234567890"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/change-password" in resp.headers["location"]

    _cleanup(db, "TEST-CREATE-01")


# ---------------------------------------------------------------------------
# 2. Duplicate user_id
# ---------------------------------------------------------------------------
def test_duplicate_user_id(client, db, make_user):
    """POST with existing user_id → error, no new User row."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    _seed_user(db, "TEST-DUP-UID", "9999999999", name="Dup")

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(user_id="TEST-DUP-UID", national_code="9999999999",
                          csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200  # re-rendered form
    assert "قبلاً ثبت شده" in resp.text

    assert db.query(User).filter(User.user_id == "TEST-DUP-UID").count() == 1
    _cleanup(db, "TEST-DUP-UID")


# ---------------------------------------------------------------------------
# 3. Duplicate national_code
# ---------------------------------------------------------------------------
def test_duplicate_national_code(client, db, make_user):
    """POST with existing national_code → error, no new rows."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    _seed_user(db, "EXISTING-EMP", "5555555555", name="Exist")

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(user_id="NEW-UNIQUE", national_code="5555555555",
                          csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "کد ملی قبلاً ثبت شده" in resp.text
    assert db.query(User).filter(User.user_id == "NEW-UNIQUE").first() is None

    _cleanup(db, "EXISTING-EMP", "NEW-UNIQUE")


# ---------------------------------------------------------------------------
# 4. Invalid user_id / national_code
# ---------------------------------------------------------------------------
def test_invalid_user_id(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(user_id="x" * 51, csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "۱ تا ۵۰ کاراکتر" in resp.text

    token2 = _csrf(client, "/admin/users/create")
    data = _valid_payload(user_id="bad id!", csrf_token=token2)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "فقط حروف، عدد، زیرخط و خط تیره" in resp.text


def test_invalid_national_code(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(national_code="12345", csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "۱۰ رقم" in resp.text


# ---------------------------------------------------------------------------
# 5. Atomicity — no partial rows
# ---------------------------------------------------------------------------
def test_atomicity_no_partial_on_integrity_error(client, db, make_user):
    """If IntegrityError occurs mid-transaction, nothing is created."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    _seed_user(db, "ATOMIC-TEST", "9876543210", name="Atomic")

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(user_id="ATOMIC-TEST", national_code="1111111111",
                          csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200  # re-rendered with error

    # Only the original user exists; no orphan Employee with the new national code
    assert db.query(User).filter(User.user_id == "ATOMIC-TEST").count() == 1
    assert db.query(Employee).filter(
        Employee.user_id == "ATOMIC-TEST",
        Employee.national_code == "1111111111"
    ).first() is None

    _cleanup(db, "ATOMIC-TEST")


# ---------------------------------------------------------------------------
# 6. Profile renders after creation
# ---------------------------------------------------------------------------
def test_profile_renders_after_creation(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    _create(client, _valid_payload(csrf_token=token))

    resp = client.get("/admin/profile/TEST-CREATE-01", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "علی" in resp.text

    _cleanup(db, "TEST-CREATE-01")


# ---------------------------------------------------------------------------
# 7. Super-admin gate
# ---------------------------------------------------------------------------
def test_admin_role_gets_403(client, db, make_user):
    """Non-super-admin cannot access the create form."""
    adm = make_user(role="admin")
    login_as(client, adm["national_code"])

    resp = client.get("/admin/users/create", headers=HTML_ACCEPT)
    assert resp.status_code == 403


def test_admin_role_post_gets_403(client, db, make_user):
    """Non-super-admin cannot submit the create form."""
    adm = make_user(role="admin")
    login_as(client, adm["national_code"])

    data = _valid_payload(csrf_token="anything")
    resp = _create(client, data)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 8. CSRF enforcement
# ---------------------------------------------------------------------------
def test_missing_csrf_token_rejected(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    data = _valid_payload()  # no csrf_token
    resp = _create(client, data)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 9. Regression — /admin/users still works
# ---------------------------------------------------------------------------
def test_users_list_still_works(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    resp = client.get("/admin/users", headers=HTML_ACCEPT)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 10. GET form renders with all fields
# ---------------------------------------------------------------------------
def test_create_form_renders(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    resp = client.get("/admin/users/create", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "ایجاد کاربر جدید" in resp.text
    assert 'name="csrf_token"' in resp.text
    assert 'name="user_id"' in resp.text
    assert 'name="national_code"' in resp.text
    assert 'name="first_name"' in resp.text
    assert 'name="last_name"' in resp.text
    assert 'name="region_code"' in resp.text
    assert "ایجاد کاربر" in resp.text


# ---------------------------------------------------------------------------
# 11. Empty required fields
# ---------------------------------------------------------------------------
def test_empty_first_name(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(first_name="", csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "نام الزامی است" in resp.text


def test_empty_last_name(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    data = _valid_payload(last_name="", csrf_token=token)
    resp = _create(client, data)
    assert resp.status_code == 200
    assert "نام خانوادگی الزامی است" in resp.text


# ---------------------------------------------------------------------------
# 12. Users list shows the new user after creation
# ---------------------------------------------------------------------------
def test_new_user_appears_in_users_list(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])

    token = _csrf(client, "/admin/users/create")
    _create(client, _valid_payload(csrf_token=token))

    resp = client.get("/admin/users?show_all=1", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "TEST-CREATE-01" in resp.text

    _cleanup(db, "TEST-CREATE-01")
