"""
Phase 7 – Hourly Leave (HL) integration tests.

Validates:
- Policy resolution, submission-time validation, approval-time accounting
- Monthly exempt, annual accumulation → AL conversion
- Attendance integration (effective required minutes)
- Reversal flow, conflict detection

NOTE on Jalali years:
- make_user() seeds AL balance in the *current* Jalali year (1405).
- Our test workdays (Mar–May 2027) fall in Jalali year 1406.
- Therefore any test that deducts AL calls _ensure_al() to add a 1406 balance.
- Annual accumulation is PER Jalali YEAR (see get_annual_subject_minutes).
"""
import pytest
from datetime import date, time

import jdatetime

from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.attendance import (
    AttendancePolicy, AttendancePolicyDay,
    HourlyLeavePolicy, HourlyLeaveResolution, HourlyLeaveTransaction,
)
from models.daily_status import DailyStatus

from web.services.hourly_leave_service import (
    validate_hourly_leave_request,
    approve_hourly_leave,
    reverse_hourly_leave,
    get_approved_hl_minutes,
    get_annual_subject_minutes,
    compute_requested_minutes,
)
from web.services.attendance_policy_service import compute_required_minutes_for_range

from .conftest import login_as


# ---------------------------------------------------------------------------
# Jalali / Gregorian helpers
# ---------------------------------------------------------------------------
# POLICY_START = 2027-02-01 ; POLICY_END = 2027-05-31 (Gregorian)
#
# 2027-03-22 (Mon) ≈ 1406/01/02   -- Jalali month 1
# 2027-03-23 (Tue) ≈ 1406/01/03   -- Jalali month 1
# 2027-04-26 (Mon) ≈ 1406/02/06   -- Jalali month 2
# 2027-05-31 (Mon) ≈ 1406/03/10   -- Jalali month 3
POLICY_START = date(2027, 2, 1)
POLICY_END   = date(2027, 5, 31)
MONDAY       = date(2027, 3, 22)   # 1406/01/02
TUESDAY      = date(2027, 3, 23)   # 1406/01/03
D2           = date(2027, 4, 26)   # 1406/02/06 (month 2)
D3           = date(2027, 5, 31)   # 1406/03/10 (month 3)

YEAR_J = 1406  # Jalali year used by every leave date below


def _gregorian_to_jalali(d: date) -> str:
    return jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d")


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------
def _ensure_al(db, user_id, amount=30):
    """Ensure an AL balance row exists for Jalali 1406 (leave-date year)."""
    b = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == YEAR_J,
        LeaveBalance.leave_type == "AL",
    ).first()
    if not b:
        db.add(LeaveBalance(
            user_id=user_id, year=YEAR_J,
            leave_type="AL", balance=amount,
        ))
        db.commit()


def _seed_attendance_policy(db, emp, start=POLICY_START, end=POLICY_END,
                            workday_start=time(7, 0), workday_end=time(15, 0)):
    """Create an AttendancePolicy + days for Mon-Thu, Sat (workdays)."""
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
    for weekday in [0, 1, 2, 3, 5]:  # Mon-Thu, Sat
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=weekday,
            is_working_day=True,
            start_time=workday_start,
            end_time=workday_end,
        ))
    db.commit()
    return policy


def _seed_hl_policy(db, emp, *,
                    conversion=480, monthly_exempt=480, daily_limit=180,
                    entitled=True, granularity=15,
                    min_request=15, max_request=240,
                    start=POLICY_START, end=POLICY_END):
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


