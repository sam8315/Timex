"""Tests for the admin leave lifecycle: approve / reject / delete-approved."""
import jdatetime

from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.leave_transaction import LeaveTransaction
from .conftest import jalali_range, login_as


def _submit_as(client, creds, start_offset, span=2):
    from_str, to_str = jalali_range(start_offset, span)
    return client.post(
        "/leave/request",
        data={"leave_type": "AL", "from_date_str": from_str,
              "to_date_str": to_str, "reason": ""},
        follow_redirects=False,
    ), from_str


def _balance(db, user_id):
    year_j = jdatetime.date.today().year
    return db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == "AL",
    ).first().balance


def test_admin_can_approve_pending_request(client, db, make_user):
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="super_admin", balance_al=None)

    login_as(client, user["national_code"])
    resp, _ = _submit_as(client, user, 3)
    assert resp.status_code == 302
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    days = row.days_count
    before = _balance(db, user["user_id"])

    client.get("/logout", follow_redirects=False)
    login_as(client, admin["national_code"])
    approve = client.post(f"/admin/leave-requests/{row.id}/approve",
                          follow_redirects=False)
    assert approve.status_code == 302
    assert "success=" in approve.headers["location"]

    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "A"
    assert _balance(db, user["user_id"]) == before - days
    txn = db.query(LeaveTransaction).filter(
        LeaveTransaction.reference_id == row.id,
        LeaveTransaction.transaction_type == "USE",
    ).first()
    assert txn is not None
    assert txn.amount == days


def test_approve_twice_is_rejected(client, db, make_user):
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="super_admin", balance_al=None)
    login_as(client, user["national_code"])
    _submit_as(client, user, 8)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()

    client.get("/logout", follow_redirects=False)
    login_as(client, admin["national_code"])
    first = client.post(f"/admin/leave-requests/{row.id}/approve",
                        follow_redirects=False)
    assert "success=" in first.headers["location"]
    second = client.post(f"/admin/leave-requests/{row.id}/approve",
                         follow_redirects=False)
    assert "error=" in second.headers["location"]


def test_plain_user_cannot_approve(client, db, make_user):
    user = make_user(role="user", balance_al=30)
    login_as(client, user["national_code"])
    _submit_as(client, user, 12)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    resp = client.post(f"/admin/leave-requests/{row.id}/approve",
                       follow_redirects=False)
    assert resp.status_code == 403


def test_admin_can_reject_without_deduction(client, db, make_user):
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="super_admin", balance_al=None)
    login_as(client, user["national_code"])
    _submit_as(client, user, 15)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    before = _balance(db, user["user_id"])

    client.get("/logout", follow_redirects=False)
    login_as(client, admin["national_code"])
    resp = client.post(
        f"/admin/leave-requests/{row.id}/reject",
        data={"rejection_reason": "کمبود نیرو"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    rejected = db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first()
    assert rejected.status == "R"
    assert rejected.rejection_reason == "کمبود نیرو"
    assert _balance(db, user["user_id"]) == before


def _setup_insufficient_balance(client, db, make_user, start_offset=25):
    """Submit a valid request, then drain the balance to force insufficiency."""
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="super_admin", balance_al=None)
    login_as(client, user["national_code"])
    _submit_as(client, user, start_offset)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    assert row is not None and row.status == "P"
    year_j = jdatetime.date.today().year
    db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user["user_id"],
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == "AL",
    ).update({"balance": 0})
    db.commit()
    client.get("/logout", follow_redirects=False)
    return user, admin, row


def test_super_admin_first_attempt_asks_for_confirmation(
        client, db, make_user):
    user, admin, row = _setup_insufficient_balance(client, db, make_user)
    login_as(client, admin["national_code"])
    resp = client.post(f"/admin/leave-requests/{row.id}/approve",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert f"confirm_negative={row.id}" in resp.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "P"
    assert _balance(db, user["user_id"]) == 0


def test_super_admin_confirm_makes_balance_negative(
        client, db, make_user):
    user, admin, row = _setup_insufficient_balance(
        client, db, make_user, start_offset=30)
    days = row.days_count
    login_as(client, admin["national_code"])
    resp = client.post(
        f"/admin/leave-requests/{row.id}/approve",
        data={"allow_negative": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "A"
    assert _balance(db, user["user_id"]) == -days
    txn = db.query(LeaveTransaction).filter(
        LeaveTransaction.reference_id == row.id,
        LeaveTransaction.transaction_type == "USE",
    ).first()
    assert txn is not None
    assert "مانده منفی" in (txn.description or "")


def test_plain_admin_insufficient_has_no_confirm_option(
        client, db, make_user):
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="admin", balance_al=None)
    login_as(client, user["national_code"])
    _submit_as(client, user, 35)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    year_j = jdatetime.date.today().year
    db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user["user_id"],
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == "AL",
    ).update({"balance": 0})
    db.commit()
    client.get("/logout", follow_redirects=False)

    login_as(client, admin["national_code"])
    resp = client.post(f"/admin/leave-requests/{row.id}/approve",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert "confirm_negative" not in resp.headers["location"]
    # حتی با فلگ اجازه هم مدیر عادی نمی‌تواند منفی کند
    forced = client.post(
        f"/admin/leave-requests/{row.id}/approve",
        data={"allow_negative": "on"},
        follow_redirects=False,
    )
    assert "error=" in forced.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "P"


def test_confirm_warning_box_renders_for_super_admin(
        client, db, make_user):
    user, admin, row = _setup_insufficient_balance(
        client, db, make_user, start_offset=40)
    login_as(client, admin["national_code"])
    resp = client.get(
        f"/admin/leave-requests?status_filter=P&confirm_negative={row.id}")
    assert resp.status_code == 200
    assert "مانده منفی" in resp.text
    assert f"/admin/leave-requests/{row.id}/approve" in resp.text
    assert 'name="allow_negative"' in resp.text


def test_admin_can_delete_approved_and_restore_balance(
        client, db, make_user):
    user = make_user(role="user", balance_al=30)
    admin = make_user(role="super_admin", balance_al=None)
    login_as(client, user["national_code"])
    _submit_as(client, user, 20)
    db.expire_all()
    row = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user["user_id"]).first()
    days = row.days_count
    before = _balance(db, user["user_id"])

    client.get("/logout", follow_redirects=False)
    login_as(client, admin["national_code"])
    client.post(f"/admin/leave-requests/{row.id}/approve",
                follow_redirects=False)
    db.expire_all()
    assert _balance(db, user["user_id"]) == before - days

    delete = client.post(f"/admin/leave-requests/{row.id}/delete",
                         follow_redirects=False)
    assert delete.status_code == 302
    assert "success=" in delete.headers["location"]
    db.expire_all()
    assert db.query(LeaveRequest).filter(
        LeaveRequest.id == row.id).first().status == "D"
    assert _balance(db, user["user_id"]) == before
    reverse = db.query(LeaveTransaction).filter(
        LeaveTransaction.reference_id == row.id,
        LeaveTransaction.transaction_type == "REVERSE",
    ).first()
    assert reverse is not None
