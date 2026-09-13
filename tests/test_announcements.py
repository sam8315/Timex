"""Announcement domain tests (unit / UI / API / auth / CSRF / unread / seen)."""
from tests.conftest import login_as


def test_model_import_and_schema(db):
    from models.system_announcement import SystemAnnouncement
    from models.user_announcement import UserAnnouncement

    assert SystemAnnouncement.__tablename__ == "system_announcements"
    assert UserAnnouncement.__tablename__ == "user_announcements"


def test_service_unread_and_seen(db, make_user):
    from models.system_announcement import SystemAnnouncement
    from web.services.announcement_service import (
        get_unread_count,
        list_history,
        mark_as_seen,
    )

    u = make_user(role="user")
    ann = SystemAnnouncement(
        title="T",
        content="C",
        is_active=True,
        announcement_type="general",
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)

    count_before = get_unread_count(db, u["user_id"])
    assert mark_as_seen(db, u["user_id"], ann.id) is True
    assert get_unread_count(db, u["user_id"]) == count_before - 1
    assert len(list_history(db, u["user_id"])) >= 1

    # Idempotent acknowledgement.
    assert mark_as_seen(db, u["user_id"], ann.id) is True
    db.query(SystemAnnouncement).filter_by(id=ann.id).delete()
    db.commit()


def test_api_unread_unauthenticated(client):
    resp = client.get("/api/announcements/unread")
    assert resp.status_code in (307, 302, 401, 403)


def test_api_mark_seen_csrf_protected(client, db, make_user):
    from models.system_announcement import SystemAnnouncement

    u = make_user(role="user")
    ann = SystemAnnouncement(title="CSRF", content="C", is_active=True)
    db.add(ann)
    db.commit()
    db.refresh(ann)

    login_as(client, u["national_code"])
    resp = client.post(
        f"/api/announcements/{ann.id}/seen",
        data={"csrf_token": "bad"},
    )
    assert resp.status_code == 403

    db.query(SystemAnnouncement).filter_by(id=ann.id).delete()
    db.commit()


def test_user_page_announcements(client, make_user):
    u = make_user(role="user")
    login_as(client, u["national_code"])
    resp = client.get("/announcements")
    assert resp.status_code == 200
    assert "تازه‌های سیستم" in resp.text


def test_user_page_acknowledgement_requires_csrf(client, db, make_user):
    from models.system_announcement import SystemAnnouncement

    u = make_user(role="user")
    ann = SystemAnnouncement(title="Ack", content="C", is_active=True)
    db.add(ann)
    db.commit()
    db.refresh(ann)

    login_as(client, u["national_code"])
    resp = client.post(
        f"/announcements/{ann.id}/seen",
        data={"csrf_token": "bad"},
    )
    assert resp.status_code == 403

    db.query(SystemAnnouncement).filter_by(id=ann.id).delete()
    db.commit()


def test_user_page_acknowledgement_marks_seen_and_redirects(client, db, make_user):
    from models.system_announcement import SystemAnnouncement
    from web.services.announcement_service import list_unread
    from web.session import make_csrf_token

    u = make_user(role="user")
    ann = SystemAnnouncement(title="Ack OK", content="C", is_active=True)
    db.add(ann)
    db.commit()
    db.refresh(ann)

    login_as(client, u["national_code"])
    resp = client.post(
        f"/announcements/{ann.id}/seen",
        data={"csrf_token": make_csrf_token(u["user_id"])},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/announcements"
    assert all(item.id != ann.id for item in list_unread(db, u["user_id"]))

    resp2 = client.get("/announcements")
    assert resp2.status_code == 200
    assert "Ack OK" in resp2.text

    db.query(SystemAnnouncement).filter_by(id=ann.id).delete()
    db.commit()


def test_admin_page_announcements_and_form(client, make_user):
    u = make_user(role="admin")
    login_as(client, u["national_code"])

    assert client.get("/admin/announcements").status_code == 200
    form = client.get("/admin/announcements/new")
    assert form.status_code == 200
    assert "ایجاد اعلان جدید" in form.text


def test_admin_create_requires_csrf(client, make_user):
    u = make_user(role="admin")
    login_as(client, u["national_code"])

    resp = client.post(
        "/admin/announcements/create",
        data={"title": "No CSRF", "content": "C"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_scenario_two_unread_then_one_seen(db, client, make_user):
    """Two active announcements stay distinct: one seen, one unread; both remain in history/page."""
    import uuid
    from models.system_announcement import SystemAnnouncement
    from web.services.announcement_service import list_history, list_unread, mark_as_seen

    u = make_user(role="user")
    uid = str(uuid.uuid4())[:8]
    a1 = SystemAnnouncement(
        title=f"A1-{uid}", content="C1", is_active=True, announcement_type="general"
    )
    a2 = SystemAnnouncement(
        title=f"A2-{uid}", content="C2", is_active=True, announcement_type="general"
    )
    db.add_all([a1, a2])
    db.commit()
    db.refresh(a1)
    db.refresh(a2)

    unread = [ann for ann in list_unread(db, u["user_id"]) if ann.id in (a1.id, a2.id)]
    assert len(unread) == 2

    login_as(client, u["national_code"])
    resp = client.get("/announcements")
    assert resp.status_code == 200
    assert a1.title in resp.text and a2.title in resp.text

    assert mark_as_seen(db, u["user_id"], a1.id) is True
    unread2 = [ann for ann in list_unread(db, u["user_id"]) if ann.id in (a1.id, a2.id)]
    assert [ann.id for ann in unread2] == [a2.id]

    resp2 = client.get("/announcements")
    assert resp2.status_code == 200
    assert a1.title in resp2.text and a2.title in resp2.text

    history = list_history(db, u["user_id"])
    seen_row = next((h for h in history if h["announcement_id"] == a1.id), None)
    assert seen_row is not None and seen_row["seen_at"] is not None

    db.query(SystemAnnouncement).filter(SystemAnnouncement.id.in_([a1.id, a2.id])).delete(
        synchronize_session=False
    )
    db.commit()


def test_dashboard_has_announcement_context(client, make_user):
    u = make_user(role="user")
    login_as(client, u["national_code"])
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "announcement" in resp.text.lower()