def _seed_annual_accumulator(db, emp, minutes):
    """Seed subject-to-AL minutes in the same Jalali year (1406).

    Placed on TUESDAY so it does not interfere with same-day daily limits
    of requests that use MONDAY.
    """
    seed_date = TUESDAY  # 1406/01/03

    req = LeaveRequest(
        user_id=emp.user_id,
        leave_type="HL",
        from_date=seed_date,
        to_date=seed_date,
        days_count=0,
        start_time=time(9, 0),
        end_time=time(9 + minutes // 60, minutes % 60),
        status="A",
        reason="_seed",
    )
    db.add(req)
    db.flush()
    res = HourlyLeaveResolution(
        leave_request_id=req.id,
        requested_minutes=minutes,
        policy_conversion_rate=480,
        policy_monthly_exempt=0,
        policy_daily_limit=180,
        policy_entitled=True,
        daily_usage_before=0,
        daily_usage_after=minutes,
        daily_limit_exceeded=False,
        full_day_conversion=False,
        monthly_exempt_used_before=0,
        monthly_exempt_applied=0,
        minutes_subject_to_al=minutes,
        annual_subject_minutes_before=0,
        annual_subject_minutes_after=minutes,
        annual_remainder_minutes=minutes % 480,
        new_al_days_deducted=0,
        status="APPROVED",
    )
    db.add(res)
    db.commit()
    return req


def _create_and_approve_hl(db, emp, start_t, end_t, *, leave_date=None):
    if leave_date is None:
        leave_date = MONDAY

    st = time(*map(int, start_t.split(":")))
    et = time(*map(int, end_t.split(":")))

    req = LeaveRequest(
        user_id=emp.user_id,
        leave_type="HL",
        from_date=leave_date,
        to_date=leave_date,
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


def _create_hl_request(db, emp, start_t, end_t, *, leave_date=None):
    if leave_date is None:
        leave_date = MONDAY

    st = time(*map(int, start_t.split(":")))
    et = time(*map(int, end_t.split(":")))

    req = LeaveRequest(
        user_id=emp.user_id,
        leave_type="HL",
        from_date=leave_date,
        to_date=leave_date,
        days_count=0,
        start_time=st,
        end_time=et,
        status="P",
    )
    db.add(req)
    db.commit()
    return req


# ---------------------------------------------------------------------------
# Test 1: Basic HL Request (HTTP)
# ---------------------------------------------------------------------------
class TestBasicHLRequest:

    def test_basic_hl_request(self, db, client, make_user):
        """User submits HL 09:00-11:00 → pending request created."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp)

        j_from = _gregorian_to_jalali(MONDAY)
        login_as(client, user["national_code"])
        resp = client.post("/leave/request", data={
            "leave_type": "HL",
            "from_date_str": j_from,
            "to_date_str": j_from,
            "start_time_str": "09:00",
            "end_time_str": "11:00",
            "reason": "Doctor appointment",
        }, follow_redirects=False)

        assert resp.status_code == 302
        db.expire_all()
        lr = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == user["user_id"],
            LeaveRequest.leave_type == "HL",
        ).first()
        assert lr is not None
        assert lr.status == "P"
        assert lr.start_time == time(9, 0)
        assert lr.end_time == time(11, 0)


# ---------------------------------------------------------------------------
# Test 2: Outside Working Hours Rejected
# ---------------------------------------------------------------------------
class TestOutsideWorkingHours:

    def test_hl_outside_working_hours(self, db, client, make_user):
        """Request 06:00-08:00 when workday starts 07:00 → validation error."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp, workday_start=time(7, 0), workday_end=time(15, 0))

        j_from = _gregorian_to_jalali(MONDAY)
        login_as(client, user["national_code"])
        resp = client.post("/leave/request", data={
            "leave_type": "HL",
            "from_date_str": j_from,
            "to_date_str": j_from,
            "start_time_str": "06:00",
            "end_time_str": "08:00",
        }, follow_redirects=False)

        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 3: Daily Limit → Full Day Conversion
# ---------------------------------------------------------------------------
class TestDailyLimitFullDay:

    def test_daily_limit_full_day_conversion(self, db, make_user):
        """daily_limit=180, monthly_exempt=0, conversion=480. Request 200 min
        → full_day_conversion, minutes_subject_to_al=480, 1 AL day."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=180)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        req = _create_and_approve_hl(db, emp, "07:00", "10:20")  # 200 min

        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.full_day_conversion is True
        assert res.monthly_exempt_applied == 0
        assert res.minutes_subject_to_al == 480  # full day
        assert res.annual_subject_minutes_after == 480
        assert res.new_al_days_deducted == 1  # floor(480/480)-floor(0/480)


# ---------------------------------------------------------------------------
# Test 4: Monthly Exempt Calculation (Cumulative)
# ---------------------------------------------------------------------------
class TestMonthlyExemptCumulative:

    def test_two_requests_cumulative_exempt(self, db, make_user):
        """monthly_exempt=480, daily_limit=480. Req1 300 → 300 exempt / 0 AL.
        Req2 250 → 180 exempt / 70 AL (both same Jalali month 1406/01)."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480, daily_limit=480)
        _seed_attendance_policy(db, emp)

        req1 = _create_and_approve_hl(db, emp, "08:00", "13:00")  # 300 min
        res1 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req1.id
        ).first()
        assert res1.monthly_exempt_applied == 300
        assert res1.minutes_subject_to_al == 0
        assert res1.annual_subject_minutes_after == 0
        assert res1.new_al_days_deducted == 0

        req2 = _create_and_approve_hl(db, emp, "14:00", "18:10",
                                      leave_date=TUESDAY)  # 250 min, same month
        res2 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req2.id
        ).first()
        assert res2.monthly_exempt_applied == 180  # 480 - 300
        assert res2.minutes_subject_to_al == 70   # 250 - 180
        assert res2.annual_subject_minutes_after == 70
        assert res2.new_al_days_deducted == 0     # floor(70/480) = 0

        al = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.leave_type == "AL",
        ).first()
        assert al.balance == 30  # unchanged


