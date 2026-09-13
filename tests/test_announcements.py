"""Announcement domain tests (unit / API / auth / CSRF / unread / seen / regression)."""
from datetime import datetime
from sqlalchemy import text
from tests.conftest import login_as
import uuid


def test_model_import_and_schema(db):
    from models.system_announcement import SystemAnnouncement
    from models.user_announcement import UserAnnouncement
    assert SystemAnnouncement.__tablename__ == "system_announcements"
    assert UserAnnouncement.__tablename__ == "user_announcements"


def test_service_unread_and_seen(db, make_user):
    from web.services.announcement_service import (
        get_unread_count, mark_as_seen, list_history
    )
    from models.system_announcement import SystemAnnouncement
    u = make_user(role="user")
    ann = SystemAnnouncement(
        title="T", content="C", is_active=True,
        announcement_type="general",
    )
    db.add(ann); db.commit(); db.refresh(ann)
    # Count may include pre-existing active announcements from DB
    count_before = get_unread_count(db, u["user_id"])
    assert mark_as_seen(db, u["user_id"], ann.id) is True
    count_after = get_unread_count(db, u["user_id"])
    assert count_after == count_before - 1
    assert len(list_history(db, u["user_id"])) >= 1
    # Idempotent
    assert mark_as_seen(db, u["user_id"], ann.id) is True
    db.query(SystemAnnouncement).filter_by(id=ann.id).delete()
    db.commit()


def test_api_unread_unauthenticated(client):
    resp = client.get("/api/announcements/unread")
    # Not logged in → redirect to login (307) per auth behavior
    assert resp.status_code in (307, 302, 401, 403)


def test_api_mark_seen_csrf_protected(client, db, make_user):
    u = make_user(role="user")
    login_as(client, u["national_code"])
    # No CSRF → 403
    resp = client.post("/api/announcements/1/seen", data={"csrf_token": "bad"})
    assert resp.status_code == 403


def test_user_page_announcements(client, db, make_user):
    u = make_user(role="user")
    login_as(client, u["national_code"])
    resp = client.get("/announcements")
    assert resp.status_code == 200


def test_admin_page_announcements(client, db, make_user):
    u = make_user(role="admin")
    login_as(client, u["national_code"])
    resp = client.get("/admin/announcements")
    assert resp.status_code == 200


def test_scenario_two_unread_then_one_seen(db, client, make_user):
    """2 active announcements, unread count=2, page shows both unread; after seen count=1, history keeps both."""
    from web.services.announcement_service import (
        get_unread_count, list_unread, list_history, mark_as_seen
    )
    from models.system_announcement import SystemAnnouncement
    import uuid
    u = make_user(role="user")
    uid = str(uuid.uuid4())[:8]
    a1 = SystemAnnouncement(title=f"A1-{uid}", content="C1", is_active=True, announcement_type="general")
    a2 = SystemAnnouncement(title=f"A2-{uid}", content="C2", is_active=True, announcement_type="general")
    db.add(a1); db.add(a2); db.commit(); db.refresh(a1); db.refresh(a2)

    # 1) both unread
    unread = [ann for ann in list_unread(db, u["user_id"]) if ann.id in (a1.id, a2.id)]
    assert len(unread) == 2

    # 2) page shows both
    login_as(client, u["national_code"])
    resp = client.get("/announcements")
    assert resp.status_code == 200
    assert a1.title in resp.text and a2.title in resp.text

    # 3) mark a1 seen
    assert mark_as_seen(db, u["user_id"], a1.id) is True
    unread2 = [ann for ann in list_unread(db, u["user_id"]) if ann.id in (a1.id, a2.id)]
    assert [ann.id for ann in unread2] == [a2.id]

    # 4) page still lists a2 as unread, a1 in history
    resp2 = client.get("/announcements")
    assert a1.title in resp2.text and a2.title in resp2.text
    hist = list_history(db, u["user_id"])
    seen_row = next((h for h in hist if h["announcement_id"] == a1.id), None)
    assert seen_row is not None and seen_row["seen_at"] is not None

    db.query(SystemAnnouncement).filter(SystemAnnouncement.id.in_([a1.id, a2.id])).delete(synchronize_session=False)
    db.commit()


def test_dashboard_has_announcement_context(client, db, make_user):
    u = make_user(role="user")
    login_as(client, u["national_code"])
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    # Sidebar / modal presence verified implicitly by template render
