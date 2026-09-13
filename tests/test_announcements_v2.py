"""Focused tests for the clean-room announcements implementation."""
from datetime import datetime, timedelta


def test_announcement_models_import():
    from models.system_announcement import SystemAnnouncement
    from models.user_announcement import UserAnnouncement
    assert SystemAnnouncement.__tablename__ == "system_announcements"
    assert UserAnnouncement.__tablename__ == "user_announcements"


def test_unread_filter_excludes_future_and_expired(db):
    from models.system_announcement import SystemAnnouncement
    from web.services.announcement_service import list_unread

    user_id = "announcement-test-user"
    now = datetime.now()
    db.add_all([
        SystemAnnouncement(title="Visible", content="x", published_at=now - timedelta(minutes=1), is_active=True),
        SystemAnnouncement(title="Future", content="x", published_at=now + timedelta(days=1), is_active=True),
        SystemAnnouncement(title="Expired", content="x", published_at=now - timedelta(days=2), expires_at=now - timedelta(days=1), is_active=True),
        SystemAnnouncement(title="Inactive", content="x", published_at=now - timedelta(minutes=1), is_active=False),
    ])
    db.commit()
    titles = {item.title for item in list_unread(db, user_id)}
    assert "Visible" in titles
    assert "Future" not in titles
    assert "Expired" not in titles
    assert "Inactive" not in titles


def test_mark_seen_is_idempotent(db):
    from models.system_announcement import SystemAnnouncement
    from web.services.announcement_service import mark_as_seen, get_unread_count

    user_id = "announcement-idempotent-user"
    ann = SystemAnnouncement(title="Once", content="x", published_at=datetime.now(), is_active=True)
    db.add(ann)
    db.commit()
    db.refresh(ann)
    assert get_unread_count(db, user_id) == 1
    assert mark_as_seen(db, user_id, ann.id) is True
    assert get_unread_count(db, user_id) == 0
    assert mark_as_seen(db, user_id, ann.id) is True
    assert get_unread_count(db, user_id) == 0