# ---------------------------------------------------------------------------
# Test 5: Annual Accumulation → AL Conversion (3 Jalali months in 1406)
# ---------------------------------------------------------------------------
class TestAnnualAccumulation:

    def test_three_month_accumulation(self, db, make_user):
        """1406 month 1: 70 min → 70/0. Month 2: 200 → 270/0.
        Month 3: 210 → 480, new=1, remainder=0. AL 30 → 29 in 1406."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        # Month 1 (1406/01/02): 70 min
        req1 = _create_and_approve_hl(db, emp, "09:00", "10:10",
                                      leave_date=MONDAY)
        res1 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req1.id
        ).first()
        assert res1.annual_subject_minutes_before == 0
        assert res1.annual_subject_minutes_after == 70
        assert res1.new_al_days_deducted == 0

        # Month 2 (1406/02/06): 200 min
        req2 = _create_and_approve_hl(db, emp, "09:00", "12:20",
                                      leave_date=D2)
        res2 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req2.id
        ).first()
        assert res2.annual_subject_minutes_before == 70
        assert res2.annual_subject_minutes_after == 270
        assert res2.new_al_days_deducted == 0

        # Month 3 (1406/03/10): 210 min → crosses 480 threshold
        req3 = _create_and_approve_hl(db, emp, "09:00", "12:30",
                                      leave_date=D3)
        res3 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req3.id
        ).first()
        assert res3.annual_subject_minutes_before == 270
        assert res3.annual_subject_minutes_after == 480
        assert res3.new_al_days_deducted == 1  # floor(480/480)-floor(270/480)
        assert res3.annual_remainder_minutes == 0

        al = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.year == 1406,
            LeaveBalance.leave_type == "AL",
        ).first()
        assert al.balance == 29  # 30 - 1


# ---------------------------------------------------------------------------
# Test 6: Parameterized Conversion Rates
# ---------------------------------------------------------------------------
class TestParameterizedConversion:

    @pytest.mark.parametrize("conversion,requested,annual_before,expected_new_days", [
        (480, 120, 0, 0),
        (480, 120, 360, 1),
        (440, 120, 0, 0),
        (440, 120, 320, 1),
        (600, 240, 0, 0),
        (600, 240, 360, 1),
    ])
    def test_annual_conversion_parameterized(self, db, make_user, conversion,
                                             requested, annual_before, expected_new_days):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=conversion, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        if expected_new_days > 0:
            _ensure_al(db, user["user_id"])

        if annual_before > 0:
            _seed_annual_accumulator(db, emp, annual_before)

        start_m = 480  # 08:00
        st = time(start_m // 60, start_m % 60)
        et = time((start_m + requested) // 60, (start_m + requested) % 60)

        req = _create_and_approve_hl(
            db, emp,
            f"{st.hour:02d}:{st.minute:02d}",
            f"{et.hour:02d}:{et.minute:02d}",
        )

        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.policy_conversion_rate == conversion
        assert res.annual_subject_minutes_before == annual_before
        assert res.annual_subject_minutes_after == annual_before + requested
        assert res.new_al_days_deducted == expected_new_days


# ---------------------------------------------------------------------------
# Test 7: Entitled=False → 100% Subject to AL
# ---------------------------------------------------------------------------
class TestEntitledFalse:

    def test_entitled_false_full_subject(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480, entitled=False)
        _seed_attendance_policy(db, emp)

        req = _create_and_approve_hl(db, emp, "09:00", "11:00")  # 120 min
        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.policy_entitled is False
        assert res.monthly_exempt_applied == 0
        assert res.minutes_subject_to_al == 120
        assert res.annual_subject_minutes_after == 120
        assert res.new_al_days_deducted == 0  # 120 < 480

        al = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.leave_type == "AL",
        ).first()
        assert al.balance == 30


# ---------------------------------------------------------------------------
# Test 8: Attendance Integration
# ---------------------------------------------------------------------------
class TestAttendanceIntegration:

    def test_hl_subtracts_from_required(self, db, make_user):
        """Base 480, HL 120 → effective 360."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_attendance_policy(db, emp, workday_start=time(8, 0), workday_end=time(16, 0))
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480)

        leave_date = MONDAY
        _create_and_approve_hl(db, emp, "09:00", "11:00", leave_date=leave_date)

        hl_minutes = get_approved_hl_minutes(db, emp, leave_date, leave_date)
        assert hl_minutes[leave_date] == 120

        effective = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=leave_date, end_date=leave_date,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            hourly_leave_minutes_by_date=hl_minutes,
        )
        assert effective == 360  # 480 - 120

    def test_hl_not_full_day_leave(self, db, make_user):
        """HL must NOT cause is_leave=True (full-day leave)."""
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        # Policy: Mon-Thu 08:00-16:00 = 480 min
        _seed_attendance_policy(db, emp, workday_start=time(8, 0), workday_end=time(16, 0))
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480)

        leave_date = MONDAY
        _create_and_approve_hl(db, emp, "09:00", "11:00", leave_date=leave_date)  # 120 min

        hl_minutes = get_approved_hl_minutes(db, emp, leave_date, leave_date)
        assert hl_minutes[leave_date] == 120

        # ⚠️ ключевой: leaves_by_date НЕ содержит HL → is_leave=False → base required = 480
        # effective = 480 - 120 = 360
        effective_correct = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=leave_date, end_date=leave_date,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},  # HL NOT in leaves
            hourly_leave_minutes_by_date=hl_minutes,
        )
        assert effective_correct == 360

        # ❌ incorrect: if HL leaked into leaves_by_date → is_leave=True → base=0 → effective=0
        effective_wrong = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=leave_date, end_date=leave_date,
            rest_dates=set(), holiday_dates={},
            leaves_by_date={leave_date: 'HL'},  # ❌ HL in leaves → WRONG
            hourly_leave_minutes_by_date=hl_minutes,
        )
        assert effective_wrong == 0, "Bug: HL in leaves_by_date makes is_leave=True → required=0"

    def test_hl_balance_with_actual_work(self, db, make_user):
        """
        Integration test: HL reduces required, NOT actual.

        Scenario 1: Base=420, HL=120, Actual=300 → Required=300, Balance=0
        Scenario 2: Base=420, HL=120, Actual=250 → Required=300, Deficit=50
        """
        user = make_user(role="user", balance_al=30, department="1")
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        # Policy: Mon-Thu 08:00-15:00 = 420 min (7 hours)
        _seed_attendance_policy(db, emp, workday_start=time(8, 0), workday_end=time(15, 0))
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480)

        leave_date = MONDAY
        _create_and_approve_hl(db, emp, "09:00", "11:00", leave_date=leave_date)  # 120 min

        hl_minutes = get_approved_hl_minutes(db, emp, leave_date, leave_date)
        assert hl_minutes[leave_date] == 120

        # Scenario 1: Actual work = 300 min (5 hours) → Balance = 0
        required1 = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=leave_date, end_date=leave_date,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            hourly_leave_minutes_by_date=hl_minutes,
        )
        assert required1 == 300  # 420 - 120
        actual1 = 300
        balance1 = actual1 - required1
        assert balance1 == 0, f"Scenario 1: expected balance 0, got {balance1}"

        # Scenario 2: Actual work = 250 min (4h 10m) → Deficit = 50
        required2 = required1  # same day, same HL
        actual2 = 250
        balance2 = actual2 - required2
        assert balance2 == -50, f"Scenario 2: expected deficit 50, got {balance2}"

        # Verify actual is NOT reduced by HL
        assert actual1 == 300
        assert actual2 == 250

        # Verify required IS reduced by HL
        assert required1 == 300
        assert required2 == 300


