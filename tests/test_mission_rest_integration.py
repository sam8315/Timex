"""
Integration tests for Mission/Rest daily status across all consumers.

Scenario (the real bug):
  24/06/1405 (2026-09-14) → DailyStatus M, no Attendance
  25/06/1405 (2026-09-15) → DailyStatus R, no Attendance

Assert all four consumers see these days.
"""
from datetime import date, timedelta

import jdatetime
import pytest

from core.day_status_resolver import (
    build_daily_status_map, build_mission_dates, build_rest_dates,
    resolve_day_status, DayContext,
    STATUS_KEY_MISSION, STATUS_KEY_REST, STATUS_KEY_LEAVE,
)
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from models.daily_status import DailyStatus
from web.services.attendance_policy_service import resolve_required_minutes
from .conftest import login_as


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_workday(start: date) -> date:
    """Return the first non-Friday date >= start."""
    d = start
    while d.weekday() == 4:
        d += timedelta(days=1)
    return d


def _seed_mission_rest(db, user_id: str, mission_date: date, rest_date: date):
    """Insert DailyStatus M and R rows for the given user (upsert-safe)."""
    for d in (mission_date, rest_date):
        existing = db.query(DailyStatus).filter(
            DailyStatus.user_id == user_id,
            DailyStatus.status_date == d,
        ).first()
        if existing:
            db.delete(existing)
    db.flush()
    db.add(DailyStatus(user_id=user_id, status_date=mission_date, status_code='M'))
    db.add(DailyStatus(user_id=user_id, status_date=rest_date, status_code='R'))
    db.commit()


# ---------------------------------------------------------------------------
# 1. Resolver — DB round-trip
# ---------------------------------------------------------------------------

class TestResolverDBRoundTrip:
    """build_daily_status_map reads M/R from the real DB."""

    def test_mission_and_rest_from_db(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)

        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        status_map = build_daily_status_map(db, target['user_id'], mission_date, rest_date)
        assert status_map[mission_date] == 'M'
        assert status_map[rest_date] == 'R'

        missions = build_mission_dates(status_map)
        rests = build_rest_dates(status_map)
        assert mission_date in missions
        assert rest_date in rests
        assert mission_date not in rests
        assert rest_date not in missions


# ---------------------------------------------------------------------------
# 2. Resolver — duty exemption
# ---------------------------------------------------------------------------

class TestResolverDutyExemption:
    def test_mission_zero_required(self):
        result = resolve_required_minutes(
            resolved=None, target_date=date(2026, 9, 14), is_mission=True,
        )
        assert result == 0

    def test_rest_zero_required(self):
        result = resolve_required_minutes(
            resolved=None, target_date=date(2026, 9, 14), is_rest=True,
        )
        assert result == 0


# ---------------------------------------------------------------------------
# 3. Detailed Monthly V2 — M/R rows exist
# ---------------------------------------------------------------------------

