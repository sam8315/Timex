"""درخواست تردد فراموش‌شده: ارسال، تأیید، رد و دسترسی."""
from datetime import datetime, timedelta

import jdatetime

from models.attendance import Attendance
from models.missed_attendance_request import MissedAttendanceRequest
from models.user import User
from tests.conftest import login_as
from web.permissions import ALL_PERMISSIONS, has_permission


def _past_date(days_ago=3) -> str:
    day = jdatetime.date.today() - timedelta(days=days_ago)
    return day.strftime("%Y/%m/%d")


def _user(db, user_id):
    return db.query(User).filter(User.user_id == user_id).first()


def test_other_reason_requires_text(client, db, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])

    empty = client.post(
        "/attendance/missed",
        data={
            "date_str": _past_date(),
            "time_str": "08:10",
            "punch": "0",
            "reason_code": "other",
            "reason_text": "   ",
        },
        follow_redirects=True,
    )
    assert empty.status_code == 200
    assert "سایر" in empty.text
    assert db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.user_id == creds["user_id"]
    ).count() == 0

    filled = client.post(
        "/attendance/missed",
        data={
            "date_str": _past_date(),
            "time_str": "08:10",
            "punch": "1",
            "reason_code": "other",
            "reason_text": "جلسه بیرون از ساختمان",
        },
        follow_redirects=True,
    )
    assert filled.status_code == 200
    assert "درخواست ثبت شد" in filled.text
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.user_id == creds["user_id"]
    ).one()
    assert row.reason_code == "other"
    assert row.reason_text == "جلسه بیرون از ساختمان"
    assert row.status == "P"
    assert row.punch == 1


def test_approve_creates_manual_attendance(client, db, make_user):
    employee = make_user(role="user")
    approver = make_user(role="super_admin")
    login_as(client, employee["national_code"])
    sent = client.post(
        "/attendance/missed",
        data={
            "date_str": _past_date(4),
            "time_str": "09:15",
            "punch": "0",
            "reason_code": "forgot_punch",
        },
        follow_redirects=False,
    )
    assert sent.status_code == 302

    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.user_id == employee["user_id"]
    ).one()

    login_as(client, approver["national_code"])
    approved = client.post(
        f"/admin/missed-attendance/{row.id}/approve",
        follow_redirects=True,
    )
    assert approved.status_code == 200
    assert "تردد ثبت شد" in approved.text

    db.expire_all()
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.id == row.id
    ).one()
    assert row.status == "A"
    assert row.reviewed_by == approver["user_id"]
    assert row.attendance_id is not None

    record = db.query(Attendance).filter(Attendance.id == row.attendance_id).one()
    assert record.user_id == employee["user_id"]
    assert record.source == "M"
    assert record.punch == 0
    assert record.status == 15
    assert record.is_deleted is False
    wall = record.timestamp
    if wall.tzinfo is not None:
        wall = wall.astimezone().replace(tzinfo=None)
    assert (wall.hour, wall.minute) == (9, 15)


def test_reject_does_not_create_attendance(client, db, make_user):
    employee = make_user(role="user")
    approver = make_user(role="super_admin")
    login_as(client, employee["national_code"])
    client.post(
        "/attendance/missed",
        data={
            "date_str": _past_date(5),
            "time_str": "17:40",
            "punch": "1",
            "reason_code": "device_fault",
        },
    )
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.user_id == employee["user_id"]
    ).one()

    login_as(client, approver["national_code"])
    rejected = client.post(
        f"/admin/missed-attendance/{row.id}/reject",
        data={"rejection_reason": "ساعت با شیفت نمی‌خواند"},
        follow_redirects=True,
    )
    assert rejected.status_code == 200
    assert "درخواست رد شد" in rejected.text

    db.expire_all()
    row = db.query(MissedAttendanceRequest).filter(
        MissedAttendanceRequest.id == row.id
    ).one()
    assert row.status == "R"
    assert row.rejection_reason == "ساعت با شیفت نمی‌خواند"
    assert row.attendance_id is None
    assert db.query(Attendance).filter(
        Attendance.user_id == employee["user_id"],
        Attendance.is_deleted == False,  # noqa: E712
    ).count() == 0


def test_permission_defaults_to_super_admin_only(db, make_user):
    info = ALL_PERMISSIONS["approve_missed_attendance"]
    assert info["admin"] is False
    assert info["super_admin"] is True
    assert info.get("user", False) is False

    admin = _user(db, make_user(role="admin")["user_id"])
    super_admin = _user(db, make_user(role="super_admin")["user_id"])
    employee = _user(db, make_user(role="user")["user_id"])
    assert has_permission(db, admin, "approve_missed_attendance") is False
    assert has_permission(db, super_admin, "approve_missed_attendance") is True
    assert has_permission(db, employee, "approve_missed_attendance") is False


def test_admin_without_permission_gets_403(client, make_user):
    creds = make_user(role="admin")
    login_as(client, creds["national_code"])
    assert client.get("/admin/missed-attendance").status_code == 403
    assert client.post("/admin/missed-attendance/1/approve").status_code == 403


def test_incomplete_month_rows_offer_form_fill(client, db, make_user):
    creds = make_user(role="user")
    stamp = datetime.now().replace(second=0, microsecond=0)
    if stamp.hour > 0 or stamp.minute > 1:
        stamp = stamp.replace(hour=0, minute=1)
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=stamp,
        punch=0,
        status=0,
        source="D",
    ))
    db.commit()

    login_as(client, creds["national_code"])
    page = client.get("/attendance/missed")
    assert page.status_code == 200
    assert 'data-time-input="true"' in page.text
    assert 'placeholder="HH:MM"' in page.text
    assert 'type="time"' not in page.text
    date_j = jdatetime.date.fromgregorian(date=stamp.date()).strftime("%Y/%m/%d")
    assert date_j in page.text
    assert 'class="btn btn-sm btn-outline-primary fill-missed-form"' in page.text
    assert 'data-punch="1"' in page.text
    assert "ترددهای ناقص" in page.text


def test_dashboard_card_visible_only_with_permission(client, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    admin_page = client.get("/admin", follow_redirects=True)
    assert admin_page.status_code == 200
    assert "درخواست تردد فراموش‌شده" not in admin_page.text

    super_admin = make_user(role="super_admin")
    login_as(client, super_admin["national_code"])
    page = client.get("/admin", follow_redirects=True)
    assert page.status_code == 200
    assert "درخواست تردد فراموش‌شده" in page.text
    assert 'href="/admin/missed-attendance"' in page.text