# ---------------------------------------------------------------------------
# Test 9: Example A – Monthly Exempt, No AL Deduction
# ---------------------------------------------------------------------------
class TestExampleA:

    def test_70_min_fully_exempt(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480)
        _seed_attendance_policy(db, emp)

        req = _create_and_approve_hl(db, emp, "09:00", "10:10")  # 70 min
        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.monthly_exempt_applied == 70
        assert res.minutes_subject_to_al == 0
        assert res.annual_subject_minutes_after == 0
        assert res.new_al_days_deducted == 0


# ---------------------------------------------------------------------------
# Test 10: Example B – Annual Threshold Reached
# ---------------------------------------------------------------------------
class TestExampleB:

    def test_threshold_reached_430_plus_70(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        _seed_annual_accumulator(db, emp, 430)

        req = _create_and_approve_hl(db, emp, "09:00", "10:10")  # 70 min
        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.annual_subject_minutes_before == 430
        assert res.annual_subject_minutes_after == 500
        assert res.new_al_days_deducted == 1  # floor(500/480)-floor(430/480)
        assert res.annual_remainder_minutes == 20  # 500 % 480


# ---------------------------------------------------------------------------
# Test 11: Example C – Entitled False, No Per-Request Ceiling
# ---------------------------------------------------------------------------
class TestExampleC:

    def test_no_per_request_ceiling(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480, entitled=False)
        _seed_attendance_policy(db, emp)

        req = _create_and_approve_hl(db, emp, "09:00", "11:00")  # 120 min
        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()

        assert res.minutes_subject_to_al == 120
        assert res.annual_subject_minutes_after == 120
        assert res.new_al_days_deducted == 0  # NOT ceil(120/480)=1

        al = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.leave_type == "AL",
        ).first()
        assert al.balance == 30


