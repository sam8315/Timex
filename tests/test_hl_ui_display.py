"""
Phase 7 – Hourly Leave (HL) UI display tests.

Validates:
- format_hl_display() produces correct output strings
- Approved HL appears as badge in all 4 target pages
- HL does NOT convert person_status from P to L in reports
- Pending/Rejected HL does NOT appear
- Required minutes / worked hours are NOT affected
"""
import pytest
from datetime import date, datetime, time, timedelta

import jdatetime

from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.attendance import (
    Attendance, AttendancePolicy, AttendancePolicyDay,
    HourlyLeavePolicy, HourlyLeaveResolution,
)
from web.services.hourly_leave_service import (
    format_hl_display,
    approve_hourly_leave,
    get_approved_hl_minutes,
)

from .conftest import login_as, TestingSessionLocal


# ---------------------------------------------------------------------------
# Jalali / Gregorian helpers
# ---------------------------------------------------------------------------
def _current_jalali_month():
    """Return (year, month) of current Jalali date."""
    today = jdatetime.date.today()
    return today.year, today.month


def _workday_in_current_month():
    """Find a workday (non-Friday) in the current Jalali month's middle third."""
    jy, jm = _current_jalali_month()
    if jm == 12:
        j_end = jdatetime.date(jy, 12, 29)
    else:
        j_end = jdatetime.date(jy, jm + 1, 1) - timedelta(days=1)
    j_start = jdatetime.date(jy, jm, 1)

    days_in_month = (j_end - j_start).days + 1
    # pick day ~10 (middle-ish, avoids edge cases)
    day_num = min(10, days_in_month)
    candidate = jdatetime.date(jy, jm, day_num)

    # If Friday (weekday=4 in Python), shift forward
    while candidate.togregorian().weekday() == 4:
        candidate += timedelta(days=1)
        if candidate > j_end:
            candidate = jdatetime.date(jy, jm, 1)
            while candidate.togregorian().weekday() == 4:
                candidate += timedelta(days=1)
            break

    return candidate


# ---------------------------------------------------------------------------
# Seeding helpers (same as integration tests, inlined for isolation)
# ---------------------------------------------------------------------------
def _ensure_al(db, user_id, amount=30):
    year_j = jdatetime.date.today().year
    b = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == year_j,
        LeaveBalance.leave_type == "AL",
    ).first()
    if not b:
        db.add(LeaveBalance(
            user_id=user_id, year=year_j,
            leave_type="AL", balance=amount,
        ))
        db.commit()


def _seed_attendance_policy(db, emp, start, end,
                            workday_start=time(7, 0), workday_end=time(15, 0)):
    try:
        pids = [p[0] for p in db.query(AttendancePolicy.id).filter(
            AttendancePolicy.employment_type_code == emp.department,
            AttendancePolicy.user_id.is_(None),
        ).all()]
        if pids:
            db.query(AttendancePolicyDay).filter(
                AttendancePolicyDay.policy_id.in_(pids)
            ).delete(synchronize_session=False)
            db.query(AttendancePolicy).filter(
                AttendancePolicy.id.in_(pids)
            ).delete(synchronize_session=False)
            db.commit()
    except Exception:
        db.rollback()

    policy = AttendancePolicy(
        employment_type_code=emp.department,
        user_id=None,
        effective_from_date=start,
        effective_to_date=end,
        late_enabled=True,
        late_allowed_minutes=5,
        late_reference_mode="FIXED_TIME",
        early_leave_enabled=True,
        early_leave_allowed_minutes=5,
        early_leave_reference_mode="FIXED_TIME",
        is_active=True,
    )
    db.add(policy)
    db.flush()
    for weekday in range(7):  # all days (Friday filtered by is_working_day)
        is_friday = weekday == 4
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=weekday,
            is_working_day=not is_friday,
            start_time=workday_start,
            end_time=workday_end,
        ))
    db.commit()
    return policy


