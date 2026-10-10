"""
Phase 5.7 / Phase 7: Tests for Attendance Policy Service

Contract (current implementation — Phase 7 aligned):
- AttendancePolicyDay.required_minutes is a derived @property (start/end),
  not a writable column.
- compute_late / compute_early_leave take datetime check-in/out + scheduled
  time, return dicts (not tuples).
- is_late / is_early_leave mean grace exceeded (chargeable delay).
- When past grace, *_violation_minutes = full total (not total - grace).
- compute_daily_balance(actual, required, late_info, early_info) =
  actual - required; late/early are not subtracted again.

Tests cover:
- Policy resolution (priority, date filtering, override)
- Weekly schedule (working days, times)
- Late and early leave calculations
- Balance calculations
- Holiday and leave handling
- Grace period logic
"""
from datetime import date, time, datetime, timedelta

from web.services.attendance_policy_service import (
    resolve_policy,
    resolve_required_minutes,
    compute_late,
    compute_early_leave,
    compute_late_early_for_day,
    compute_daily_balance,
    time_to_minutes,
    minutes_to_hours_hhmm,
    DEFAULT_REQUIRED_MINUTES,
    ResolvedPolicy,
    PolicyDayInfo,
)

# Fixed calendar day for combining time → datetime in pure unit tests
_REF_DAY = date(2026, 6, 1)


def _dt(t: time) -> datetime:
    """Combine reference date with a wall-clock time."""
    return datetime.combine(_REF_DAY, t)