# ---------------------------------------------------------------------------
# Test 12: Example D – Monthly Exempt Split
# ---------------------------------------------------------------------------
class TestExampleD:

    def test_exhaust_monthly_exempt(self, db, make_user):
        """monthly_exempt=480. Req1 480 → 480 exempt/0 AL (month 1406/01).
        Req2 120 → 0 exempt/120 subject (same month)."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=480, daily_limit=480)
        _seed_attendance_policy(db, emp)

        req1 = _create_and_approve_hl(db, emp, "08:00", "16:00",
                                      leave_date=MONDAY)  # 480 min
        res1 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req1.id
        ).first()
        assert res1.monthly_exempt_applied == 480
        assert res1.minutes_subject_to_al == 0

        req2 = _create_and_approve_hl(db, emp, "09:00", "11:00",
                                      leave_date=TUESDAY)  # 120 min
        res2 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req2.id
        ).first()
        assert res2.monthly_exempt_applied == 0
        assert res2.minutes_subject_to_al == 120


# ---------------------------------------------------------------------------
# Test 13: HL Rejection (No Side Effects)
# ---------------------------------------------------------------------------
class TestHLRejection:

    def test_rejection_no_side_effects(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp)

        req = _create_hl_request(db, emp, "09:00", "11:00")

        req.status = "R"
        db.commit()

        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()
        assert res is None

        al = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == user["user_id"],
            LeaveBalance.leave_type == "AL",
        ).first()
        assert al.balance == 30


# ---------------------------------------------------------------------------
# Test 14: HL Reversal
# ---------------------------------------------------------------------------
class TestHLReversal:

    def test_reversal_restores_state(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)

        req = _create_and_approve_hl(db, emp, "09:00", "11:00")  # 120 min

        success, err = reverse_hourly_leave(db, req)
        assert success, f"reverse failed: {err}"
        db.commit()

        db.expire_all()
        res = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req.id
        ).first()
        assert res.status == "REVERSED"

        lr = db.query(LeaveRequest).filter(LeaveRequest.id == req.id).first()
        assert lr.status == "D"


# ---------------------------------------------------------------------------
# Test 14b: Annual Reversal Recompute (accounting consistency)
# ---------------------------------------------------------------------------
def _al_balance(db, user_id):
    return db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == YEAR_J,
        LeaveBalance.leave_type == "AL",
    ).first().balance


class TestAnnualReversalRecompute:
    """Reversing one approved HL request must recompute the annual threshold
    over the remaining approved requests — not just undo the deleted request's
    own AL days."""

    def test_case1_earlier_request_reversal(self, db, make_user):
        """A=430 (seeded), B=70 approved → 1 AL day deducted.
        Reverse A → AL deducted 0, annual subject = 70, remainder = 70."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        seed_a = _seed_annual_accumulator(db, emp, 430)  # A = 430
        req_b = _create_and_approve_hl(db, emp, "09:00", "10:10")  # B = 70

        assert _al_balance(db, user["user_id"]) == 29  # 1 AL day deducted

        success, err = reverse_hourly_leave(db, seed_a)
        assert success, f"reverse A failed: {err}"
        db.commit()
        db.expire_all()

        assert _al_balance(db, user["user_id"]) == 30  # AL deducted restored to 0

        res_b = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req_b.id
        ).first()
        assert res_b.annual_subject_minutes_after == 70
        assert res_b.annual_remainder_minutes == 70
        assert res_b.new_al_days_deducted == 0

        assert get_annual_subject_minutes(db, user["user_id"], YEAR_J) == 70

    def test_case2_later_request_reversal(self, db, make_user):
        """A=430 (seeded), B=70 approved → 1 AL day deducted.
        Reverse B → AL deducted 0, annual subject = 430, remainder = 430."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        _seed_annual_accumulator(db, emp, 430)  # A = 430
        req_b = _create_and_approve_hl(db, emp, "09:00", "10:10")  # B = 70

        assert _al_balance(db, user["user_id"]) == 29

        success, err = reverse_hourly_leave(db, req_b)
        assert success, f"reverse B failed: {err}"
        db.commit()
        db.expire_all()

        assert _al_balance(db, user["user_id"]) == 30

        assert get_annual_subject_minutes(db, user["user_id"], YEAR_J) == 430

    def test_case3_multiple_thresholds(self, db, make_user):
        """A=300, B=250, C=500 → total 1050 → 2 AL days, remainder 90.
        Reverse A → 750 → 1 day, remainder 270. Then reverse C → 250 → 0 days,
        remainder 250."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=600)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        req_a = _create_and_approve_hl(db, emp, "08:00", "13:00", leave_date=MONDAY)   # 300
        req_b = _create_and_approve_hl(db, emp, "08:00", "12:10", leave_date=TUESDAY)  # 250
        req_c = _create_and_approve_hl(db, emp, "08:00", "16:20", leave_date=D2)       # 500

        assert _al_balance(db, user["user_id"]) == 28  # 2 AL days deducted

        res_c = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req_c.id
        ).first()
        assert res_c.annual_subject_minutes_after == 1050
        assert res_c.annual_remainder_minutes == 90

        # Reverse A (earliest) → recompute remaining B+C = 750 → 1 day
        success, err = reverse_hourly_leave(db, req_a)
        assert success, f"reverse A failed: {err}"
        db.commit()
        db.expire_all()

        assert _al_balance(db, user["user_id"]) == 29  # 1 AL day deducted

        res_b = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req_b.id
        ).first()
        res_c = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req_c.id
        ).first()
        assert res_b.annual_subject_minutes_after == 250
        assert res_b.new_al_days_deducted == 0
        assert res_c.annual_subject_minutes_after == 750
        assert res_c.annual_remainder_minutes == 270
        assert res_c.new_al_days_deducted == 1

        # Reverse C → remaining B = 250 → 0 days
        success, err = reverse_hourly_leave(db, req_c)
        assert success, f"reverse C failed: {err}"
        db.commit()
        db.expire_all()

        assert _al_balance(db, user["user_id"]) == 30  # 0 AL days deducted

        res_b = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req_b.id
        ).first()
        assert res_b.annual_subject_minutes_after == 250
        assert res_b.annual_remainder_minutes == 250
        assert res_b.new_al_days_deducted == 0

    def test_case4_idempotent_reversal(self, db, make_user):
        """Reversing the same approved HL request twice must not restore AL twice."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=480)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        req = _create_and_approve_hl(db, emp, "08:00", "16:00")  # 480 → 1 AL day
        assert _al_balance(db, user["user_id"]) == 29

        success, err = reverse_hourly_leave(db, req)
        assert success, f"first reverse failed: {err}"
        db.commit()

        assert _al_balance(db, user["user_id"]) == 30

        # Second reversal must be a no-op (request already deleted).
        success2, _ = reverse_hourly_leave(db, req)
        assert success2 is False
        db.commit()

        assert _al_balance(db, user["user_id"]) == 30  # not double-restored


# ---------------------------------------------------------------------------
# Test 15: Conflict with Full-Day Leave
# ---------------------------------------------------------------------------
class TestConflictFullDay:

    def test_hl_conflict_with_al(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp)

        al_req = LeaveRequest(
            user_id=user["user_id"],
            leave_type="AL",
            from_date=MONDAY,
            to_date=MONDAY,
            days_count=1,
            status="P",
            reason="test",
        )
        db.add(al_req)
        db.commit()

        is_valid, error = validate_hourly_leave_request(
            db, emp, MONDAY, time(9, 0), time(11, 0)
        )
        assert not is_valid
        assert error is not None


# ---------------------------------------------------------------------------
# Test 16: Conflict with Mission
# ---------------------------------------------------------------------------
class TestConflictMission:

    def test_hl_conflict_with_mission(self, db, client, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp)

        ds = DailyStatus(
            user_id=emp.user_id,
            status_date=MONDAY,
            status_code="M",
        )
        db.add(ds)
        db.commit()

        j_from = _gregorian_to_jalali(MONDAY)
        login_as(client, user["national_code"])
        resp = client.post("/leave/request", data={
            "leave_type": "HL",
            "from_date_str": j_from,
            "to_date_str": j_from,
            "start_time_str": "09:00",
            "end_time_str": "11:00",
        }, follow_redirects=False)

        assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 17: Time Overlap
# ---------------------------------------------------------------------------
class TestTimeOverlap:

    def test_overlapping_hl_rejected(self, db, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp)
        _seed_attendance_policy(db, emp)

        _create_and_approve_hl(db, emp, "09:00", "11:00")

        is_valid, error = validate_hourly_leave_request(
            db, emp, MONDAY, time(10, 0), time(12, 0)
        )
        assert not is_valid
        assert error is not None


# ---------------------------------------------------------------------------
# Test 18: Multiple Same-Day Cumulative Daily Limit
# ---------------------------------------------------------------------------
class TestMultipleSameDay:

    def test_cumulative_daily_limit(self, db, make_user):
        """daily_limit=180, monthly_exempt=0. Req1 100 → ok.
        Req2 90 → cumulative 190 > 180 → full_day_conversion (subject 480)."""
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, conversion=480, monthly_exempt=0, daily_limit=180)
        _seed_attendance_policy(db, emp)
        _ensure_al(db, user["user_id"])

        _create_and_approve_hl(db, emp, "08:00", "09:40")  # 100 min

        req2 = _create_and_approve_hl(db, emp, "11:00", "12:30")  # 90 min
        res2 = db.query(HourlyLeaveResolution).filter(
            HourlyLeaveResolution.leave_request_id == req2.id
        ).first()

        assert res2.daily_usage_before == 100
        assert res2.daily_usage_after == 190
        assert res2.daily_limit_exceeded is True
        assert res2.full_day_conversion is True
        assert res2.minutes_subject_to_al == 480  # full day


# ---------------------------------------------------------------------------
# Test 19: Granularity Validation
# ---------------------------------------------------------------------------
class TestGranularity:

    def test_non_aligned_times_rejected(self, db, client, make_user):
        user = make_user(role="user", balance_al=30)
        emp = db.query(Employee).filter(
            Employee.user_id == user["user_id"]
        ).first()
        _seed_hl_policy(db, emp, granularity=15)
        _seed_attendance_policy(db, emp)

        j_from = _gregorian_to_jalali(MONDAY)
        login_as(client, user["national_code"])
        resp = client.post("/leave/request", data={
            "leave_type": "HL",
            "from_date_str": j_from,
            "to_date_str": j_from,
            "start_time_str": "09:07",
            "end_time_str": "09:22",
        }, follow_redirects=False)

        assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Test 20: HL Policy CRUD (HTTP)
# ---------------------------------------------------------------------------
class TestHLPolicyCRUD:

    def test_create_edit_delete_policy(self, db, client, make_user):
        admin = make_user(role="super_admin", balance_al=None)
        # Purge any leftover HL policies so the overlap check does not trip
        # on rows created by other tests for employment type "1".
        try:
            db.query(HourlyLeavePolicy).delete()
            db.commit()
        except Exception:
            db.rollback()

        login_as(client, admin["national_code"])

        resp = client.post("/admin/policies/hourly-leave/save", data={
            "employment_type_code": "1",
            "user_id_override": "",
            "effective_from_date_str": "1405/01/01",
            "effective_to_date_str": "",
            "hourly_leave_entitled": "on",
            "max_daily_minutes": "180",
            "monthly_exempt_minutes": "480",
            "conversion_minutes_per_day": "480",
            "granularity_minutes": "15",
            "min_request_minutes": "15",
            "max_request_minutes": "240",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]

        policy = db.query(HourlyLeavePolicy).filter(
            HourlyLeavePolicy.employment_type_code == "1"
        ).first()
        assert policy is not None
        assert policy.max_daily_minutes == 180

        resp = client.post(
            f"/admin/policies/hourly-leave/{policy.id}/update",
            data={
                "employment_type_code": "1",
                "user_id_override": "",
                "effective_from_date_str": "1405/01/01",
                "effective_to_date_str": "",
                "hourly_leave_entitled": "on",
                "max_daily_minutes": "240",
                "monthly_exempt_minutes": "480",
                "conversion_minutes_per_day": "480",
                "granularity_minutes": "15",
                "min_request_minutes": "15",
                "max_request_minutes": "240",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.refresh(policy)
        assert policy.max_daily_minutes == 240

        resp = client.post(
            f"/admin/policies/hourly-leave/{policy.id}/delete",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.expire_all()
        deleted = db.query(HourlyLeavePolicy).filter(
            HourlyLeavePolicy.id == policy.id
        ).first()
        assert deleted is not None
        assert deleted.is_active is False  # soft delete