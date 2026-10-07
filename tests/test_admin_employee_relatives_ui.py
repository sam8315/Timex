"""Admin UI tests for employee relatives on /admin/profile/{id}."""
from datetime import date
from urllib.parse import unquote

from web.services.employee_relative_service import create_relative, list_relatives
from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


def _login_super(client, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    return super_u


def _profile(client, target_user_id):
    resp = client.get(
        f"/admin/profile/{target_user_id}", headers=HTML_ACCEPT
    )
    assert resp.status_code == 200, resp.status_code
    return resp.text


def test_admin_profile_renders_relatives_section(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    create_relative(
        db,
        user_id=target["user_id"],
        first_name="سارا",
        last_name="احمدی",
        relationship_type="CHILD",
        birth_date=date(2018, 3, 15),
    )

    body = _profile(client, target["user_id"])
    assert "بستگان" in body
    assert "سارا احمدی" in body
    assert "فرزند" in body
    assert f"/admin/profile/{target['user_id']}/relatives/add" in body
    assert "adminAddRelativeModal" in body
    # existing sections still present
    assert "حساب‌های بانکی" in body


def test_admin_profile_relatives_empty_state(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    body = _profile(client, target["user_id"])
    assert "بستگان" in body
    assert "هیچ فرد وابسته‌ای برای این کارمند ثبت نشده است" in body


def test_admin_add_relative_via_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/add",
        data={
            "first_name": "نیما",
            "last_name": "کاظمی",
            "relationship_type": "CHILD",
            "gender": "M",
            "is_studying": "true",
            "employment_status": "",
            "insurance_status": "",
            "is_disabled": "",
            "marital_status": "",
            "birth_date": "1395/01/01",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = unquote(resp.headers["location"])
    assert "success=" in loc

    rows = list_relatives(db, target["user_id"])
    assert len(rows) == 1
    assert rows[0].first_name == "نیما"
    assert rows[0].is_studying is True
    assert rows[0].birth_date is not None


def test_admin_update_relative_via_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="قدیم",
        last_name="نام",
        relationship_type="SPOUSE",
    )

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/update",
        data={
            "first_name": "جدید",
            "last_name": "نام",
            "relationship_type": "SPOUSE",
            "marital_status": "M",
            "gender": "F",
            "is_studying": "",
            "is_disabled": "false",
            "employment_status": "unemployed",
            "insurance_status": "uninsured",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(rel)
    assert rel.first_name == "جدید"
    assert rel.marital_status == "M"
    assert rel.employment_status == "unemployed"
    assert rel.is_disabled is False


def test_admin_soft_delete_via_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="حذف",
        last_name="شود",
        relationship_type="OTHER",
    )

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert list_relatives(db, target["user_id"]) == []
    body = _profile(client, target["user_id"])
    assert "حذف شود" not in body
    assert "هیچ فرد وابسته‌ای برای این کارمند ثبت نشده است" in body


def test_validation_error_redirects_with_error(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/add",
        data={
            "first_name": "الف",
            "last_name": "ب",
            "relationship_type": "COUSIN",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = unquote(resp.headers["location"])
    assert "error=" in loc


def test_edit_modal_present_for_existing_relative(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="ویرایش",
        last_name="مودال",
        relationship_type="FATHER",
    )
    body = _profile(client, target["user_id"])
    assert f"adminEditRelativeModal-{rel.id}" in body
    assert f"/relatives/{rel.id}/update" in body


def test_add_modal_dates_have_no_initial_flag(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    body = _profile(client, target["user_id"])
    assert 'data-jalali-initial="false"' in body
    assert "relative-dep-disability" in body
    assert "relative-deceased-toggle" in body


def test_admin_add_creates_verified(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/add",
        data={
            "first_name": "ادمین",
            "last_name": "ثبت",
            "relationship_type": "CHILD",
            "is_studying": "",
            "is_disabled": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = list_relatives(db, target["user_id"])
    assert len(rows) == 1
    assert rows[0].status == "VERIFIED"


def test_admin_verify_and_reject(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="منتظر",
        last_name="تأیید",
        relationship_type="CHILD",
        status="PENDING",
    )
    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/verify",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(rel)
    assert rel.status == "VERIFIED"

    resp2 = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/reject",
        data={"rejection_reason": "مدارک ناقص"},
        follow_redirects=False,
    )
    assert resp2.status_code == 302
    db.refresh(rel)
    assert rel.status == "REJECTED"
    assert rel.rejection_reason == "مدارک ناقص"