class TestDetailedMonthlyV2MissionRest:
    """The V2 generator must produce rows for M/R dates even without Attendance."""

    def _generate(self, db, user_id, year, month):
        gen = DetailedMonthlyReportGeneratorV2()
        gen.db = db
        try:
            return gen.generate_detailed_report(user_id, year, month)
        finally:
            gen.close()

    def test_mission_row_exists(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=mission_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        assert report.get('success')

        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert len(day_rows) == 1
        assert day_rows[0]['person_status'] == 'M'

    def test_rest_row_exists(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        rest_date = _next_workday(today_g)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)
        mission_date = rest_date - timedelta(days=1)
        if mission_date.weekday() == 4:
            mission_date -= timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=rest_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        assert report.get('success')

        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert len(day_rows) == 1
        assert day_rows[0]['person_status'] == 'R'

    def test_mission_no_deficit(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=mission_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert day_rows[0]['deficit'] == 0.0

    def test_rest_no_deficit(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        rest_date = _next_workday(today_g)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)
        mission_date = rest_date - timedelta(days=1)
        if mission_date.weekday() == 4:
            mission_date -= timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=rest_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert day_rows[0]['deficit'] == 0.0

    def test_mission_not_absent(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=mission_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert day_rows[0]['person_status'] != 'A'


# ---------------------------------------------------------------------------
# 4. Monthly Full — M/R survives through V2
# ---------------------------------------------------------------------------

class TestMonthlyFullMissionRest:
    """Monthly Full delegates to V2, so M/R must survive."""

    def _generate(self, db, user_id, year, month):
        gen = DetailedMonthlyReportGeneratorV2()
        gen.db = db
        try:
            return gen.generate_detailed_report(user_id, year, month)
        finally:
            gen.close()

    def test_mission_survives(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=mission_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert day_rows[0]['person_status'] == 'M'

    def test_rest_survives(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        rest_date = _next_workday(today_g)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)
        mission_date = rest_date - timedelta(days=1)
        if mission_date.weekday() == 4:
            mission_date -= timedelta(days=1)

        j_date = jdatetime.date.fromgregorian(date=rest_date)
        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        report = self._generate(db, target['user_id'], j_date.year, j_date.month)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_date.strftime('%Y/%m/%d')]
        assert day_rows[0]['person_status'] == 'R'


# ---------------------------------------------------------------------------
# 5. Monthly Stats — M → م, R → اس, not absence
# ---------------------------------------------------------------------------

class TestMonthlyStatsMissionRest:
    """get_day_code must return 'م' for M and 'اس' for R."""

    def test_m_returns_me(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 14),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 14): 'M'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code == 'م'

    def test_r_returns_es(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 15),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 15): 'R'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code == 'اس'

    def test_m_not_dash(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 14),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 14): 'M'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code != '-'

    def test_r_not_dash(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 15),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 15): 'R'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code != '-'


# ---------------------------------------------------------------------------
# 6. User Attendance page — filter by mission/rest
# ---------------------------------------------------------------------------

class TestUserAttendanceFilterMissionRest:
    """User attendance page must include M/R in days_list with correct filter."""

    def test_mission_filter(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        mission_date = _next_workday(today_g)
        rest_date = mission_date + timedelta(days=1)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)
        j_date = jdatetime.date.fromgregorian(date=mission_date)

        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        from core.day_status_resolver import build_daily_status_map

        status_map = build_daily_status_map(db, target['user_id'], mission_date, rest_date)
        assert mission_date in status_map
        assert status_map[mission_date] == 'M'

    def test_rest_filter(self, db, make_user):
        target = make_user()
        today_g = jdatetime.date.today().togregorian()
        rest_date = _next_workday(today_g)
        if rest_date.weekday() == 4:
            rest_date += timedelta(days=1)
        mission_date = rest_date - timedelta(days=1)
        if mission_date.weekday() == 4:
            mission_date -= timedelta(days=1)

        _seed_mission_rest(db, target['user_id'], mission_date, rest_date)

        from core.day_status_resolver import build_daily_status_map

        status_map = build_daily_status_map(db, target['user_id'], mission_date, rest_date)
        assert rest_date in status_map
        assert status_map[rest_date] == 'R'


# ---------------------------------------------------------------------------
# 7. Combined: M + Attendance preserves attendance records
# ---------------------------------------------------------------------------

