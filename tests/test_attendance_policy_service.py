"""
Phase 5.7: Tests for Attendance Policy Service

Tests cover:
- Policy resolution (priority, date filtering, override)
- Weekly schedule (working days, times)
- Late and early leave calculations
- Balance calculations
- Holiday and leave handling
- Grace period logic
"""
import pytest
from datetime import date, time, datetime, timedelta
from unittest.mock import MagicMock

from web.services.attendance_policy_service import (
    resolve_policy,
    resolve_policy_day,
    resolve_required_minutes,
    compute_late,
    compute_early_leave,
    compute_daily_balance,
    calculate_daily_attendance,
    time_to_minutes,
    minutes_to_hours_hhmm,
    DEFAULT_REQUIRED_MINUTES,
)


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_time_to_minutes_basic(self):
        assert time_to_minutes(time(7, 20)) == 440

    def test_time_to_minutes_midnight(self):
        assert time_to_minutes(time(0, 0)) == 0

    def test_time_to_minutes_end_of_day(self):
        assert time_to_minutes(time(23, 59)) == 1439

    def test_time_to_minutes_none(self):
        assert time_to_minutes(None) == 0

    def test_minutes_to_hours_hhmm_positive(self):
        assert minutes_to_hours_hhmm(440) == '7:20'

    def test_minutes_to_hours_hhmm_zero(self):
        assert minutes_to_hours_hhmm(0) == '0:00'

    def test_minutes_to_hours_hhmm_negative(self):
        assert minutes_to_hours_hhmm(-30) == '-0:30'

    def test_minutes_to_hours_hhmm_none(self):
        assert minutes_to_hours_hhmm(None) == '-'

    def test_default_required_minutes(self):
        assert DEFAULT_REQUIRED_MINUTES == 440  # 7:20


class TestResolvePolicy:
    """Tests for policy resolution logic."""

    def test_resolve_policy_employee_override_priority(self, db, make_user):
        """Employee override should take priority over employment type policy."""
        from models.employee import Employee
        from models.attendance import AttendancePolicy, AttendancePolicyDay
        from models.user import User

        # Create user
        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        # Create employee with department code '1'
        emp = Employee(user_id=user_id, department='1', first_name='Test', last_name='User')
        db.add(emp)
        db.flush()

        # Create employment type policy
        type_policy = AttendancePolicy(
            employment_type_code='1',
            user_id=None,
            effective_from_date=date(2026, 1, 1),
            late_enabled=True,
            late_allowed_minutes=5,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=True,
            early_leave_allowed_minutes=5,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(type_policy)
        db.flush()

        # Add schedule for type policy (Mon 8:00-16:40)
        db.add(AttendancePolicyDay(
            policy_id=type_policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(8, 0),
            end_time=time(16, 40),
            required_minutes=520
        ))

        # Create employee override policy
        override_policy = AttendancePolicy(
            employment_type_code='1',
            user_id=user_id,
            effective_from_date=date(2026, 1, 1),
            late_enabled=True,
            late_allowed_minutes=15,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=False,
            early_leave_allowed_minutes=0,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(override_policy)
        db.flush()

        # Add schedule for override (Mon 9:00-17:00)
        db.add(AttendancePolicyDay(
            policy_id=override_policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(9, 0),
            end_time=time(17, 0),
            required_minutes=480
        ))
        db.commit()

        # Test: Override should be returned
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        resolved = resolve_policy(db, employee, date(2026, 6, 1))  # A Monday

        assert resolved is not None
        assert resolved.is_employee_override == True
        assert resolved.policy.late_allowed_minutes == 15
        assert resolved.policy.early_leave_allowed_minutes == 0

    def test_resolve_policy_employment_type_fallback(self, db, make_user):
        """Should fall back to employment type policy when no override exists."""
        from models.employee import Employee
        from models.attendance import AttendancePolicy, AttendancePolicyDay

        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, department='2', first_name='Test', last_name='User')
        db.add(emp)
        db.flush()

        # Only employment type policy
        type_policy = AttendancePolicy(
            employment_type_code='2',
            user_id=None,
            effective_from_date=date(2026, 1, 1),
            late_enabled=True,
            late_allowed_minutes=10,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(type_policy)
        db.flush()

        db.add(AttendancePolicyDay(
            policy_id=type_policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(8, 0),
            end_time=time(16, 40),
            required_minutes=520
        ))
        db.commit()

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        resolved = resolve_policy(db, employee, date(2026, 6, 1))

        assert resolved is not None
        assert resolved.is_employee_override == False
        assert resolved.policy.employment_type_code == '2'

    def test_resolve_policy_no_policy_returns_none(self, db, make_user):
        """Should return None when no policy exists."""
        from models.employee import Employee

        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, department='9', first_name='Test', last_name='User')
        db.add(emp)
        db.commit()

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        resolved = resolve_policy(db, employee, date(2026, 6, 1))

        assert resolved is None

    def test_resolve_policy_date_filtering(self, db, make_user):
        """Policy should only apply within effective_from/to dates."""
        from models.employee import Employee
        from models.attendance import AttendancePolicy, AttendancePolicyDay

        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, department='1', first_name='Test', last_name='User')
        db.add(emp)
        db.flush()

        # Policy only valid for June 2026
        policy = AttendancePolicy(
            employment_type_code='1',
            user_id=None,
            effective_from_date=date(2026, 6, 1),
            effective_to_date=date(2026, 6, 30),
            late_enabled=True,
            late_allowed_minutes=5,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=True,
            early_leave_allowed_minutes=5,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(policy)
        db.flush()

        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(8, 0),
            end_time=time(16, 40),
            required_minutes=520
        ))
        db.commit()

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()

        # Before effective period
        resolved_before = resolve_policy(db, employee, date(2026, 5, 31))
        assert resolved_before is None

        # During effective period
        resolved_during = resolve_policy(db, employee, date(2026, 6, 15))
        assert resolved_during is not None

        # After effective period
        resolved_after = resolve_policy(db, employee, date(2026, 7, 1))
        assert resolved_after is None


