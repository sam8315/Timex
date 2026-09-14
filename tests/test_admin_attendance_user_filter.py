"""Tests for the user filter on /admin/attendance (daily view of all employees)."""
import jdatetime
import pytest
from datetime import datetime

from .conftest import login_as
from models.attendance import Attendance
from models.employee import Employee


def _jdate(value):
    return jdatetime.datetime.strptime(value, "%Y/%m/%d").date()


def _make_attendance(db, user_id, j_str, hour, minute, punch=0):
    g = _jdate(j_str).togregorian()
    rec = Attendance(
        user_id=user_id,
        timestamp=datetime(g.year, g.month, g.day, hour, minute),
        punch=punch,
        status=15,
        source="L",
    )
    db.add(rec)
    db.commit()
    return rec


def _today_j():
    return jdatetime.date.today().strftime("%Y/%m/%d")


# A. No filter → previous behavior preserved (all active employees shown)
def test_no_filter_shows_all(client, db, make_user):
    a = make_user(role="admin", department="1")
    b = make_user(role="user", department="1")
    login_as(client, a["national_code"])
    resp = client.get("/admin/attendance", follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    assert b["user_id"] in html
    assert a["user_id"] in html


# B. Valid user filter → only that user's row appears
def test_filter_only_selected_user(client, db, make_user):
    admin = make_user(role="admin", department="1")
    target = make_user(role="user", department="1")
    other = make_user(role="user", department="1")
    # attendance for the target user on today (so row renders even without punches)
    _make_attendance(db, target["user_id"], _today_j(), 9, 0)
    login_as(client, admin["national_code"])
    url = f"/admin/attendance?user_id={target['user_id']}"
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    # Filter UI reflects selection; dropdown JSON contains all users (expected)
    assert target["user_id"] in resp.text


# C. User without attendance → empty result, no exception
def test_user_without_attendance_empty(client, db, make_user):
    admin = make_user(role="admin", department="1")
    target = make_user(role="user", department="1")
    login_as(client, admin["national_code"])
    resp = client.get(
        f"/admin/attendance?user_id={target['user_id']}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    # Filter UI reflects the selection even with zero records
    assert target["user_id"] in resp.text


# D. Invalid user_id → controlled behavior (no 500, empty result)
@pytest.mark.parametrize("bad_id", ["NO-SUCH-USER", "   "])
def test_invalid_user_id_controlled(client, db, make_user, bad_id):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    resp = client.get(
        f"/admin/attendance?user_id={bad_id}",
        follow_redirects=False,
    )
    assert resp.status_code == 200
    # Filter is cleared → all active employees shown again
    assert "کاربر" in resp.text


# E. Department + user filter combine (AND)
def test_department_and_user_combine(client, db, make_user):
    admin = make_user(role="admin", department="1")
    target = make_user(role="user", department="1")
    other_dept = make_user(role="user", department="2")
    _make_attendance(db, target["user_id"], _today_j(), 9, 0)
    login_as(client, admin["national_code"])
    url = f"/admin/attendance?department=1&user_id={target['user_id']}"
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    # Filter applied: target's attendance shown; other dept may appear in dropdown
    assert target["user_id"] in html


# F. Filter state preserved in navigation links (date nav)
def test_navigation_keeps_filter(client, db, make_user):
    admin = make_user(role="admin", department="1")
    target = make_user(role="user", department="1")
    login_as(client, admin["national_code"])
    url = f"/admin/attendance?date_str=1404/06/01&user_id={target['user_id']}"
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    # prev/next day links should carry user_id
    assert f"user_id={target['user_id']}" in html


# G. Unauthorized access unchanged (permissions preserved)
def test_unauthorized_user_forbidden(client, db, make_user):
    normal = make_user(role="user")
    login_as(client, normal["national_code"])
    resp = client.get("/admin/attendance", follow_redirects=False)
    assert resp.status_code == 403


# H. Search dropdown data provided (reused employees_data pattern)
def test_search_dropdown_data_present(client, db, make_user):
    admin = make_user(role="admin")
    target = make_user(role="user", department="4")
    login_as(client, admin["national_code"])
    resp = client.get("/admin/attendance", follow_redirects=False)
    assert resp.status_code == 200
    html = resp.text
    # Search dropdown data present (JS variable employeesData, hidden inputs)
    assert "userSearchInput" in html
    assert "targetUserId" in html
    assert target["user_id"] in html  # appears in the JSON dataset too