class TestCombinedMissionWithAttendance:
    """When M exists AND attendance records exist, both are preserved."""

    def test_mission_with_attendance(self):
        ctx = DayContext(
            target_date=date(2026, 9, 14),
            is_friday=False,
            is_holiday=False,
            holiday_title=None,
            is_leave=False,
            leave_type=None,
            daily_status_code='M',
            has_attendance=True,
            attendance_records=['rec1', 'rec2'],
            work_minutes=420,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION
        assert result.attendance_records == ['rec1', 'rec2']
        assert result.work_minutes == 420
        assert result.is_duty_exempt is True
        assert result.deficit_minutes == 0

    def test_rest_with_attendance(self):
        ctx = DayContext(
            target_date=date(2026, 9, 15),
            is_friday=False,
            is_holiday=False,
            holiday_title=None,
            is_leave=False,
            leave_type=None,
            daily_status_code='R',
            has_attendance=True,
            attendance_records=['rec3'],
            work_minutes=300,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_REST
        assert result.attendance_records == ['rec3']
        assert result.work_minutes == 300
        assert result.is_duty_exempt is True
        assert result.deficit_minutes == 0


# ---------------------------------------------------------------------------
# 8. Priority: Leave > Mission > Rest
# ---------------------------------------------------------------------------

class TestPriorityChain:
    def test_leave_over_mission(self):
        ctx = DayContext(
            target_date=date(2026, 9, 14),
            is_friday=False, is_holiday=False, holiday_title=None,
            is_leave=True, leave_type='AL',
            daily_status_code='M',
            has_attendance=False, attendance_records=[], work_minutes=0,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_LEAVE

    def test_mission_over_attendance(self):
        ctx = DayContext(
            target_date=date(2026, 9, 14),
            is_friday=False, is_holiday=False, holiday_title=None,
            is_leave=False, leave_type=None,
            daily_status_code='M',
            has_attendance=True, attendance_records=['r'], work_minutes=420,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION


# ---------------------------------------------------------------------------
# 9. Real bug regression: 24/06/1405 M, 25/06/1405 R
# ---------------------------------------------------------------------------

class TestRealBugRegression:
    """
    Regression for the reported bug:
      24/06/1405 (2026-09-14) → M
      25/06/1405 (2026-09-15) → R
    Both must be visible in all consumers.
    """

    def test_m_date_visible_in_status_map(self, db, make_user):
        target = make_user()
        mission_g = date(2026, 9, 14)
        rest_g = date(2026, 9, 15)
        _seed_mission_rest(db, target['user_id'], mission_g, rest_g)

        status_map = build_daily_status_map(db, target['user_id'], mission_g, rest_g)
        assert status_map.get(mission_g) == 'M'
        assert status_map.get(rest_g) == 'R'

    def test_m_date_not_absent_in_resolver(self):
        ctx = DayContext(
            target_date=date(2026, 9, 14),
            is_friday=False, is_holiday=False, holiday_title=None,
            is_leave=False, leave_type=None,
            daily_status_code='M',
            has_attendance=False, attendance_records=[], work_minutes=0,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_MISSION
        assert result.status_code != 'absent'

    def test_r_date_not_absent_in_resolver(self):
        ctx = DayContext(
            target_date=date(2026, 9, 15),
            is_friday=False, is_holiday=False, holiday_title=None,
            is_leave=False, leave_type=None,
            daily_status_code='R',
            has_attendance=False, attendance_records=[], work_minutes=0,
        )
        result = resolve_day_status(ctx)
        assert result.status_code == STATUS_KEY_REST
        assert result.status_code != 'absent'

    def test_v2_shows_mission(self, db, make_user):
        target = make_user()
        mission_g = date(2026, 9, 14)
        rest_g = date(2026, 9, 15)
        _seed_mission_rest(db, target['user_id'], mission_g, rest_g)

        j_date = jdatetime.date.fromgregorian(date=mission_g)
        gen = DetailedMonthlyReportGeneratorV2()
        gen.db = db
        try:
            report = gen.generate_detailed_report(target['user_id'], j_date.year, j_date.month)
        finally:
            gen.close()

        j_target = jdatetime.date.fromgregorian(date=mission_g)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_target.strftime('%Y/%m/%d')]
        assert len(day_rows) == 1
        assert day_rows[0]['person_status'] == 'M'

    def test_v2_shows_rest(self, db, make_user):
        target = make_user()
        mission_g = date(2026, 9, 14)
        rest_g = date(2026, 9, 15)
        _seed_mission_rest(db, target['user_id'], mission_g, rest_g)

        j_date = jdatetime.date.fromgregorian(date=rest_g)
        gen = DetailedMonthlyReportGeneratorV2()
        gen.db = db
        try:
            report = gen.generate_detailed_report(target['user_id'], j_date.year, j_date.month)
        finally:
            gen.close()

        j_target = jdatetime.date.fromgregorian(date=rest_g)
        day_rows = [d for d in report['days']
                     if d['jalali_date'] == j_target.strftime('%Y/%m/%d')]
        assert len(day_rows) == 1
        assert day_rows[0]['person_status'] == 'R'

    def test_stats_m_code(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 14),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 14): 'M'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code == 'م'

    def test_stats_r_code(self):
        from web.routes.reports import get_day_code
        code = get_day_code(
            day_date=date(2026, 9, 15),
            leaves_by_date={},
            daily_status_map={date(2026, 9, 15): 'R'},
            holiday_dates=set(),
            has_attendance=False,
            is_friday=False,
        )
        assert code == 'اس'