def _seed_hl_policy(db, emp, *,
                    conversion=480, monthly_exempt=480, daily_limit=180,
                    entitled=True, granularity=15,
                    min_request=15, max_request=240,
                    start, end):
    try:
        existing = db.query(HourlyLeavePolicy).filter(
            HourlyLeavePolicy.employment_type_code == emp.department,
            HourlyLeavePolicy.user_id.is_(None),
        ).all()
        for p in existing:
            db.delete(p)
        db.commit()
    except Exception:
        db.rollback()

    policy = HourlyLeavePolicy(
        employment_type_code=emp.department,
        user_id=None,
        effective_from_date=start,
        effective_to_date=end,
        is_active=True,
        hourly_leave_entitled=entitled,
        max_daily_minutes=daily_limit,
        monthly_exempt_minutes=monthly_exempt,
        conversion_minutes_per_day=conversion,
        granularity_minutes=granularity,
        min_request_minutes=min_request,
        max_request_minutes=max_request,
    )
    db.add(policy)
    db.commit()
    return policy


def _create_and_approve_hl(db, emp, leave_date, start_t, end_t):
    st = time(*map(int, start_t.split(":")))
    et = time(*map(int, end_t.split(":")))

    # psycopg2 only adapts datetime.date; jdatetime.date must be converted
    g_date = leave_date.togregorian()

    req = LeaveRequest(
        user_id=emp.user_id,
        leave_type="HL",
        from_date=g_date,
        to_date=g_date,
        days_count=0,
        start_time=st,
        end_time=et,
        status="P",
    )
    db.add(req)
    db.commit()

    success, err = approve_hourly_leave(db, req, "admin")
    assert success, f"approve_hourly_leave failed: {err}"
    db.commit()
    return req


def _seed_day_punches(db, emp, g_date,
                      start_t=time(7, 0), end_t=time(15, 0)):
    """Seed a real pair of attendance punches (full present day) on g_date.

    The person genuinely worked this day, so the report/user page must keep
    person_status = P (حاضر) even though an approved HL also exists.
    Naive datetimes are used so Postgres stores them in server-local time and
    func.date(timestamp) == g_date.
    """
    db.add(Attendance(
        user_id=emp.user_id,
        timestamp=datetime(g_date.year, g_date.month, g_date.day,
                           start_t.hour, start_t.minute),
        punch=0,
        source="M",
    ))
    db.add(Attendance(
        user_id=emp.user_id,
        timestamp=datetime(g_date.year, g_date.month, g_date.day,
                           end_t.hour, end_t.minute),
        punch=1,
        source="M",
    ))
    db.commit()


def _html_row_containing(html, needle):
    """Return the <tr>…</tr> segment that contains `needle` (else '')."""
    for chunk in html.split('<tr'):
        if needle in chunk:
            return chunk
    return ''


# ---------------------------------------------------------------------------
# Test 1: format_hl_display() exact output
# ---------------------------------------------------------------------------
class TestFormatHLDisplay:

    @pytest.mark.parametrize("minutes, expected", [
        (0, ''),
        (120, 'مرخصی ساعتی 2:00'),
        (15, 'مرخصی ساعتی 0:15'),
        (180, 'مرخصی ساعتی 3:00'),
        (65, 'مرخصی ساعتی 1:05'),
        (480, 'مرخصی ساعتی 8:00'),
    ])
    def test_format_hl_display(self, minutes, expected):
        assert format_hl_display(minutes) == expected


