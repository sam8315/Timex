"""
Travel Leave attendance display tests.

Validates:
- build_leave_days_by_date() splits the first `final_travel_days` working days
  of an approved AL request as 'TL' ("مرخصی توراهی") instead of 'AL'.
- Fridays / holidays are never emitted and do not consume a TL slot.
- The split is computed across the *whole* leave range, so the visible window
  only affects which dates are emitted, not which days count as "first N".
- All three attendance views (/attendance, /admin/attendance, and
  /admin/attendance/user/{id}) render the TL badge on the correct days.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import jdatetime
import pytest

from models.employee import Employee
from models.city import City
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail

from web.services.travel_leave_service import (
    build_leave_days_by_date,
    is_working_day,
    leave_type_label,
    LEAVE_TYPE_TRAVEL,
    ATTENDANCE_LEAVE_TYPE_NAMES,
)

from .conftest import login_as, TestingSessionLocal


# ---------------------------------------------------------------------------
# Jalali / Gregorian date helpers
# ---------------------------------------------------------------------------
def _current_jalali_month():
    today = jdatetime.date.today()
    return today.year, today.month


def _workdays_in_current_month(n):
    """Return the first ``n`` non-Friday gregorian dates of the current
    Jalali month (consecutive working days). Guarantees a fully deterministic,
    holiday-free environment because the test DB seeds no holidays."""
    jy, jm = _current_jalali_month()
    j_start = jdatetime.date(jy, jm, 1)
    if jm == 12:
        j_end = jdatetime.date(jy, 12, 29)
    else:
        j_end = jdatetime.date(jy, jm + 1, 1) - timedelta(days=1)
    g_start = j_start.togregorian()
    g_end = j_end.togregorian()
    picks = []
    cur = g_start
    while cur <= g_end and len(picks) < n:
        if cur.weekday() != 4:  # skip Friday
            picks.append(cur)
        cur += timedelta(days=1)
    assert len(picks) == n, "could not find enough working days in current month"
    return picks


def _jalali_str(g_date):
    return jdatetime.date.fromgregorian(date=g_date).strftime("%Y/%m/%d")


# ---------------------------------------------------------------------------
# Seeding helper: an approved AL LeaveRequest with a TravelLeaveDetail
# ---------------------------------------------------------------------------
def _create_al_with_travel_leave(db, emp, from_g, to_g, final_travel_days):
    city = db.query(City).filter(City.is_active.is_(True)).first()
    assert city, "test DB must have at least one active city"

    req = LeaveRequest(
        user_id=emp.user_id,
        leave_type="AL",
        from_date=from_g,
        to_date=to_g,
        days_count=(to_g - from_g).days + 1,
        status="A",
    )
    db.add(req)
    db.flush()  # obtain req.id for the detail FK

    j_year = jdatetime.date.fromgregorian(date=from_g).year
    detail = TravelLeaveDetail(
        leave_request_id=req.id,
        destination_city_id=city.id,
        destination_city_name_snapshot=city.name,
        destination_latitude_snapshot=city.latitude,
        destination_longitude_snapshot=city.longitude,
        distance_km=100.0,
        calculated_travel_days=final_travel_days,
        final_travel_days=final_travel_days,
        manual_override=False,
        jalali_year=j_year,
    )
    db.add(detail)
    db.commit()
    return req, detail


def _html_row_containing(html, needle):
    for chunk in html.split('<tr'):
        if needle in chunk:
            return chunk
    return ''


# ---------------------------------------------------------------------------
# Unit tests: build_leave_days_by_date / is_working_day / leave_type_label
# ---------------------------------------------------------------------------
# Reference week: 2024-01-01 (Mon) .. 2024-01-07 (Sun); 2024-01-05 is a Friday.
D0 = date(2024, 1, 1)
D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
D3 = date(2024, 1, 4)
FRI = date(2024, 1, 5)
D5 = date(2024, 1, 6)
D6 = date(2024, 1, 7)


def _leave(from_d, to_d, leave_type="AL", detail=None):
    return SimpleNamespace(
        from_date=from_d, to_date=to_d,
        leave_type=leave_type,
        travel_leave_detail=detail,
    )


class TestBuildLeaveDaysByDate:

    def test_first_two_working_days_are_tl(self):
        detail = SimpleNamespace(final_travel_days=2)
        leave = _leave(D0, D6, detail=detail)  # includes Friday D4
        mapping = build_leave_days_by_date([leave], {}, D0, D6)
        assert mapping[D0] == LEAVE_TYPE_TRAVEL
        assert mapping[D1] == LEAVE_TYPE_TRAVEL
        # Friday is never emitted
        assert FRI not in mapping
        # Remaining working days keep AL
        assert mapping[D2] == "AL"
        assert mapping[D3] == "AL"
        assert mapping[D5] == "AL"
        assert mapping[D6] == "AL"

    def test_friday_is_skipped_and_not_consumed(self):
        detail = SimpleNamespace(final_travel_days=2)
        # range D3..FRI..D5: Friday sits between two working days
        leave = _leave(D3, D5, detail=detail)
        mapping = build_leave_days_by_date([leave], {}, D3, D5)
        assert FRI not in mapping
        # working_seen advances only on real working days:
        # D3 -> TL (seen 0), Friday skipped, D5 -> TL (seen 1)
        assert mapping[D3] == LEAVE_TYPE_TRAVEL
        assert mapping[D5] == LEAVE_TYPE_TRAVEL

    def test_holiday_is_skipped_and_not_consumed(self):
        detail = SimpleNamespace(final_travel_days=2)
        leave = _leave(D0, D3, detail=detail)
        # treat D2 as a holiday
        mapping = build_leave_days_by_date([leave], {D2: "عید"}, D0, D3)
        assert D2 not in mapping
        # D0 TL, D1 TL; D3 remains AL (seen 2 -> not < 2)
        assert mapping[D0] == LEAVE_TYPE_TRAVEL
        assert mapping[D1] == LEAVE_TYPE_TRAVEL
        assert mapping[D3] == "AL"

    def test_tl_zero_means_all_al(self):
        detail = SimpleNamespace(final_travel_days=0)
        leave = _leave(D0, D3, detail=detail)
        mapping = build_leave_days_by_date([leave], {}, D0, D3)
        assert set(mapping.values()) == {"AL"}
        assert set(mapping.keys()) == {D0, D1, D2, D3}

    def test_tl_exceeds_working_days(self):
        detail = SimpleNamespace(final_travel_days=99)
        leave = _leave(D0, D3, detail=detail)  # 4 working days
        mapping = build_leave_days_by_date([leave], {}, D0, D3)
        assert set(mapping.keys()) == {D0, D1, D2, D3}
        assert set(mapping.values()) == {LEAVE_TYPE_TRAVEL}

    def test_window_filters_emission_but_not_counting(self):
        """Counting runs over the whole range; the window only filters output."""
        detail = SimpleNamespace(final_travel_days=2)
        leave = _leave(D0, D6, detail=detail)
        # Window is the latter half [D3, D6]; D0/D1 are the TL days but they
        # fall outside the window, so the window should show NO TL.
        mapping = build_leave_days_by_date([leave], {}, D3, D6)
        assert D0 not in mapping
        assert D1 not in mapping
        assert FRI not in mapping
        # D3 is the 3rd working day -> not TL
        assert mapping[D3] == "AL"
        assert mapping[D5] == "AL"
        assert mapping[D6] == "AL"
        assert LEAVE_TYPE_TRAVEL not in mapping.values()

    def test_leave_without_detail_is_all_original_type(self):
        leave = _leave(D0, D3, leave_type="AL", detail=None)
        mapping = build_leave_days_by_date([leave], {}, D0, D3)
        assert set(mapping.keys()) == {D0, D1, D2, D3}
        assert set(mapping.values()) == {"AL"}

    def test_multiple_leaves_do_not_interfere(self):
        d1 = _leave(D0, D1, "AL", SimpleNamespace(final_travel_days=1))
        d2 = _leave(D3, D6, "AL", SimpleNamespace(final_travel_days=2))
        mapping = build_leave_days_by_date([d1, d2], {}, D0, D6)
        # first leave: D0 TL
        assert mapping[D0] == LEAVE_TYPE_TRAVEL
        # second leave: D3 TL, D5 -> D5? working days in d2 range: D3(ws0 TL), D5(ws1 TL), D6(ws2 AL)
        assert mapping[D3] == LEAVE_TYPE_TRAVEL
        assert mapping[D5] == LEAVE_TYPE_TRAVEL
        assert mapping[D6] == "AL"
        assert FRI not in mapping

    def test_cross_month_holiday_before_visible_window_does_not_consume_tl_day(self):
        """
        A holiday before the visible window, but inside the LeaveRequest range,
        must still be excluded from working-day counting.
        """
        detail = SimpleNamespace(final_travel_days=2)

        leave = _leave(
            date(2024, 1, 5),   # Friday
            date(2024, 1, 8),   # Monday
            detail=detail,
        )

        holiday_dates = {
            date(2024, 1, 6): "تعطیل رسمی",
        }

        mapping = build_leave_days_by_date(
            [leave],
            holiday_dates,
            start_date=date(2024, 1, 6),
            end_date=date(2024, 1, 8),
        )

        # Holiday must not consume a TL slot.
        assert date(2024, 1, 6) not in mapping

        # First two actual working days are TL.
        assert mapping[date(2024, 1, 7)] == LEAVE_TYPE_TRAVEL
        assert mapping[date(2024, 1, 8)] == LEAVE_TYPE_TRAVEL


class TestIsWorkingDay:
    def test_friday_is_not_working(self):
        assert is_working_day(FRI, {}) is False

    def test_normal_day_is_working(self):
        assert is_working_day(D0, {}) is True

    def test_holiday_is_not_working(self):
        assert is_working_day(D2, {D2: "h"}) is False


class TestLeaveTypeLabel:
    def test_tl_label(self):
        assert leave_type_label("TL") == "توراهی"

    def test_al_label(self):
        assert leave_type_label("AL") == "استحقاقی"

    def test_unknown_label(self):
        assert leave_type_label("ZZ") == ''

    def test_constants(self):
        assert LEAVE_TYPE_TRAVEL == "TL"
        assert ATTENDANCE_LEAVE_TYPE_NAMES["TL"] == "توراهی"


# ---------------------------------------------------------------------------
# Route regression tests: all three attendance views
# ---------------------------------------------------------------------------
class TestUserAttendanceTLBadge:
    def test_attendance_page_shows_tl(self, db, client, make_user):
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        w1, w2, w3 = _workdays_in_current_month(3)
        req, detail = _create_al_with_travel_leave(db, emp, w1, w3, 2)

        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        # Exactly the first two working days render the TL badge.
        assert html.count("🌴 مرخصی توراهی") == 2

        # First TL day's row must carry the TL badge and NOT the AL badge.
        row = _html_row_containing(html, _jalali_str(w1))
        assert row != '', f"row for {w1} جلالی not found"
        assert "🌴 مرخصی توراهی" in row
        assert "🌴 مرخصی استحقاقی" not in row

        # The remaining day (w3) is still AL.
        row3 = _html_row_containing(html, _jalali_str(w3))
        assert "🌴 مرخصی استحقاقی" in row3
        assert "🌴 مرخصی توراهی" not in row3


class TestAdminDailyTLBadge:
    def test_admin_attendance_shows_tl(self, db, client, make_user):
        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        w1, w2, w3 = _workdays_in_current_month(3)
        _create_al_with_travel_leave(db, emp, w1, w3, 2)

        login_as(client, admin["national_code"])
        resp = client.get(f"/admin/attendance?date_str={_jalali_str(w1)}")
        assert resp.status_code == 200
        html = resp.text

        # The single target day w1 is a TL day -> exactly one TL badge.
        assert html.count("🌴 مرخصی توراهی") == 1
        assert "🌴 مرخصی توراهی" in html


class TestAdminUserAttendanceTLBadge:
    def test_admin_user_attendance_shows_tl(self, db, client, make_user):
        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        w1, w2, w3 = _workdays_in_current_month(3)
        _create_al_with_travel_leave(db, emp, w1, w3, 2)

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.get(
            f"/admin/attendance/user/{user['user_id']}?year={jy}&month={jm}"
        )
        assert resp.status_code == 200
        html = resp.text

        # First two working days render as TL.
        assert html.count("🌴 مرخصی توراهی") == 2

        row1 = _html_row_containing(html, _jalali_str(w1))
        assert row1 != '', f"row for {w1} جلالی not found"
        assert "🌴 مرخصی توراهی" in row1
        assert "🌴 مرخصی استحقاقی" not in row1

        # w3 (the third working day) stays AL.
        row3 = _html_row_containing(html, _jalali_str(w3))
        assert "🌴 مرخصی استحقاقی" in row3
        assert "🌴 مرخصی توراهی" not in row3


# ---------------------------------------------------------------------------
# Regression: a plain AL leave (no TravelLeaveDetail) still shows as AL
# ---------------------------------------------------------------------------
class TestPlainALStillShowsAl:
    def test_plain_al_no_tl_badge(self, db, client, make_user):
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        w1, w2, w3 = _workdays_in_current_month(3)
        req = LeaveRequest(
            user_id=emp.user_id,
            leave_type="AL",
            from_date=w1,
            to_date=w3,
            days_count=(w3 - w1).days + 1,
            status="A",
        )
        db.add(req)
        db.commit()
        # no TravelLeaveDetail created

        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        assert "🌴 مرخصی توراهی" not in html
        assert html.count("🌴 مرخصی استحقاقی") >= 1
