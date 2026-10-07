"""Self-service relatives UI on /profile."""
from urllib.parse import unquote

from web.services.employee_relative_service import create_relative, list_relatives
from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


def test_profile_renders_relatives_section(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    create_relative(
        db,
        user_id=me["user_id"],
        first_name="سارا",
        last_name="تستی",
        relationship_type="CHILD",
        status="PENDING",
    )
    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "بستگان من" in resp.text
    assert "سارا تستی" in resp.text
    assert "addRelativeModal" in resp.text
    assert 'data-jalali-initial="false"' in resp.text


def test_self_add_relative_pending(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    resp = client.post(
        "/profile/relatives/add",
        data={
            "first_name": "نیما",
            "last_name": "کاربر",
            "relationship_type": "CHILD",
            "is_studying": "",
            "is_disabled": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = list_relatives(db, me["user_id"])
    assert len(rows) == 1
    assert rows[0].status == "PENDING"
    assert rows[0].first_name == "نیما"


def test_self_cannot_delete_verified(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    rel = create_relative(
        db,
        user_id=me["user_id"],
        first_name="تأیید",
        last_name="شده",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by="admin1",
    )
    resp = client.post(
        f"/profile/relatives/{rel.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = unquote(resp.headers["location"])
    assert "error=" in loc
    assert list_relatives(db, me["user_id"])


def test_self_update_resets_to_pending(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    rel = create_relative(
        db,
        user_id=me["user_id"],
        first_name="قدیم",
        last_name="نام",
        relationship_type="SPOUSE",
        status="VERIFIED",
        created_by="admin1",
    )
    resp = client.post(
        f"/profile/relatives/{rel.id}/update",
        data={
            "first_name": "جدید",
            "last_name": "نام",
            "relationship_type": "SPOUSE",
            "is_studying": "",
            "is_disabled": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(rel)
    assert rel.first_name == "جدید"
    assert rel.status == "PENDING"