class TestResolveRequiredMinutes:
    """Tests for required minutes calculation."""

    def test_working_day(self, db, make_user):
        """Working day should return policy's required_minutes."""
        from models.employee import Employee
        from models.attendance import AttendancePolicy, AttendancePolicyDay

        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, department='1', first_name='Test', last_name='User')
        db.add(emp)
        db.flush()

        policy = AttendancePolicy(
            employment_type_code='1',
            user_id=None,
            effective_from_date=date(2026, 1, 1),
            late_enabled=True,
            late_allowed_minutes=5,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=True,
            early_leave_allowed_minutes=5,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(policy)
        db.flush()

        # 7:20 = 440 minutes
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(7, 20),
            end_time=time(14, 40),
            required_minutes=440
        ))
        db.commit()

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        resolved = resolve_policy(db, employee, date(2026, 6, 1))

        # Monday = weekday 0
        required = resolve_required_minutes(resolved, date(2026, 6, 1))
        assert required == 440

    def test_non_working_day(self, db, make_user):
        """Non-working day should return 0."""
        from models.employee import Employee
        from models.attendance import AttendancePolicy, AttendancePolicyDay

        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, department='1', first_name='Test', last_name='User')
        db.add(emp)
        db.flush()

        policy = AttendancePolicy(
            employment_type_code='1',
            user_id=None,
            effective_from_date=date(2026, 1, 1),
            late_enabled=True,
            late_allowed_minutes=5,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=True,
            early_leave_allowed_minutes=5,
            early_leave_reference_mode='FIXED_TIME',
            is_active=True
        )
        db.add(policy)
        db.flush()

        # Friday (weekday=4) is not working
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=4,
            is_working_day=False,
            start_time=None,
            end_time=None,
            required_minutes=0
        ))
        db.commit()

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        resolved = resolve_policy(db, employee, date(2026, 6, 5))  # A Friday

        required = resolve_required_minutes(resolved, date(2026, 6, 5))
        assert required == 0

    def test_holiday_returns_zero(self):
        """Holiday should return 0 regardless of policy."""
        required = resolve_required_minutes(None, date(2026, 6, 1), is_holiday=True)
        assert required == 0

    def test_leave_returns_zero(self):
        """Leave day should return 0."""
        required = resolve_required_minutes(None, date(2026, 6, 1), is_leave=True)
        assert required == 0

    def test_mission_returns_zero(self):
        """Mission day should return 0."""
        required = resolve_required_minutes(None, date(2026, 6, 1), is_mission=True)
        assert required == 0

    def test_rest_returns_zero(self):
        """Rest day should return 0."""
        required = resolve_required_minutes(None, date(2026, 6, 1), is_rest=True)
        assert required == 0

    def test_no_policy_returns_default(self):
        """Without policy, should return DEFAULT_REQUIRED_MINUTES."""
        required = resolve_required_minutes(None, date(2026, 6, 1))
        assert required == DEFAULT_REQUIRED_MINUTES


