"""Regression tests for the unread-announcement login flow."""
from datetime import datetime

from .conftest import login_as
from models.system_announcement import SystemAnnouncement


def test_login_redirects_to_unread_announcements(client, db, make_user):
    creds = make_user(role="user")
    db.add(SystemAnnouncement(
        title="قابلیت جدید",
        content="این یک اعلان آزمایشی است.",
        announcement_type="feature",
        is_active=True,
        published_at=datetime.now(),
    ))
    db.commit()

    response = client.post("/login", data={
        "national_code": creds["national_code"],
        "password": creds["password"],
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/announcements"


def test_login_without_unread_announcements_redirects_to_dashboard(client, make_user):
    creds = make_user(role="user")
    response = client.post("/login", data={
        "national_code": creds["national_code"],
        "password": creds["password"],
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
