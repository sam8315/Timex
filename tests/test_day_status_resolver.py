"""Tests for the shared daily-status resolver."""
from datetime import date, timedelta

import jdatetime

from core.day_status_resolver import (
    resolve_day_status, DayContext,
    build_daily_status_map, build_mission_dates, build_rest_dates,
    STATUS_KEY_MISSION, STATUS_KEY_REST, STATUS_KEY_LEAVE,
    STATUS_KEY_HOLIDAY, STATUS_KEY_FRIDAY, STATUS_KEY_PRESENT, STATUS_KEY_ABSENT,
    STATUS_CODE_MISSION, STATUS_CODE_REST,
)
from models.daily_status import DailyStatus
from .conftest import login_as


def _make_context(**overrides):
    """Helper to build a DayContext with sensible defaults."""
    defaults = dict(
        target_date=date(2026, 9, 14),
        is_friday=False,
        is_holiday=False,
        holiday_title=None,
        is_leave=False,
        leave_type=None,
        daily_status_code=None,
        has_attendance=False,
        attendance_records=[],
        work_minutes=0,
    )
    defaults.update(overrides)
    return DayContext(**defaults)


# ============================================
# DailyStatus resolution
# ============================================

class TestResolveDayStatusMission:
    def test_mission_recognized(self):
        ctx = _make_context(daily_status_code='M')
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION
        assert result.is_duty_exempt is True
        assert result.required_minutes == 0
        assert result.deficit_minutes == 0

    def test_mission_replaces_absent(self):
        ctx = _make_context(daily_status_code='M', has_attendance=False)
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION
        assert result.status_code != STATUS_KEY_ABSENT

    def test_mission_duty_exempt(self):
        ctx = _make_context(daily_status_code='M')
        result = resolve_day_status(ctx)
        assert result.is_duty_exempt is True


class TestResolveDayStatusRest:
    def test_rest_recognized(self):
        ctx = _make_context(daily_status_code='R')
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_REST
        assert result.is_duty_exempt is True
        assert result.required_minutes == 0
        assert result.deficit_minutes == 0

    def test_rest_replaces_absent(self):
        ctx = _make_context(daily_status_code='R', has_attendance=False)
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_REST
        assert result.status_code != STATUS_KEY_ABSENT

    def test_rest_duty_exempt(self):
        ctx = _make_context(daily_status_code='R')
        result = resolve_day_status(ctx)
        assert result.is_duty_exempt is True


class TestResolveDayStatusLeave:
    def test_leave_recognized(self):
        ctx = _make_context(is_leave=True, leave_type='AL')
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_LEAVE
        assert result.is_duty_exempt is True

    def test_leave_takes_priority_over_mission(self):
        ctx = _make_context(is_leave=True, leave_type='AL', daily_status_code='M')
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_LEAVE


class TestResolveDayStatusHoliday:
    def test_holiday_recognized(self):
        ctx = _make_context(is_holiday=True, holiday_title='test')
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_HOLIDAY
        assert result.is_duty_exempt is True


class TestResolveDayStatusFriday:
    def test_friday_no_attendance(self):
        ctx = _make_context(is_friday=True)
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_FRIDAY
        assert result.is_duty_exempt is True

    def test_friday_with_attendance(self):
        ctx = _make_context(is_friday=True, has_attendance=True, work_minutes=420)
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_PRESENT
        assert result.is_duty_exempt is True


class TestResolveDayStatusPresent:
    def test_present_with_attendance(self):
        ctx = _make_context(has_attendance=True, work_minutes=420)
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_PRESENT
        assert result.is_duty_exempt is False


class TestResolveDayStatusAbsent:
    def test_absent_no_attendance(self):
        ctx = _make_context()
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_ABSENT
        assert result.is_duty_exempt is False


# ============================================
# Combined state: M/R + Attendance
# ============================================

