"""Tests for user leave requests (submit / validate / cancel / calculate)."""
import jdatetime
from datetime import timedelta

from models.leave_request import LeaveRequest
from .conftest import jalali_range, login_as


def _submit(client, leave_type="AL", from_str=None, to_str=None, reason=""):
    if from_str is None or to_str is None:
        from_str, to_str = jalali_range(3, 2)
    return client.post(
        "/leave/request",
        data={
            "leave_type": leave_type,
            "from_date_str": from_str,
            "to_date_str": to_str,
            "reason": reason,
        },
        follow_redirects=False,
    )


def test_leave_page_loads(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = client.get("/leave")
    assert resp.status_code == 200
    assert "مرخصی" in resp.text


def test_calculate_days_api(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    from_str, to_str = jalali_range(3, 2)
    resp = client.get(
        "/leave/calculate-days",
        params={"from_date": from_str, "to_date": to_str},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["days_count"] > 0


def test_calculate_days_reversed_range_fails(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    from_str, to_str = jalali_range(5, 2)
    resp = client.get(
        "/leave/calculate-days",
        params={"from_date": to_str, "to_date": from_str},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_submit_valid_request_creates_pending(client, db, make_user):
    creds = make_user(role="user", balance_al=30)
    login_as(client, creds["national_code"])
    resp = _submit(client)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == creds["user_id"]).first()
    assert row is not None
    assert row.status == "P"
    assert row.days_count > 0


def test_submit_past_date_is_rejected(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    today_j = jdatetime.date.today()
    past = (today_j - timedelta(days=1)).strftime("%Y/%m/%d")
    future = (today_j + timedelta(days=2)).strftime("%Y/%m/%d")
    resp = _submit(client, from_str=past, to_str=future)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_submit_overlapping_request_is_rejected(client, make_user):
    creds = make_user(role="user", balance_al=30)
    login_as(client, creds["national_code"])
    from_str, to_str = jalali_range(6, 2)
    first = _submit(client, from_str=from_str, to_str=to_str)
    assert first.status_code == 302
    second = _submit(client, from_str=from_str, to_str=to_str)
    assert second.status_code == 302
    assert "error=" in second.headers["location"]


def test_submit_without_balance_is_rejected(client, make_user):
    creds = make_user(role="user", balance_al=None)
    login_as(client, creds["national_code"])
    resp = _submit(client)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_submit_invalid_leave_type_is_rejected(client, make_user):
    creds = make_user(role="user")
    login_as(client, creds["national_code"])
    resp = _submit(client, leave_type="XX")
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_cancel_own_pending_request(client, db, make_user):
    creds = make_user(role="user", balance_al=30)
    login_as(client, creds["national_code"])
    _submit(client)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == creds["user_id"]).first()
    resp = client.post(f"/leave/request/{row.id}/cancel",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "R"


def test_cancel_other_users_request_is_rejected(client, db, make_user):
    owner = make_user(role="user", balance_al=30)
    intruder = make_user(role="user", balance_al=30)
    login_as(client, owner["national_code"])
    _submit(client)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == owner["user_id"]).first()

    client.get("/logout", follow_redirects=False)
    login_as(client, intruder["national_code"])
    resp = client.post(f"/leave/request/{row.id}/cancel",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "P"
