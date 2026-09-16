"""
HTTP regression test for Admin User Attendance Mission/Rest rendering.

Real scenario:
    1405/06/24 -> 2026-09-15 -> Mission (M)
    1405/06/25 -> 2026-09-16 -> Rest (R)

This test intentionally exercises the real FastAPI endpoint and rendered
HTML, not only the DailyStatus resolver helpers.
"""
from datetime import datetime, date

import jdatetime

from models.attendance import Attendance
from models.daily_status import DailyStatus
from .conftest import login_as


MISSION_G = date(2026, 9, 15)
REST_G = date(2026, 9, 16)
JALALI_MONTH = 6
JALALI_YEAR = 1405


def _seed_daily_statuses(db, user_id: str) -> None:
    for status_date, status_code in (
        (MISSION_G, "M"),
        (REST_G, "R"),
    ):
        existing = db.query(DailyStatus).filter(
            DailyStatus.user_id == user_id,
            DailyStatus.status_date == status_date,
        ).first()
        if existing:
            db.delete(existing)

    db.flush()
    db.add_all([
        DailyStatus(
            user_id=user_id,
            status_date=MISSION_G,
            status_code="M",
        ),
        DailyStatus(
            user_id=user_id,
            status_date=REST_G,
            status_code="R",
        ),
    ])
    db.commit()


def _seed_existing_attendance(db, user_id: str) -> None:
    db.add_all([
        Attendance(
            user_id=user_id,
            timestamp=datetime(2026, 9, 15, 8, 0, 0),
            punch=0,
            source="M",
            is_deleted=False,
        ),
        Attendance(
            user_id=user_id,
            timestamp=datetime(2026, 9, 15, 16, 0, 0),
            punch=1,
            source="M",
            is_deleted=False,
        ),
    ])
    db.commit()


def test_real_admin_user_attendance_endpoint_renders_correct_mission_rest_dates(
    db, client, make_user
):
    target = make_user(role="super_admin")
    _seed_daily_statuses(db, target["user_id"])
    _seed_existing_attendance(db, target["user_id"])

    # Guard the exact Jalali/Gregorian mapping used by the regression.
    assert jdatetime.date.fromgregorian(date=MISSION_G).strftime("%Y/%m/%d") == "1405/06/24"
    assert jdatetime.date.fromgregorian(date=REST_G).strftime("%Y/%m/%d") == "1405/06/25"

    login_response = login_as(client, target["national_code"])
    assert login_response.status_code == 302

    url = (
        f"/admin/attendance/user/{target['user_id']}"
        f"?year={JALALI_YEAR}&month={JALALI_MONTH}"
    )
    response = client.get(url)

    assert response.status_code == 200
    html = response.text

    # Full unfiltered endpoint response: both statuses must be rendered.
    assert "1405/06/24" in html
    assert "1405/06/25" in html
    assert "🟦 مأموریت" in html
    assert "🟣 استراحت" in html

    # Existing attendance must remain visible when Mission is also present.
    assert "08:00:00" in html
    assert "16:00:00" in html


def test_real_admin_user_attendance_mission_filter_uses_rendered_status(
    db, client, make_user
):
    target = make_user(role="super_admin")
    _seed_daily_statuses(db, target["user_id"])

    login_response = login_as(client, target["national_code"])
    assert login_response.status_code == 302

    response = client.get(
        f"/admin/attendance/user/{target['user_id']}"
        f"?year={JALALI_YEAR}&month={JALALI_MONTH}&filter=mission"
    )

    assert response.status_code == 200
    html = response.text
    assert "1405/06/24" in html
    assert "🟦 مأموریت" in html
    assert "1405/06/25" not in html
    assert "🟣 استراحت" not in html


def test_real_admin_user_attendance_rest_filter_uses_rendered_status(
    db, client, make_user
):
    target = make_user(role="super_admin")
    _seed_daily_statuses(db, target["user_id"])

    login_response = login_as(client, target["national_code"])
    assert login_response.status_code == 302

    response = client.get(
        f"/admin/attendance/user/{target['user_id']}"
        f"?year={JALALI_YEAR}&month={JALALI_MONTH}&filter=rest"
    )

    assert response.status_code == 200
    html = response.text
    assert "1405/06/25" in html
    assert "🟣 استراحت" in html
    assert "1405/06/24" not in html
    assert "🟦 مأموریت" not in html


def test_real_admin_user_attendance_existing_no_attendance_filter_still_excludes_mission_rest(
    db, client, make_user
):
    target = make_user(role="super_admin")
    _seed_daily_statuses(db, target["user_id"])

    login_response = login_as(client, target["national_code"])
    assert login_response.status_code == 302

    response = client.get(
        f"/admin/attendance/user/{target['user_id']}"
        f"?year={JALALI_YEAR}&month={JALALI_MONTH}&filter=no_attendance"
    )

    assert response.status_code == 200
    html = response.text
    assert "1405/06/24" not in html
    assert "1405/06/25" not in html
    assert "🟦 مأموریت" not in html
    assert "🟣 استراحت" not in html