class TestComputeLate:
    """Tests for late calculation."""

    def test_no_late_when_on_time(self):
        """No late when arriving before start."""
        result = compute_late(
            late_enabled=True,
            late_allowed_minutes=10,
            start_time=time(8, 0),
            first_enter=time(7, 50),
            late_reference_mode='FIXED_TIME'
        )
        assert result == (False, 0, 10, 0)

    def test_late_within_grace(self):
        """Late within grace period should not be violation."""
        result = compute_late(
            late_enabled=True,
            late_allowed_minutes=10,
            start_time=time(8, 0),
            first_enter=time(8, 5),
            late_reference_mode='FIXED_TIME'
        )
        is_late, total_late, allowed, violation = result
        assert is_late == True
        assert total_late == 5
        assert allowed == 10
        assert violation == 0

    def test_late_exceeds_grace(self):
        """Late exceeding grace period should be violation."""
        result = compute_late(
            late_enabled=True,
            late_allowed_minutes=10,
            start_time=time(8, 0),
            first_enter=time(8, 15),
            late_reference_mode='FIXED_TIME'
        )
        is_late, total_late, allowed, violation = result
        assert is_late == True
        assert total_late == 15
        assert allowed == 10
        assert violation == 5

    def test_late_disabled(self):
        """Late disabled should not track."""
        result = compute_late(
            late_enabled=False,
            late_allowed_minutes=10,
            start_time=time(8, 0),
            first_enter=time(8, 15),
            late_reference_mode='FIXED_TIME'
        )
        is_late, total_late, allowed, violation = result
        assert is_late == False
        assert total_late == 0

    def test_no_attendance(self):
        """No attendance should not be late."""
        result = compute_late(
            late_enabled=True,
            late_allowed_minutes=10,
            start_time=time(8, 0),
            first_enter=None,
            late_reference_mode='FIXED_TIME'
        )
        assert result == (False, 0, 10, 0)


class TestComputeEarlyLeave:
    """Tests for early leave calculation."""

    def test_no_early_leave_when_staying(self):
        """No early leave when leaving after end time."""
        result = compute_early_leave(
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            end_time=time(16, 40),
            last_exit=time(16, 45),
            early_reference_mode='FIXED_TIME'
        )
        assert result == (False, 0, 10, 0)

    def test_early_leave_within_grace(self):
        """Early leave within grace should not be violation."""
        result = compute_early_leave(
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            end_time=time(16, 40),
            last_exit=time(16, 35),
            early_reference_mode='FIXED_TIME'
        )
        is_early, total_early, allowed, violation = result
        assert is_early == True
        assert total_early == 5
        assert allowed == 10
        assert violation == 0

    def test_early_leave_exceeds_grace(self):
        """Early leave exceeding grace should be violation."""
        result = compute_early_leave(
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            end_time=time(16, 40),
            last_exit=time(16, 20),
            early_reference_mode='FIXED_TIME'
        )
        is_early, total_early, allowed, violation = result
        assert is_early == True
        assert total_early == 20
        assert allowed == 10
        assert violation == 10

    def test_early_leave_disabled(self):
        """Early leave disabled should not track."""
        result = compute_early_leave(
            early_leave_enabled=False,
            early_leave_allowed_minutes=10,
            end_time=time(16, 40),
            last_exit=time(16, 20),
            early_reference_mode='FIXED_TIME'
        )
        is_early, total_early, allowed, violation = result
        assert is_early == False
        assert total_early == 0


class TestComputeDailyBalance:
    """Tests for balance calculation."""

    def test_exact_work(self):
        """Exact work should be balanced."""
        balance = compute_daily_balance(
            actual_minutes=440,
            required_minutes=440
        )
        assert balance == 0

    def test_overtime(self):
        """More work than required = positive balance."""
        balance = compute_daily_balance(
            actual_minutes=480,
            required_minutes=440
        )
        assert balance == 40

    def test_undertime(self):
        """Less work than required = negative balance."""
        balance = compute_daily_balance(
            actual_minutes=400,
            required_minutes=440
        )
        assert balance == -40

    def test_zero_actual_on_working_day(self):
        """Zero actual on working day = full negative balance."""
        balance = compute_daily_balance(
            actual_minutes=0,
            required_minutes=440
        )
        assert balance == -440

    def test_zero_required_no_balance(self):
        """Zero required (non-working day) = no balance."""
        balance = compute_daily_balance(
            actual_minutes=0,
            required_minutes=0
        )
        assert balance == 0


class TestMinutesToHoursHhmmFormat:
    """Additional format tests."""

    def test_one_hour(self):
        assert minutes_to_hours_hhmm(60) == '1:00'

    def test_minutes_only(self):
        assert minutes_to_hours_hhmm(45) == '0:45'

    def test_large_hours(self):
        assert minutes_to_hours_hhmm(600) == '10:00'