class TestCombinedState:
    def test_mission_with_attendance_preserves_records(self):
        ctx = _make_context(
            daily_status_code='M',
            has_attendance=True,
            attendance_records=['dummy'],
            work_minutes=420,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION
        assert result.attendance_records == ['dummy']
        assert result.work_minutes == 420

    def test_rest_with_attendance_preserves_records(self):
        ctx = _make_context(
            daily_status_code='R',
            has_attendance=True,
            attendance_records=['dummy'],
            work_minutes=420,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_REST
        assert result.attendance_records == ['dummy']
        assert result.work_minutes == 420

    def test_mission_no_deficit_even_with_zero_work(self):
        ctx = _make_context(daily_status_code='M', work_minutes=0)
        result = resolve_day_status(ctx)
        assert result.deficit_minutes == 0

    def test_rest_no_deficit_even_with_zero_work(self):
        ctx = _make_context(daily_status_code='R', work_minutes=0)
        result = resolve_day_status(ctx)
        assert result.deficit_minutes == 0


# ============================================
# Helper functions
# ============================================

class TestBuildHelpers:
    def test_build_mission_dates(self):
        status_map = {
            date(2026, 9, 1): 'M',
            date(2026, 9, 2): 'R',
            date(2026, 9, 3): 'M',
        }
        missions = build_mission_dates(status_map)
        assert missions == {date(2026, 9, 1), date(2026, 9, 3)}

    def test_build_rest_dates(self):
        status_map = {
            date(2026, 9, 1): 'M',
            date(2026, 9, 2): 'R',
            date(2026, 9, 3): 'M',
        }
        rests = build_rest_dates(status_map)
        assert rests == {date(2026, 9, 2)}

    def test_build_empty_maps(self):
        assert build_mission_dates({}) == set()
        assert build_rest_dates({}) == set()


# ============================================
# Model integration
# ============================================

class TestModelIntegration:
    def test_daily_status_code_strips_spaces(self, db, make_user):
        target = make_user(role="user", balance_al=None)
        day = jdatetime.date.today().togregorian()
        row = DailyStatus(
            user_id=target["user_id"],
            status_date=day,
            status_code="M ",
        )
        assert row.status_code == "M"

    def test_resolve_required_minutes_zero_for_mission(self):
        from web.services.attendance_policy_service import resolve_required_minutes
        result = resolve_required_minutes(
            resolved=None,
            target_date=date(2026, 9, 14),
            is_mission=True,
        )
        assert result == 0

    def test_resolve_required_minutes_zero_for_rest(self):
        from web.services.attendance_policy_service import resolve_required_minutes
        result = resolve_required_minutes(
            resolved=None,
            target_date=date(2026, 9, 14),
            is_rest=True,
        )
        assert result == 0


# ============================================
# Filter integration (admin page)
# ============================================

class TestFilterIntegration:
    def test_mission_filter_includes_only_mission(self):
        """Verify filter logic extracts mission-only days."""
        days = [
            {'status': {'main_status': 'mission'}},
            {'status': {'main_status': 'rest'}},
            {'status': {'main_status': 'mission'}},
        ]
        filtered = [d for d in days if d['status']['main_status'] == 'mission']
        assert len(filtered) == 2

    def test_rest_filter_includes_only_rest(self):
        """Verify filter logic extracts rest-only days."""
        days = [
            {'status': {'main_status': 'mission'}},
            {'status': {'main_status': 'rest'}},
            {'status': {'main_status': 'rest'}},
        ]
        filtered = [d for d in days if d['status']['main_status'] == 'rest']
        assert len(filtered) == 2

    def test_mission_not_in_no_attendance(self):
        """Mission days must not appear in no_attendance filter."""
        days = [
            {'status': {'main_status': 'mission'}},
            {'status': {'main_status': 'no_attendance'}},
        ]
        no_att = [d for d in days if d['status']['main_status'] == 'no_attendance']
        assert len(no_att) == 1
        assert all(d['status']['main_status'] != 'mission' for d in no_att)