# ---------------------------------------------------------------------------
# Test 2: User attendance page shows HL badge
# ---------------------------------------------------------------------------
class TestUserAttendanceHLBadge:

    def test_attendance_page_shows_hl(self, db, client, make_user):
        """GET /attendance?year=Y&month=M with approved HL → badge visible."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_start = workday.togregorian()
        g_end = g_start + timedelta(days=1)

        _seed_attendance_policy(db, emp, start=g_start - timedelta(days=30),
                                end=g_end + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_start - timedelta(days=30),
                        end=g_end + timedelta(days=30))

        req = _create_and_approve_hl(db, emp, workday, "09:00", "11:00")  # 120 min

        # Person also actually worked this day (full 07:00–15:00) → day must stay کامل
        _seed_day_punches(db, emp, g_start)

        # Verify the data layer is correct
        hl_minutes = get_approved_hl_minutes(db, emp, g_start, g_start)
        assert hl_minutes.get(g_start) == 120

        # Hit the page
        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        # HL badge present with correct text
        assert 'مرخصی ساعتی 2:00' in html
        # Main status was NOT overwritten: the worked day still shows ✅ کامل
        # and the day was NOT converted to full-day leave
        assert '✅ کامل' in html


# ---------------------------------------------------------------------------
# Test 3: Admin daily attendance page shows HL badge
# ---------------------------------------------------------------------------
class TestAdminDailyHLBadge:

    def test_admin_attendance_shows_hl(self, db, client, make_user):
        """GET /admin/attendance?date=... with approved HL → badge visible."""
        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_date = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_date - timedelta(days=30),
                                end=g_date + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_date - timedelta(days=30),
                        end=g_date + timedelta(days=30))

        req = _create_and_approve_hl(db, emp, workday, "09:00", "11:00")  # 120 min

        j_date_str = workday.strftime("%Y/%m/%d")
        login_as(client, admin["national_code"])
        # NB: the route reads the `date_str` query param (web/routes/admin.py).
        resp = client.get(f"/admin/attendance?date_str={j_date_str}")
        assert resp.status_code == 200
        html = resp.text

        assert 'مرخصی ساعتی 2:00' in html


# ---------------------------------------------------------------------------
# Test 4: Detailed monthly report shows HL, person_status stays P
# ---------------------------------------------------------------------------
class TestDetailedReportHLBadge:

    def test_detailed_report_shows_hl(self, db, client, make_user, monkeypatch):
        """POST /reports/monthly-detailed → HL badge, person_status=P."""
        # The report generator opens its own session via database.engine.SessionLocal
        # (the production DB), bypassing the test client's get_db override. Route it
        # to the test DB so it sees the seeded data (same as the get_db override).
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_date = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_date - timedelta(days=30),
                                end=g_date + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_date - timedelta(days=30),
                        end=g_date + timedelta(days=30))

        req = _create_and_approve_hl(db, emp, workday, "09:00", "11:00")  # 120 min

        # Person genuinely worked this day too → person_status must stay P (حاضر)
        _seed_day_punches(db, emp, g_date)

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.post("/reports/monthly-detailed", data={
            "target_user_id": user["user_id"],
            "year": jy,
            "month": jm,
        })
        assert resp.status_code == 200
        html = resp.text

        # HL badge present
        assert 'مرخصی ساعتی 2:00' in html

        # person_status must NOT be L for this day (HL doesn't convert to full-day leave).
        # Locate the table row of the workday: it must show the present badge (حاضر)
        # and NOT the leave badge (مرخصی), with the HL badge as a separate add-on.
        j_date_str = workday.strftime("%Y/%m/%d")
        row = _html_row_containing(html, j_date_str)
        assert row != '', f"ردیف روز {j_date_str} در گزارش یافت نشد"
        assert 'status-badge">حاضر' in row, \
            "person_status باید P (حاضر) بماند — HL نباید روز را به مرخصی کامل تبدیل کند"
        assert 'status-badge">مرخصی' not in row, \
            "person_status نباید به L (مرخصی) تبدیل شود"
        assert 'مرخصی ساعتی 2:00' in row, \
            "بج جداگانه HL باید در همان ردیف کنار وضعیت اصلی نمایش داده شود"


# ---------------------------------------------------------------------------
# Test 5: Full monthly report shows HL, person_status stays P
# ---------------------------------------------------------------------------
class TestFullReportHLBadge:

    def test_full_report_shows_hl(self, db, client, make_user, monkeypatch):
        """POST /reports/monthly-full → HL badge, person_status=P."""
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_date = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_date - timedelta(days=30),
                                end=g_date + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_date - timedelta(days=30),
                        end=g_date + timedelta(days=30))

        req = _create_and_approve_hl(db, emp, workday, "09:00", "11:00")  # 120 min

        # Person genuinely worked this day too → person_status must stay P (حاضر)
        _seed_day_punches(db, emp, g_date)

        jy, jm = _current_jalali_month()
        login_as(client, admin["national_code"])
        resp = client.post("/reports/monthly-full", data={
            "target_user_id": user["user_id"],
            "year": jy,
            "month": jm,
        })
        assert resp.status_code == 200
        html = resp.text

        # HL badge present
        assert 'مرخصی ساعتی 2:00' in html

        # person_status must NOT be L for this day (HL doesn't convert to full-day leave)
        j_date_str = workday.strftime("%Y/%m/%d")
        row = _html_row_containing(html, j_date_str)
        assert row != '', f"ردیف روز {j_date_str} در گزارش یافت نشد"
        assert 'status-pill">حاضر' in row, \
            "person_status باید P (حاضر) بماند — HL نباید روز را به مرخصی کامل تبدیل کند"
        assert 'status-pill">مرخصی' not in row, \
            "person_status نباید به L (مرخصی) تبدیل شود"
        assert 'مرخصی ساعتی 2:00' in row


# ---------------------------------------------------------------------------
# Test 6: Pending/Rejected HL does NOT appear
# ---------------------------------------------------------------------------
class TestPendingRejectedHLHidden:

    def test_pending_hl_not_shown(self, db, client, make_user):
        """Pending HL must NOT produce a badge on any page."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_start = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_start - timedelta(days=30),
                                end=g_start + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_start - timedelta(days=30),
                        end=g_start + timedelta(days=30))

        # Create HL but leave it PENDING (do not approve)
        req = LeaveRequest(
            user_id=emp.user_id,
            leave_type="HL",
            from_date=g_start,
            to_date=g_start,
            days_count=0,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="P",  # pending
        )
        db.add(req)
        db.commit()

        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        # HL badge must NOT appear
        assert 'مرخصی ساعتی 2:00' not in html

    def test_rejected_hl_not_shown(self, db, client, make_user):
        """Rejected HL must NOT produce a badge."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_start = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_start - timedelta(days=30),
                                end=g_start + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_start - timedelta(days=30),
                        end=g_start + timedelta(days=30))

        req = LeaveRequest(
            user_id=emp.user_id,
            leave_type="HL",
            from_date=g_start,
            to_date=g_start,
            days_count=0,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="R",  # rejected
        )
        db.add(req)
        db.commit()

        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        assert 'مرخصی ساعتی 2:00' not in html


# ---------------------------------------------------------------------------
# Test 7: HL does NOT affect required minutes or actual worked hours
# ---------------------------------------------------------------------------
class TestHLDoesNotAffectWorkMetrics:

    def test_required_minutes_preserved(self, db, make_user):
        """HL reduces required minutes (existing behavior preserved), not doubled."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_date = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_date - timedelta(days=30),
                                end=g_date + timedelta(days=30),
                                workday_start=time(8, 0), workday_end=time(16, 0))
        _seed_hl_policy(db, emp, start=g_date - timedelta(days=30),
                        end=g_date + timedelta(days=30),
                        conversion=480, monthly_exempt=480)

        _create_and_approve_hl(db, emp, workday, "09:00", "11:00")  # 120 min

        hl_minutes = get_approved_hl_minutes(db, emp, g_date, g_date)
        assert hl_minutes.get(g_date) == 120

        # Verify that the data layer reports correct values
        # Required = 480 - 120 = 360 (reduced, existing behavior)
        # Actual = 0 (no attendance records in test)
        # HL does NOT double-subtract
        from web.services.attendance_policy_service import compute_required_minutes_for_range
        required = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=g_date, end_date=g_date,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            hourly_leave_minutes_by_date=hl_minutes,
        )
        assert required == 360  # 480 - 120, correctly reduced


