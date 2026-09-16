"""Tests for mission/rest status display and duty deduction on
/admin/attendance/user/{id} — mirroring the user-side attendance tests.

Verifies:
- Mission (M) and Rest (R) badges appear in the وضعیت column, not the date cell
- Mission days reduce monthly required minutes (consistency with user page)
- Existing admin features (filters, permissions, calculations) are preserved
"""
import pytest
from datetime import datetime, time, timedelta

import jdatetime

from models.daily_status import DailyStatus
from models.employee import Employee
from models.attendance import Attendance
from .conftest import login_as
from .test_hl_ui_display import (
    _current_jalali_month,
    _workday_in_current_month,
    _seed_attendance_policy,
    _seed_day_punches,
    _html_row_containing,
)
from web.services.attendance_policy_service import (
    compute_required_minutes_for_range,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_user_on_workday(db, make_user, status_code):
    """Create an admin + target user, seed attendance policy + punches,
    optionally attach a DailyStatus.  Returns (admin, target_user, workday, g_start)."""
    target = make_user(role="user", balance_al=None, department="1")
    emp = db.query(Employee).filter(
        Employee.user_id == target["user_id"]
    ).first()

    workday = _workday_in_current_month()
    g_start = workday.togregorian()

    _seed_attendance_policy(db, emp,
                            start=g_start - timedelta(days=30),
                            end=g_start + timedelta(days=30))
    _seed_day_punches(db, emp, g_start)

    if status_code:
        db.add(DailyStatus(
            user_id=emp.user_id,
            status_date=g_start,
            status_code=status_code,
        ))
        db.commit()

    admin = make_user(role="admin", balance_al=None)
    return admin, target, workday, g_start


# ---------------------------------------------------------------------------
# Tests: badge placement in the وضعیت column
# ---------------------------------------------------------------------------
class TestAdminMissionRestBadgePlacement:
    """Mission/Rest badges must be in the وضعیت column, not in the date cell."""

    def test_mission_badge_visible(self, db, client, make_user):
        """GET /admin/attendance/user/{id} with DailyStatus M → badge visible."""
        admin, target, workday, g_start = _seed_user_on_workday(db, make_user, "M")

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/attendance/user/{target['user_id']}?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        assert "🚗 مأموریت" in html

    def test_mission_badge_not_in_date_cell(self, db, client, make_user):
        """The date <td> must NOT contain the mission badge."""
        admin, target, workday, g_start = _seed_user_on_workday(db, make_user, "M")
        j_date = workday.strftime("%Y/%m/%d")

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/attendance/user/{target['user_id']}?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        row = _html_row_containing(html, j_date)
        assert row, f"Could not find row for date {j_date}"

        td_start = row.find("<td")
        td_end = row.find("</td>")
        date_cell = row[td_start:td_end]

        assert "مأموریت" not in date_cell
        assert "bg-primary" not in date_cell

    def test_rest_badge_visible(self, db, client, make_user):
        """GET /admin/attendance/user/{id} with DailyStatus R → badge visible."""
        admin, target, workday, g_start = _seed_user_on_workday(db, make_user, "R")

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/attendance/user/{target['user_id']}?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        assert "استراحت" in html

    def test_rest_badge_not_in_date_cell(self, db, client, make_user):
        """The date <td> must NOT contain the rest badge."""
        admin, target, workday, g_start = _seed_user_on_workday(db, make_user, "R")
        j_date = workday.strftime("%Y/%m/%d")

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/attendance/user/{target['user_id']}?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        row = _html_row_containing(html, j_date)
        assert row, f"Could not find row for date {j_date}"

        td_start = row.find("<td")
        td_end = row.find("</td>")
        date_cell = row[td_start:td_end]

        assert "استراحت" not in date_cell


# ---------------------------------------------------------------------------
# Tests: duty calculation consistency with user page
# ---------------------------------------------------------------------------
class TestAdminMissionDutyDeduction:
    """Mission days must reduce required minutes in the admin view
    — same calculation as the user page."""

    def test_mission_reduces_monthly_required(self, db, make_user):
        """Mission day → 0 required for that day (via compute_required_minutes_for_range)."""
        from models.attendance import AttendancePolicy, AttendancePolicyDay

        target = make_user(role="user", balance_al=None, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == target["user_id"]
        ).first()

        g_date = _workday_in_current_month().togregorian()
        policy_start = g_date - timedelta(days=30)
        policy_end = g_date + timedelta(days=30)

        _seed_attendance_policy(db, emp, start=policy_start, end=policy_end)

        # Seed a mission status for the workday
        db.add(DailyStatus(
            user_id=emp.user_id,
            status_date=g_date,
            status_code="M",
        ))
        db.commit()

        holiday_dates = {}
        leaves_by_date = {}

        # Without mission: 1 day contributes (480 min from _seed_attendance_policy)
        base = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=g_date, end_date=g_date,
            rest_dates=set(), holiday_dates=holiday_dates,
            leaves_by_date=leaves_by_date,
            mission_dates=set(),
        )

        # With mission: 0 required
        with_mission = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=g_date, end_date=g_date,
            rest_dates=set(), holiday_dates=holiday_dates,
            leaves_by_date=leaves_by_date,
            mission_dates={g_date},
        )

        assert base > 0
        assert with_mission == 0
        assert with_mission < base

    def test_mission_equals_rest_reduction(self, db, make_user):
        """Mission and rest reduce required minutes identically."""
        target = make_user(role="user", balance_al=None, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == target["user_id"]
        ).first()

        g_date = _workday_in_current_month().togregorian()
        _seed_attendance_policy(db, emp,
                                start=g_date - timedelta(days=30),
                                end=g_date + timedelta(days=30))

        common = dict(
            db=db, employee=emp,
            start_date=g_date, end_date=g_date,
            holiday_dates={}, leaves_by_date={},
        )

        with_rest = compute_required_minutes_for_range(
            rest_dates={g_date}, mission_dates=set(), **common,
        )
        with_mission = compute_required_minutes_for_range(
            rest_dates=set(), mission_dates={g_date}, **common,
        )

        assert with_rest == with_mission == 0
