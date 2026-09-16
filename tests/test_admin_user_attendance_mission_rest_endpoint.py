"""
HTTP regression test for Admin User Attendance Mission/Rest rendering.

Real scenario:
    1405/06/24 -> 2026-09-15 -> Mission (M)
    1405/06/25 -> 2026-09-16 -> Rest (R)

This test intentionally exercises the real FastAPI endpoint and rendered
HTML, not only the DailyStatus resolver helpers.
"""
from datetime import datetime, date
import re

import jdatetime

from models.attendance import Attendance
from models.daily_status import DailyStatus
from .conftest import login_as


MISSION_G = date(2026, 9, 15)
REST_G = date(2026, 9, 16)
MISSION_J = "1405/06/24"
REST_J = "1405/06/25"
JALALI_MONTH = 6
JALALI_YEAR = 1405


def _seed_daily_statuses(db, user_id: str) -> None:
    for status_date in (MISSION_G, REST_G):
        existing = db.query(DailyStatus).filter(
            DailyStatus.user_id == user_id,
            DailyStatus.status_date == status_date,
        ).first()
        if existing:
            db.delete(existing)

    db.flush()
    db.add_all([
        DailyStatus(user_id=user_id, status_date=MISSION_G, status_code="M"),
        DailyStatus(user_id=user_id, status_date=REST_G, status_code="R"),
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


def _day_rows(html: str) -> list[str]:
    """Return rendered <tr> blocks that belong to the main day table."""
    return re.findall(r"<tr\b[^>]*>.*?</tr>", html, flags=re.IGNORECASE | re.DOTALL)


def _rows_for_date(html: str, jalali_date: str) -> list[str]:
    return [row for row in _day_rows(html) if jalali_date in row]


def test_real_admin_user_attendance_endpoint_renders_correct_mission_rest_dates(
    db, client, make_user
):
    target = make_user(role="super_admin")
    _seed_daily_statuses(db, target["user_id"])
    _seed_existing_attendance(db, target["user_id"])

    assert jdatetime.date.fromgregorian(date=MISSION_G).strftime("%Y/%m/%d") == MISSION_J
    assert jdatetime.date.fromgregorian(date=REST_G).strftime("%Y/%m/%d") == REST_J

    login_response = login_as(client, target["national_code"])
    assert login_response.status_code == 302

    response = client.get(
        f"/admin/attendance/user/{target['user_id']}"
        f"?year={JALALI_YEAR}&month={JALALI_MONTH}"
    )

    assert response.status_code == 200
    html = response.text

    mission_rows = _rows_for_date(html, MISSION_J)
    rest_rows = _rows_for_date(html, REST_J)

    assert mission_rows, "Mission date row is not rendered"
    assert rest_rows, "Rest date row is not rendered"
    assert any("🟦 مأموریت" in row for row in mission_rows)
    assert any("🟣 استراحت" in row for row in rest_rows)

    # Existing attendance must remain visible when Mission is also present.
    mission_html = "\n".join(mission_rows)
    assert "08:00:00" in mission_html
    assert "16:00:00" in mission_html


def test_real_admin_user_attendance_mission_filter_uses_rendered_rows(
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
    mission_rows = _rows_for_date(html, MISSION_J)
    rest_rows = _rows_for_date(html, REST_J)

    assert mission_rows
    assert any("🟦 مأموریت" in row for row in mission_rows)
    assert not rest_rows


def test_real_admin_user_attendance_rest_filter_uses_rendered_rows(
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
    mission_rows = _rows_for_date(html, MISSION_J)
    rest_rows = _rows_for_date(html, REST_J)

    assert rest_rows
    assert any("🟣 استراحت" in row for row in rest_rows)
    assert not mission_rows


def test_real_admin_user_attendance_no_attendance_filter_excludes_mission_rest_rows(
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
    assert not _rows_for_date(html, MISSION_J)
    assert not _rows_for_date(html, REST_J)