# ---------------------------------------------------------------------------
# Test 8: HL + full-day leave coexistence
# ---------------------------------------------------------------------------
class TestHLWithFullDayLeave:

    def test_both_badges_appear(self, db, client, make_user):
        """If HL and full-day leave exist on same day, both are preserved."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()

        workday = _workday_in_current_month()
        g_start = workday.togregorian()

        _seed_attendance_policy(db, emp, start=g_start - timedelta(days=30),
                                end=g_start + timedelta(days=30))
        _seed_hl_policy(db, emp, start=g_start - timedelta(days=30),
                        end=g_start + timedelta(days=30))

        # Full-day leave (AL)
        al_req = LeaveRequest(
            user_id=emp.user_id,
            leave_type="AL",
            from_date=g_start,
            to_date=g_start,
            days_count=1,
            status="A",
            reason="test",
        )
        db.add(al_req)

        # Also HL on same day (should not conflict since both are approved)
        hl_req = LeaveRequest(
            user_id=emp.user_id,
            leave_type="HL",
            from_date=g_start,
            to_date=g_start,
            days_count=0,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status="A",
        )
        db.add(hl_req)
        db.commit()

        jy, jm = _current_jalali_month()
        login_as(client, user["national_code"])
        resp = client.get(f"/attendance?year={jy}&month={jm}")
        assert resp.status_code == 200
        html = resp.text

        # Full-day leave badge present (main status preserved)
        assert '🌴 مرخصی استحقاقی' in html
        # HL badge also present as a separate add-on
        assert 'مرخصی ساعتی 2:00' in html
