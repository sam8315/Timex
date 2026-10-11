"""تأیید استعلاجی: انتخاب پرداخت اجباری است و تعارض مانع تأیید می‌شود."""
from datetime import datetime

import jdatetime
import pytest

from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.hourly_mission import HourlyMission
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from tests.conftest import login_as
from web.services.sick_leave_conflicts import (
    find_sick_leave_conflicts,
    format_conflict_message,
    parse_employer_pays,
)


def test_employer_pay_choice_is_required():
    with pytest.raises(ValueError):
        parse_employer_pays("", required=True)
    assert parse_employer_pays("true", required=True) is True
    assert parse_employer_pays("false", required=True) is False
    assert parse_employer_pays("", required=False) is None


def test_friday_without_punch_is_not_a_conflict(db, make_user):
    creds = make_user()
    start = jdatetime.date(1404, 7, 3).togregorian()  # جمعه
    conflicts = find_sick_leave_conflicts(db, creds["user_id"], start, start)
    assert conflicts == []


def test_punch_leave_and_mission_block_sick_approval(db, make_user):
    creds = make_user()
    day = jdatetime.date(1404, 7, 5).togregorian()
    db.add(Attendance(
        user_id=creds["user_id"],
        timestamp=datetime(day.year, day.month, day.day, 8, 0),
        punch=0,
        source="M",
        is_deleted=False,
    ))
    db.add(LeaveRequest(
        user_id=creds["user_id"],
        leave_type="AL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="A",
    ))
    db.add(DailyStatus(
        user_id=creds["user_id"],
        status_date=day,
        status_code="M",
    ))
    db.add(HourlyMission(
        user_id=creds["user_id"],
        mission_date=day,
        start_time=datetime.strptime("09:00", "%H:%M").time(),
        end_time=datetime.strptime("11:00", "%H:%M").time(),
        status="P",
    ))
    db.commit()
    conflicts = find_sick_leave_conflicts(db, creds["user_id"], day, day)
    kinds = {item["kind"] for item in conflicts}
    assert {"punch", "leave", "mission", "hourly_mission"} <= kinds
    message = format_conflict_message(conflicts)
    assert "1404/07/05" in message
    assert "تردد" in message


def test_legacy_null_pay_flag_is_stored_as_unknown(db, make_user):
    creds = make_user()
    day = jdatetime.date(1404, 7, 6).togregorian()
    row = LeaveRequest(
        user_id=creds["user_id"],
        leave_type="SL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="A",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    assert row.employer_pays_wages is None


def _pending_sick(db, user_id, pays_year=1404):
    day = jdatetime.date(pays_year, 7, 7).togregorian()
    db.add(LeaveBalance(
        user_id=user_id, year=pays_year, leave_type="SL", balance=10,
    ))
    row = LeaveRequest(
        user_id=user_id,
        leave_type="SL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="P",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_approve_route_rejects_missing_pay_choice(client, db, make_user):
    admin = make_user(role="admin")
    target = make_user()
    row = _pending_sick(db, target["user_id"])
    login_as(client, admin["national_code"])
    resp = client.post(f"/admin/leave-requests/{row.id}/approve", data={})
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    db.refresh(row)
    assert row.status == "P"
    assert row.employer_pays_wages is None


@pytest.mark.parametrize("choice,expected", [("true", True), ("false", False)])
def test_approve_route_stores_pay_choice(client, db, make_user, choice, expected):
    admin = make_user(role="admin")
    target = make_user()
    row = _pending_sick(db, target["user_id"])
    login_as(client, admin["national_code"])
    resp = client.post(
        f"/admin/leave-requests/{row.id}/approve",
        data={"employer_pays_wages": choice},
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.refresh(row)
    assert row.status == "A"
    assert row.employer_pays_wages is expected


def test_approve_route_blocks_punch_conflict(client, db, make_user):
    admin = make_user(role="admin")
    target = make_user()
    row = _pending_sick(db, target["user_id"])
    db.add(Attendance(
        user_id=target["user_id"],
        timestamp=datetime(row.from_date.year, row.from_date.month, row.from_date.day, 8, 0),
        punch=0,
        source="M",
        is_deleted=False,
    ))
    db.commit()
    login_as(client, admin["national_code"])
    resp = client.post(
        f"/admin/leave-requests/{row.id}/approve",
        data={"employer_pays_wages": "true"},
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    db.refresh(row)
    assert row.status == "P"
