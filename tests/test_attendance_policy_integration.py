"""
Minimal integration tests for Attendance Policy → Read Paths wiring.

Proves that `compute_required_minutes_for_range()` in the service
replaces the hardcoded `N_days × 440` (DAILY_DUTY_HOURS) with a sum
of policy-derived daily required minutes.

Both user view (web/routes/attendance.py) and manager view
(web/routes/admin.py) now call this helper, so proving the helper
is sufficient to prove the integration.
"""
import pytest
from datetime import date, time, timedelta

from models.employee import Employee
from models.attendance import AttendancePolicy, AttendancePolicyDay
from sqlalchemy import and_

from web.services.attendance_policy_service import compute_required_minutes_for_range


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_policy(db, employee, start, end, working_days):
    """Seed an employment-type policy covering [start, end].

    working_days: list of (weekday, start_time, end_time, expected_minutes)
    """
    policy = AttendancePolicy(
        employment_type_code=employee.department,
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
    for wd, start_t, end_t, _expected_minutes in working_days:
        db.add(AttendancePolicyDay(
            policy_id=policy.id, weekday=wd,
            is_working_day=True, start_time=start_t, end_time=end_t,
        ))
    db.commit()
    return policy


def _cleanup_policy(db, employee):
    try:
        pids = [p[0] for p in db.query(AttendancePolicy.id).filter(
            and_(AttendancePolicy.employment_type_code == employee.department,
                 AttendancePolicy.user_id.is_(None))
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


# 2027-03-22 = Monday, 2027-03-23 = Tuesday
# Both are inside a reasonable policy range
MONDAY = date(2027, 3, 22)
TUESDAY = date(2027, 3, 23)
WEDNESDAY = date(2027, 3, 24)
THURSDAY = date(2027, 3, 25)
FRIDAY = date(2027, 3, 26)
SATURDAY = date(2027, 3, 27)
SUNDAY = date(2027, 3, 28)
WEEK_START = MONDAY
WEEK_END = THURSDAY
POLICY_START = date(2027, 3, 1)
POLICY_END = date(2027, 4, 30)

EMPTY = (set(), {}, {})


# ---------------------------------------------------------------------------
# Core acceptance tests
# ---------------------------------------------------------------------------
class TestAcceptancePolicyBasedRequiredMinutes:
    """Proves the acceptance criterion:
       Policy 07:00→13:00 → 360 min required, NOT 440 min."""

    def test_single_day_policy_07_00_to_13_00(self, db, make_user):
        """Monday with policy 07:00-13:00 → 360 required minutes, not 440."""
        user = make_user(role="employee", balance_al=None, department="1")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
        _seed_policy(db, emp, POLICY_START, POLICY_END, [
            (0, time(7, 0), time(13, 0), 360),  # Mon only
        ])

        result = compute_required_minutes_for_range(
            db=db, employee=emp, start_date=MONDAY, end_date=MONDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
        )

        assert result == 360, f"Expected 360 (policy 07:00-13:00), got {result}"
        assert result != 440, "Should NOT use legacy 440 minutes"

        _cleanup_policy(db, emp)

    def test_four_workdays_sum(self, db, make_user):
        """Mon-Thu policy 07:00-13:00 (360min each) → 4×360 = 1440."""
        user = make_user(role="employee", balance_al=None, department="1")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
        _seed_policy(db, emp, POLICY_START, POLICY_END, [
            (0, time(7, 0), time(13, 0), 360),
            (1, time(7, 0), time(13, 0), 360),
            (2, time(7, 0), time(13, 0), 360),
            (3, time(7, 0), time(13, 0), 360),
        ])

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=WEEK_START, end_date=THURSDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
        )

        expected = 4 * 360
        assert result == expected, f"Expected {expected}, got {result}"

        _cleanup_policy(db, emp)

    def test_holiday_reduces_required(self, db, make_user):
        """Holiday on Wednesday → only 3 workdays contribute 360 each = 1080."""
        user = make_user(role="employee", balance_al=None, department="1")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
        _seed_policy(db, emp, POLICY_START, POLICY_END, [
            (0, time(7, 0), time(13, 0), 360),
            (1, time(7, 0), time(13, 0), 360),
            (2, time(7, 0), time(13, 0), 360),
            (3, time(7, 0), time(13, 0), 360),
        ])

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=WEEK_START, end_date=THURSDAY,
            rest_dates=set(),
            holiday_dates={WEDNESDAY: " تعطیل رسمی"},
            leaves_by_date={},
        )

        expected = 3 * 360
        assert result == expected, f"Holiday day should be 0, got {result}"

        _cleanup_policy(db, emp)

    def test_leave_reduces_required(self, db, make_user):
        """Leave on Tuesday → only 3 workdays contribute = 1080."""
        user = make_user(role="employee", balance_al=None, department="1")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
        _seed_policy(db, emp, POLICY_START, POLICY_END, [
            (0, time(7, 0), time(13, 0), 360),
            (1, time(7, 0), time(13, 0), 360),
            (2, time(7, 0), time(13, 0), 360),
            (3, time(7, 0), time(13, 0), 360),
        ])

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=WEEK_START, end_date=THURSDAY,
            rest_dates=set(), holiday_dates={},
            leaves_by_date={TUESDAY: "AL"},
        )

        expected = 3 * 360
        assert result == expected

        _cleanup_policy(db, emp)

    def test_no_policy_fallback_440(self, db, make_user):
        """Employee with department that has no policy → 440 min fallback."""
        user = make_user(role="employee", balance_al=None, department="9")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=MONDAY, end_date=MONDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
        )

        assert result == 440, f"No-policy fallback should be 440, got {result}"

    def test_non_working_day_no_policy_returns_0(self, db, make_user):
        """Friday without policy → 0 (Iranian weekend)."""
        user = make_user(role="employee", balance_al=None, department="9")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=FRIDAY, end_date=FRIDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
        )

        assert result == 0, f"Friday without policy should be 0, got {result}"

    def test_different_policy_different_minutes(self, db, make_user):
        """Different employment type has different required minutes."""
        user = make_user(role="employee", balance_al=None, department="2")
        emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()

        # Dept 2: Mon 08:00-16:40 (520 min)
        _seed_policy(db, emp, POLICY_START, POLICY_END, [
            (0, time(8, 0), time(16, 40), 520),
        ])

        result = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=MONDAY, end_date=MONDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
        )

        assert result == 520, f"Expected 520 for dept 2, got {result}"
        assert result != 440

        _cleanup_policy(db, emp)