def _cleanup_policies(db, employment_codes=None, user_ids=None):
    """Remove AttendancePolicy rows so DB tests do not leak across cases."""
    from sqlalchemy import or_
    from models.attendance import AttendancePolicy, AttendancePolicyDay

    try:
        db.rollback()
    except Exception:
        pass

    clauses = []
    if employment_codes:
        clauses.append(AttendancePolicy.employment_type_code.in_(employment_codes))
    if user_ids:
        clauses.append(AttendancePolicy.user_id.in_(user_ids))
    if not clauses:
        return

    pids = [row[0] for row in db.query(AttendancePolicy.id).filter(or_(*clauses)).all()]
    if not pids:
        return
    db.query(AttendancePolicyDay).filter(
        AttendancePolicyDay.policy_id.in_(pids)
    ).delete(synchronize_session=False)
    db.query(AttendancePolicy).filter(
        AttendancePolicy.id.in_(pids)
    ).delete(synchronize_session=False)
    db.commit()


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

        # Create user
        user = make_user(
            role='employee',
            balance_al=None,
            create_employee=False,
            contract_type_code='1',
        )
        user_id = user['user_id']
        _cleanup_policies(db, employment_codes=['1'], user_ids=[user_id])

        # Create employee with department code '1'
        emp = Employee(user_id=user_id, membership_type_code='1', first_name='Test', last_name='User')
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

        # Add schedule for type policy (Mon 8:00-16:40 → 520 min derived)
        db.add(AttendancePolicyDay(
            policy_id=type_policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(8, 0),
            end_time=time(16, 40),
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

        # Add schedule for override (Mon 9:00-17:00 → 480 min derived)
        db.add(AttendancePolicyDay(
            policy_id=override_policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(9, 0),
            end_time=time(17, 0),
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
            contract_type_code='2',
        )
        user_id = user['user_id']
        _cleanup_policies(db, employment_codes=['2'], user_ids=[user_id])

        emp = Employee(user_id=user_id, membership_type_code='2', first_name='Test', last_name='User')
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
            contract_type_code='9',
        )
        user_id = user['user_id']

        emp = Employee(user_id=user_id, first_name='Test', last_name='User')
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
            contract_type_code='1',
        )
        user_id = user['user_id']
        _cleanup_policies(db, employment_codes=['1'], user_ids=[user_id])

        emp = Employee(user_id=user_id, membership_type_code='1', first_name='Test', last_name='User')
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
            contract_type_code='1',
        )
        user_id = user['user_id']
        _cleanup_policies(db, employment_codes=['1'], user_ids=[user_id])

        emp = Employee(user_id=user_id, membership_type_code='1', first_name='Test', last_name='User')
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

        # 7:20–14:40 → 440 minutes (derived property)
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=0,
            is_working_day=True,
            start_time=time(7, 20),
            end_time=time(14, 40),
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
            contract_type_code='1',
        )
        user_id = user['user_id']
        _cleanup_policies(db, employment_codes=['1'], user_ids=[user_id])

        emp = Employee(user_id=user_id, membership_type_code='1', first_name='Test', last_name='User')
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
    """Tests for late calculation (current dict contract)."""

    def test_no_late_when_on_time(self):
        """No late when arriving before start."""
        result = compute_late(
            actual_first_check_in=_dt(time(7, 50)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result == {
            'total_late_minutes': 0,
            'late_violation_minutes': 0,
            'is_late': False,
        }

    def test_late_within_grace(self):
        """Delay within grace: total tracked, no violation, is_late=False."""
        result = compute_late(
            actual_first_check_in=_dt(time(8, 5)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['total_late_minutes'] == 5
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False

    def test_late_exceeds_grace(self):
        """Delay past grace: chargeable = full total (not total - grace)."""
        result = compute_late(
            actual_first_check_in=_dt(time(8, 15)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['total_late_minutes'] == 15
        assert result['late_violation_minutes'] == 15
        assert result['is_late'] is True

    def test_late_grace_boundary_seven_fifteen(self):
        """Start 07:00, grace 15: arrive 07:15 → no chargeable late."""
        result = compute_late(
            actual_first_check_in=_dt(time(7, 15)),
            scheduled_start=time(7, 0),
            late_enabled=True,
            late_allowed_minutes=15,
            reference_mode='FIXED_TIME',
        )
        assert result['total_late_minutes'] == 15
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False

    def test_late_past_grace_full_sixteen(self):
        """Start 07:00, grace 15: arrive 07:16 → chargeable 16 (full)."""
        result = compute_late(
            actual_first_check_in=_dt(time(7, 16)),
            scheduled_start=time(7, 0),
            late_enabled=True,
            late_allowed_minutes=15,
            reference_mode='FIXED_TIME',
        )
        assert result['total_late_minutes'] == 16
        assert result['late_violation_minutes'] == 16
        assert result['is_late'] is True

    def test_late_disabled(self):
        """Late disabled should not track."""
        result = compute_late(
            actual_first_check_in=_dt(time(8, 15)),
            scheduled_start=time(8, 0),
            late_enabled=False,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['is_late'] is False
        assert result['total_late_minutes'] == 0
        assert result['late_violation_minutes'] == 0

    def test_no_attendance(self):
        """No attendance should not be late."""
        result = compute_late(
            actual_first_check_in=None,
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result == {
            'total_late_minutes': 0,
            'late_violation_minutes': 0,
            'is_late': False,
        }


class TestComputeEarlyLeave:
    """Tests for early leave calculation (current dict contract)."""

    def test_no_early_leave_when_staying(self):
        """No early leave when leaving after end time."""
        result = compute_early_leave(
            actual_last_check_out=_dt(time(16, 45)),
            scheduled_end=time(16, 40),
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result == {
            'total_early_leave_minutes': 0,
            'early_leave_violation_minutes': 0,
            'is_early_leave': False,
        }

    def test_early_leave_within_grace(self):
        """Early within grace: total tracked, no violation, is_early_leave=False."""
        result = compute_early_leave(
            actual_last_check_out=_dt(time(16, 35)),
            scheduled_end=time(16, 40),
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['total_early_leave_minutes'] == 5
        assert result['early_leave_violation_minutes'] == 0
        assert result['is_early_leave'] is False

    def test_early_leave_exceeds_grace(self):
        """Early past grace: chargeable = full total (not total - grace)."""
        result = compute_early_leave(
            actual_last_check_out=_dt(time(16, 20)),
            scheduled_end=time(16, 40),
            early_leave_enabled=True,
            early_leave_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['total_early_leave_minutes'] == 20
        assert result['early_leave_violation_minutes'] == 20
        assert result['is_early_leave'] is True

    def test_early_leave_disabled(self):
        """Early leave disabled should not track."""
        result = compute_early_leave(
            actual_last_check_out=_dt(time(16, 20)),
            scheduled_end=time(16, 40),
            early_leave_enabled=False,
            early_leave_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert result['is_early_leave'] is False
        assert result['total_early_leave_minutes'] == 0
        assert result['early_leave_violation_minutes'] == 0


class TestComputeDailyBalance:
    """Tests for balance = actual - required (late/early not double-counted)."""

    def test_exact_work(self):
        """Exact work should be balanced."""
        balance = compute_daily_balance(
            actual_minutes=440,
            required_minutes=440,
            late_info={},
            early_info={},
        )
        assert balance == 0

    def test_overtime(self):
        """More work than required = positive balance."""
        balance = compute_daily_balance(
            actual_minutes=480,
            required_minutes=440,
            late_info={},
            early_info={},
        )
        assert balance == 40

    def test_undertime(self):
        """Less work than required = negative balance."""
        balance = compute_daily_balance(
            actual_minutes=400,
            required_minutes=440,
            late_info={},
            early_info={},
        )
        assert balance == -40

    def test_zero_actual_on_working_day(self):
        """Zero actual on working day = full negative balance."""
        balance = compute_daily_balance(
            actual_minutes=0,
            required_minutes=440,
            late_info={},
            early_info={},
        )
        assert balance == -440

    def test_zero_required_no_balance(self):
        """Zero required (non-working day) = no balance."""
        balance = compute_daily_balance(
            actual_minutes=0,
            required_minutes=0,
            late_info={},
            early_info={},
        )
        assert balance == 0

    def test_late_early_do_not_affect_balance(self):
        """Regression: late/early info must not change balance (no double count)."""
        balance = compute_daily_balance(
            actual_minutes=430,
            required_minutes=440,
            late_info={'total_late_minutes': 20, 'late_violation_minutes': 10, 'is_late': True},
            early_info={'total_early_leave_minutes': 15, 'early_leave_violation_minutes': 5, 'is_early_leave': True},
        )
        assert balance == -10


class TestMinutesToHoursHhmmFormat:
    """Additional format tests."""

    def test_one_hour(self):
        assert minutes_to_hours_hhmm(60) == '1:00'

    def test_minutes_only(self):
        assert minutes_to_hours_hhmm(45) == '0:45'

    def test_large_hours(self):
        assert minutes_to_hours_hhmm(600) == '10:00'


class TestPhase7RegressionCases:
    """Phase 7 regression cases A–E against the current Policy contract."""

    def test_case_a_exact_required_no_late_early(self):
        """required=8h, actual=8h → late=0, early=0, balance=0."""
        late = compute_late(
            actual_first_check_in=_dt(time(8, 0)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        early = compute_early_leave(
            actual_last_check_out=_dt(time(16, 0)),
            scheduled_end=time(16, 0),
            early_leave_enabled=True,
            early_leave_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        balance = compute_daily_balance(480, 480, late, early)
        assert late['total_late_minutes'] == 0
        assert early['total_early_leave_minutes'] == 0
        assert balance == 0

    def test_case_b_short_actual_balance_independent_of_late(self):
        """required=8h, actual=7h50m → balance=-10; late is schedule-based separately."""
        late = compute_late(
            actual_first_check_in=_dt(time(8, 10)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        balance = compute_daily_balance(470, 480, late, {})
        assert late['total_late_minutes'] == 10
        assert late['is_late'] is True
        assert balance == -10

    def test_case_c_overtime_balance(self):
        """required=8h, actual=8h30m → balance=+30."""
        balance = compute_daily_balance(510, 480, {}, {})
        assert balance == 30

    def test_case_d_fractional_seconds_truncate_to_int_minutes(self):
        """Sub-minute diffs truncate via int(seconds/60); unit is whole minutes."""
        # 90 seconds late → 1 minute (truncation, not round-half-up)
        enter = datetime.combine(_REF_DAY, time(8, 0)) + timedelta(seconds=90)
        result = compute_late(
            actual_first_check_in=enter,
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        assert result['total_late_minutes'] == 1

        # 59 seconds late → 0 minutes
        enter_59 = datetime.combine(_REF_DAY, time(8, 0)) + timedelta(seconds=59)
        result_59 = compute_late(
            actual_first_check_in=enter_59,
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        assert result_59['total_late_minutes'] == 0

    def test_case_e_boundary_zero_and_missing_schedule(self):
        """Missing schedule / zero grace / exact boundary."""
        no_schedule = compute_late(
            actual_first_check_in=_dt(time(9, 0)),
            scheduled_start=None,
            late_enabled=True,
            late_allowed_minutes=0,
            reference_mode='FIXED_TIME',
        )
        assert no_schedule['total_late_minutes'] == 0

        # Exactly at grace boundary: 10 late, grace 10 → not a violation
        at_grace = compute_late(
            actual_first_check_in=_dt(time(8, 10)),
            scheduled_start=time(8, 0),
            late_enabled=True,
            late_allowed_minutes=10,
            reference_mode='FIXED_TIME',
        )
        assert at_grace['total_late_minutes'] == 10
        assert at_grace['late_violation_minutes'] == 0
        assert at_grace['is_late'] is False


class TestComputeLateEarlyForDay:
    """Tests for the shared late/early helper used by reports and views."""

    def _resolved(
        self,
        late_allowed=10,
        early_allowed=10,
        late_on=True,
        early_on=True,
        start=time(8, 0),
        end=time(16, 40),
    ):
        from types import SimpleNamespace

        policy = SimpleNamespace(
            late_enabled=late_on,
            late_allowed_minutes=late_allowed,
            late_reference_mode='FIXED_TIME',
            early_leave_enabled=early_on,
            early_leave_allowed_minutes=early_allowed,
            early_leave_reference_mode='FIXED_TIME',
        )
        start_m = start.hour * 60 + start.minute
        end_m = end.hour * 60 + end.minute
        days = {
            _REF_DAY.weekday(): PolicyDayInfo(
                weekday=_REF_DAY.weekday(),
                is_working_day=True,
                start_time=start,
                end_time=end,
                required_minutes=max(0, end_m - start_m),
            )
        }
        return ResolvedPolicy(
            policy=policy,
            employment_type_code='1',
            policy_days=days,
            is_employee_override=False,
        )

    def test_within_grace_no_violation(self):
        result = compute_late_early_for_day(
            resolved=self._resolved(),
            target_date=_REF_DAY,
            first_enter=_dt(time(8, 5)),
            last_exit=_dt(time(16, 35)),
        )
        assert result['late_minutes'] == 5
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False
        assert result['early_leave_minutes'] == 5
        assert result['early_leave_violation_minutes'] == 0
        assert result['is_early_leave'] is False

    def test_past_grace_violation(self):
        result = compute_late_early_for_day(
            resolved=self._resolved(late_allowed=5, early_allowed=5),
            target_date=_REF_DAY,
            first_enter=_dt(time(8, 20)),
            last_exit=_dt(time(16, 20)),
        )
        assert result['late_violation_minutes'] == 20
        assert result['is_late'] is True
        assert result['early_leave_violation_minutes'] == 20
        assert result['is_early_leave'] is True

    def test_disabled_policy_zeros_violation(self):
        result = compute_late_early_for_day(
            resolved=self._resolved(late_on=False, early_on=False),
            target_date=_REF_DAY,
            first_enter=_dt(time(9, 0)),
            last_exit=_dt(time(15, 0)),
        )
        assert result['late_violation_minutes'] == 0
        assert result['early_leave_violation_minutes'] == 0
        assert result['is_late'] is False
        assert result['is_early_leave'] is False

    def test_no_resolved_policy_defaults(self):
        result = compute_late_early_for_day(
            resolved=None,
            target_date=_REF_DAY,
            first_enter=_dt(time(9, 0)),
            last_exit=_dt(time(15, 0)),
        )
        assert result['late_minutes'] == 0
        assert result['early_leave_minutes'] == 0

    def test_skip_leave_or_rest_zeros_all(self):
        """On leave/rest days, late/early must not be calculated even with punches."""
        result = compute_late_early_for_day(
            resolved=self._resolved(late_allowed=0, early_allowed=0),
            target_date=_REF_DAY,
            first_enter=_dt(time(9, 0)),
            last_exit=_dt(time(15, 0)),
            skip=True,
        )
        assert result['late_minutes'] == 0
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False
        assert result['early_leave_minutes'] == 0
        assert result['early_leave_violation_minutes'] == 0
        assert result['is_early_leave'] is False

    def test_hl_covers_late_window_mehdi_scenario(self):
        """ورود ۷:۲۰ + HL تأییدشده ۷:۰۰–۷:۲۰ → تأخیر صفر (حتی با grace=0)."""
        result = compute_late_early_for_day(
            resolved=self._resolved(
                late_allowed=0,
                early_allowed=0,
                start=time(7, 0),
                end=time(14, 0),
            ),
            target_date=_REF_DAY,
            first_enter=_dt(time(7, 20)),
            last_exit=_dt(time(14, 0)),
            hl_intervals=[(time(7, 0), time(7, 20))],
        )
        assert result['late_minutes'] == 0
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False

    def test_hl_partial_cover_leaves_uncovered_late(self):
        """ورود ۷:۳۰ + HL ۷:۰۰–۷:۲۰ → ۱۰ دقیقه باقیمانده؛ با grace ۱۵ → صفر."""
        result = compute_late_early_for_day(
            resolved=self._resolved(
                late_allowed=15,
                early_allowed=0,
                start=time(7, 0),
                end=time(14, 0),
            ),
            target_date=_REF_DAY,
            first_enter=_dt(time(7, 30)),
            last_exit=_dt(time(14, 0)),
            hl_intervals=[(time(7, 0), time(7, 20))],
        )
        assert result['late_minutes'] == 10
        assert result['late_violation_minutes'] == 0
        assert result['is_late'] is False

    def test_hl_covers_early_leave_window(self):
        """خروج ۱۳:۴۰ + HL ۱۳:۴۰–۱۴:۰۰ → تعجیل صفر."""
        result = compute_late_early_for_day(
            resolved=self._resolved(
                late_allowed=0,
                early_allowed=0,
                start=time(7, 0),
                end=time(14, 0),
            ),
            target_date=_REF_DAY,
            first_enter=_dt(time(7, 0)),
            last_exit=_dt(time(13, 40)),
            hl_intervals=[(time(13, 40), time(14, 0))],
        )
        assert result['early_leave_minutes'] == 0
        assert result['early_leave_violation_minutes'] == 0
        assert result['is_early_leave'] is False
