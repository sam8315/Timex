"""
Phase 5 — Regression برای اتصال `/reports/monthly-full` به Central Engine.

مرجع «Before» = منطق پیش از migration در
`core/detailed_monthly_report_v2.py::_calculate_day_work_hours_v2`
که به صورت frozen در `_old_day_calc` (زیر) کپی شده است.

نکات کلیدی:
- Actual Attendance فقط از `core.attendance_calculator.compute_day_attendance` می‌آید.
- Policy / Required / Surplus / Deficit / Summary در لایه Report می‌ماند.
- ظاهر (template) تغییر نمی‌کند: labelهای فعلی monthly-full حفظ می‌شوند.
- فقط روزهای داخل ماه در report/summary لحاظ می‌شوند؛ روزهای مرز فقط context موتورند.
"""
import json
import os
from datetime import date, datetime, timedelta

import jdatetime
import pytest

from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from tests.conftest import TestingSessionLocal
from tests.test_attendance_route_regression import (
    G_END,
    G_START,
    HOLIDAY_DATE,
    HOLIDAY_TITLE,
    J_MONTH,
    J_YEAR,
    LEAVE_DATES,
    MISSION_DATE,
    REST_DATE,
    _cleanup_holiday,
    _seed_day_statuses,
    _seed_holiday,
    _seed_leaves,
    _seed_punches,
)

# ---------------------------------------------------------------------------
# Fixture: generator متصل به test DB
# ---------------------------------------------------------------------------
@pytest.fixture()
def gen(monkeypatch):
    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
    generator = DetailedMonthlyReportGeneratorV2()
    try:
        yield generator
    finally:
        generator.close()


def _make_report(gen, user_id, year=J_YEAR, month=J_MONTH):
    report = gen.generate_detailed_report(user_id, year, month)
    assert report.get('success'), report.get('message')
    return report


def _day(report, g_date):
    for d in report['days']:
        if d['date'] == g_date:
            return d
    raise AssertionError(f'day {g_date} not in report')


def _naive(value):
    """جدول‌ها tz-aware برمی‌گردند؛ برای مقایسه فقط زمان دیواری."""
    return value.replace(tzinfo=None) if getattr(value, 'tzinfo', None) else value


# ---------------------------------------------------------------------------
# frozen: منطق قبل از migration (_calculate_day_work_hours_v2 عیناً)
# ---------------------------------------------------------------------------
MAX_PAIRS = 3


def _old_day_calc(current, day_attendances, all_attendances):
    """کپی frozen موتور Actual قبل از Phase 5 (بدون تغییر منطق)."""
    if not day_attendances:
        return {
            'work_hours': 0.0,
            'pairs': [],
            'attendance_status': 'بدون تردد',
            'has_incomplete': False,
        }

    enters = sorted([a for a in day_attendances if a.punch == 0],
                    key=lambda x: x.timestamp)
    exits = sorted([a for a in day_attendances if a.punch == 1],
                   key=lambda x: x.timestamp)

    def make_aware_datetime(d, hour, minute, second, microsecond, ref_timestamp):
        naive_dt = datetime.combine(
            d, datetime.min.time().replace(
                hour=hour, minute=minute, second=second, microsecond=microsecond))
        if ref_timestamp.tzinfo is not None:
            return naive_dt.replace(tzinfo=ref_timestamp.tzinfo)
        return naive_dt

    if enters and exits:
        first_enter = min(e.timestamp for e in enters)
        last_exit = max(e.timestamp for e in exits)

        if last_exit.date() > current:
            end_of_day = make_aware_datetime(current, 23, 59, 59, 999999, first_enter)
            pairs = []
            for i, enter in enumerate(enters):
                if i < len(exits):
                    exit_time = exits[i].timestamp
                    if exit_time.date() > current:
                        exit_time = end_of_day
                    if exit_time > enter.timestamp:
                        pairs.append({
                            'enter': enter.timestamp,
                            'exit': exit_time,
                            'hours': round((exit_time - enter.timestamp).total_seconds() / 3600, 2),
                        })
            work_hours = sum(p['hours'] for p in pairs)
            return {
                'work_hours': round(work_hours, 2),
                'pairs': pairs[:MAX_PAIRS],
                'attendance_status': f'کامل (خروج فردا)',
                'has_incomplete': False,
            }

        if last_exit > first_enter:
            pairs = []
            for i, enter in enumerate(enters):
                if i < len(exits):
                    exit_time = exits[i].timestamp
                    if exit_time > enter.timestamp:
                        pairs.append({
                            'enter': enter.timestamp,
                            'exit': exit_time,
                            'hours': round((exit_time - enter.timestamp).total_seconds() / 3600, 2),
                        })
            work_hours = sum(p['hours'] for p in pairs)
            if len(enters) == len(exits):
                attendance_status = ('کامل' if len(enters) == 1
                                     else f'کامل{len(enters)}')
            else:
                attendance_status = f'ناقص ({len(enters)}و/{len(exits)}خ)'
            return {
                'work_hours': round(work_hours, 2),
                'pairs': pairs[:MAX_PAIRS],
                'attendance_status': attendance_status,
                'has_incomplete': len(enters) != len(exits),
            }

    if enters and not exits:
        first_enter = min(e.timestamp for e in enters)
        next_day = current + timedelta(days=1)
        next_day_attendances = [a for a in all_attendances
                                if a.timestamp.date() == next_day]
        next_day_exits = [a for a in next_day_attendances if a.punch == 1]
        if next_day_exits:
            end_of_day = make_aware_datetime(current, 23, 59, 59, 999999, first_enter)
            work_hours = (end_of_day - first_enter).total_seconds() / 3600
            pairs = [{'enter': first_enter, 'exit': end_of_day,
                      'hours': round(work_hours, 2)}]
            return {
                'work_hours': round(work_hours, 2),
                'pairs': pairs,
                'attendance_status': 'کامل (خروج فردا)',
                'has_incomplete': False,
            }
        return {
            'work_hours': 0.0,
            'pairs': [],
            'attendance_status': f'ورود بدون خروج ({len(enters)} ورود)',
            'has_incomplete': True,
        }

    if exits and not enters:
        last_exit = max(e.timestamp for e in exits)
        prev_day = current - timedelta(days=1)
        prev_day_attendances = [a for a in all_attendances
                                if a.timestamp.date() == prev_day]
        prev_day_enters = [a for a in prev_day_attendances if a.punch == 0]
        if prev_day_enters:
            start_of_day = make_aware_datetime(current, 0, 0, 0, 0, last_exit)
            work_hours = (last_exit - start_of_day).total_seconds() / 3600
            pairs = [{'enter': start_of_day, 'exit': last_exit,
                      'hours': round(work_hours, 2)}]
            return {
                'work_hours': round(work_hours, 2),
                'pairs': pairs,
                'attendance_status': 'کامل (ورود دیروز)',
                'has_incomplete': False,
            }
        return {
            'work_hours': 0.0,
            'pairs': [],
            'attendance_status': f'خروج بدون ورود ({len(exits)} خروج)',
            'has_incomplete': True,
        }

    return {
        'work_hours': 0.0,
        'pairs': [],
        'attendance_status': 'بدون تردد',
        'has_incomplete': False,
    }


def _old_report_days(in_month_records):
    """روزهای قبل از migration: فقط رکوردهای داخل ماه (بدون حاشیه مرزی)."""
    by_day = {}
    for r in in_month_records:
        by_day.setdefault(r.timestamp.date(), []).append(r)
    out = {}
    current = G_START
    while current <= G_END:
        out[current] = _old_day_calc(current, by_day.get(current, []),
                                     in_month_records)
        current += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# تفاوت‌های مستندشده (قانون ۱۲: هر اختلاف دقیقاً دسته‌بندی می‌شود)
#   A) رفتار اصلاح‌شده به دلیل Central Engine
#   B) تغییر ناخواسته / regression
#   C) اختلاف صرفاً در rounding/display
#   D) اختلاف Policy
#   E) اختلاف context مرزی ماه
# ---------------------------------------------------------------------------
EXPECTED_DIFFS = {
    date(2024, 3, 20): 'E',   # خروج در روز اول ماه ← ورود ماه قبل دیده نمی‌شد
    date(2024, 3, 26): 'A',   # قدیم: هر ورودِ دیروز = شب؛ Central: آخرین punch دیروز خروج است
    date(2024, 3, 30): 'C',   # rounding جفت تکراری (0.01 قدیم ← 30s خام)
    date(2024, 4, 2): 'C',    # خروج ضمنی 23:59:59 (مرکزی) در مقابل 23:59:59.999999
    date(2024, 4, 7): 'A',    # قدیم: خروج صبح + ورود شب ← 'بدون تردد'؛ مرکزی: شیفت شب
    date(2024, 4, 19): 'E',   # ورود آخرین روز ← خروج ماه بعد دیده نمی‌شد
}

EXPECTED_TOTAL_DELTA = -1.0025  # مجموع کارکرد بعد − قبل (از همان ۶ تفاوت بالا)


def _diff_days(old_days, report):
    diffs = {}
    for g_date, old in old_days.items():
        new = _day(report, g_date)
        old_pairs = [(p['enter'], p['exit']) for p in old['pairs']]
        new_pairs = [(p['enter'], p['exit']) for p in new['attendance_pairs']]
        if (abs(old['work_hours'] - new['work_hours']) > 1e-9
                or old['attendance_status'] != new['attendance_status']
                or old['has_incomplete'] != new['has_incomplete']
                or old_pairs != new_pairs):
            diffs[g_date] = (old, new)
    return diffs


def _seed_report_month(db, user_id):
    from models.holiday import Holiday
    # holidayهای باقی‌مانده از تست‌های دیگر نباید روی این ماه اثر بگذارند
    db.query(Holiday).filter(
        Holiday.holiday_date >= G_START,
        Holiday.holiday_date <= G_END,
    ).delete()
    db.commit()
    _seed_punches(db, user_id)
    _seed_holiday(db)
    _seed_day_statuses(db, user_id)
    _seed_leaves(db, user_id)


def _in_month_records(db, user_id):
    from models.attendance import Attendance
    return db.query(Attendance).filter(
        Attendance.user_id == user_id,
        Attendance.timestamp >= G_START,
        Attendance.timestamp < G_END + timedelta(days=1),
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()


# ---------------------------------------------------------------------------
# ۱) قبل / بعد: فقط تفاوت‌های مستندشده مجازند
# ---------------------------------------------------------------------------
class TestBeforeAfter:
    def test_diffs_are_exactly_the_documented_ones(self, db, make_user, gen):
        creds = make_user(role='user', balance_al=30, department='4')
        _seed_report_month(db, creds['user_id'])
        try:
            report = _make_report(gen, creds['user_id'])
            old_days = _old_report_days(_in_month_records(db, creds['user_id']))
            diffs = _diff_days(old_days, report)

            assert set(diffs) == set(EXPECTED_DIFFS), {
                d.isoformat(): {
                    'old': {'work': v[0]['work_hours'],
                            'status': v[0]['attendance_status'],
                            'incomplete': v[0]['has_incomplete'],
                            'pairs': [(p['enter'], p['exit'])
                                      for p in v[0]['pairs']]},
                    'new': {'work': v[1]['work_hours'],
                            'status': v[1]['attendance_status'],
                            'incomplete': v[1]['has_incomplete'],
                            'pairs': [(p['enter'], p['exit'])
                                      for p in v[1]['attendance_pairs']]},
                } for d, v in diffs.items()
            }

            # دسته‌بندی E: مرز ماه — night shift حالا دیده می‌شود
            d = _day(report, date(2024, 3, 20))
            assert d['work_hours'] == pytest.approx(6.0)
            assert d['attendance_status'] == 'کامل (ورود دیروز)'
            assert d['has_incomplete'] is False
            assert _naive(d['attendance_pairs'][0]['enter']) == datetime(2024, 3, 20, 0, 0)
            assert _naive(d['attendance_pairs'][0]['exit']) == datetime(2024, 3, 20, 6, 0)

            d = _day(report, date(2024, 4, 19))
            assert d['work_hours'] == pytest.approx(7199 / 3600)
            assert d['attendance_status'] == 'کامل (خروج فردا)'
            assert d['has_incomplete'] is False

            # دسته‌بندی A: تشخیص شب فقط با آخرین punch روز قبل
            d = _day(report, date(2024, 3, 26))
            assert d['work_hours'] == 0.0
            assert d['attendance_status'] == 'خروج بدون ورود (1 خروج)'
            assert d['has_incomplete'] is True
            assert d['attendance_pairs'] == []

            d = _day(report, date(2024, 4, 7))
            assert d['work_hours'] == pytest.approx((6 * 3600 + 7199) / 3600)
            assert d['attendance_status'] == 'کامل'
            assert len(d['attendance_pairs']) == 2

            # دسته‌بندی C: فقط rounding
            d = _day(report, date(2024, 3, 30))
            assert d['work_hours'] == pytest.approx(30 / 3600)
            d = _day(report, date(2024, 4, 2))
            assert d['work_hours'] == pytest.approx(7199 / 3600)

            # مجموع کارکرد ماه = قبل + delta مستندشده
            from core.detailed_monthly_report_v2 import (
                _hours_to_minutes, _minutes_to_hours,
            )
            old_total = sum(v['work_hours'] for v in old_days.values())
            new_total = sum(d['work_hours'] for d in report['days'])
            assert new_total - old_total == pytest.approx(EXPECTED_TOTAL_DELTA, abs=1e-6)
            assert report['summary']['total_work_hours'] == pytest.approx(
                _minutes_to_hours(_hours_to_minutes(new_total)))
        finally:
            _cleanup_holiday(db)

    def test_month_contains_only_month_days(self, db, make_user, gen):
        """روزهای مرز فقط context موتورند — در report/summary نیستند."""
        creds = make_user(role='user', balance_al=30, department='4')
        _seed_report_month(db, creds['user_id'])
        try:
            report = _make_report(gen, creds['user_id'])
            dates = [d['date'] for d in report['days']]
            assert dates[0] == G_START and dates[-1] == G_END
            assert len(dates) == 31
            assert G_START - timedelta(days=1) not in dates
            assert G_END + timedelta(days=1) not in dates
        finally:
            _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۲) ماتریس سناریوها (مرحله ۱۴) + حفظ labelهای فعلی
# ---------------------------------------------------------------------------
EXPECTED_STATUS = {
    date(2024, 3, 20): 'کامل (ورود دیروز)',
    date(2024, 3, 21): 'کامل',
    date(2024, 3, 22): 'کامل',
    date(2024, 3, 23): 'کامل',
    date(2024, 3, 24): 'کامل2',
    date(2024, 3, 25): 'کامل',
    date(2024, 3, 26): 'خروج بدون ورود (1 خروج)',
    date(2024, 3, 27): 'ورود بدون خروج (1 ورود)',
    date(2024, 3, 28): 'ورود بدون خروج (2 ورود)',
    date(2024, 3, 29): 'بدون تردد',
    date(2024, 3, 30): 'کامل',
    date(2024, 3, 31): 'کامل',
    date(2024, 4, 1): 'ناقص (4و/3خ)',
    date(2024, 4, 2): 'کامل (خروج فردا)',
    date(2024, 4, 3): 'کامل (ورود دیروز)',
    date(2024, 4, 4): 'کامل',
    date(2024, 4, 5): 'کامل',
    date(2024, 4, 6): 'کامل',
    date(2024, 4, 7): 'کامل',
    date(2024, 4, 8): 'کامل',
    date(2024, 4, 19): 'کامل (خروج فردا)',
}

EXPECTED_WORK_HOURS = {
    date(2024, 3, 20): 6.0,
    date(2024, 3, 21): 9.0,
    date(2024, 3, 24): 8.0,
    date(2024, 3, 25): 9.0,
    date(2024, 3, 26): 0.0,
    date(2024, 3, 27): 0.0,
    date(2024, 3, 30): 30 / 3600,
    date(2024, 3, 31): 13.0,
    date(2024, 4, 1): 3.0,
    date(2024, 4, 2): 7199 / 3600,
    date(2024, 4, 3): 6.0,
    date(2024, 4, 6): 9.0,
    date(2024, 4, 7): (6 * 3600 + 7199) / 3600,
    date(2024, 4, 8): 0.5,
    date(2024, 4, 19): 7199 / 3600,
}

EXPECTED_INCOMPLETE = {
    date(2024, 3, 26): True,
    date(2024, 3, 27): True,
    date(2024, 3, 28): True,
    date(2024, 4, 1): True,
}


class TestScenarioMatrix:
    def test_status_work_hours_and_pairs(self, db, make_user, gen):
        creds = make_user(role='user', balance_al=30, department='4')
        _seed_report_month(db, creds['user_id'])
        try:
            report = _make_report(gen, creds['user_id'])

            for g_date, expected in EXPECTED_STATUS.items():
                d = _day(report, g_date)
                assert d['attendance_status'] == expected, g_date

            for g_date, expected in EXPECTED_WORK_HOURS.items():
                d = _day(report, g_date)
                assert d['work_hours'] == pytest.approx(expected), g_date

            for g_date, expected in EXPECTED_INCOMPLETE.items():
                assert _day(report, g_date)['has_incomplete'] is expected, g_date

            # مرز ماه: خروج/ورودِ ماه قبل و بعد دیده می‌شود
            d = _day(report, date(2024, 3, 20))
            assert len(d['attendance_pairs']) == 1
            assert _naive(d['attendance_pairs'][0]['enter']) == datetime(2024, 3, 20, 0, 0)
            assert _naive(d['attendance_pairs'][0]['exit']) == datetime(2024, 3, 20, 6, 0)
            assert d['attendance_pairs'][0]['hours'] == pytest.approx(6.0)
            d = _day(report, date(2024, 4, 3))
            assert _naive(d['attendance_pairs'][0]['enter']) == datetime(2024, 4, 3, 0, 0)
            assert _naive(d['attendance_pairs'][0]['exit']) == datetime(2024, 4, 3, 6, 0)

            # روزهای بدون تردد: بدون badge (رفتار قبلی template)
            d = _day(report, date(2024, 4, 10))
            assert d['attendance_status'] == 'بدون تردد'
            assert d['attendance_pairs'] == []
            assert d['has_incomplete'] is False
            assert d['work_hours'] == 0.0
        finally:
            _cleanup_holiday(db)

    def test_policy_layer_untouched(self, db, make_user, gen):
        """Friday/holiday/leave/mission/rest و موظفی Policy دست‌نخورده."""
        creds = make_user(role='user', balance_al=30, department='4')
        _seed_report_month(db, creds['user_id'])
        try:
            report = _make_report(gen, creds['user_id'])

            # person_status (Policy/report layer)
            assert _day(report, date(2024, 3, 22))['person_status'] == 'P'  # جمعه کاری
            assert _day(report, date(2024, 3, 22))['is_friday'] is True
            assert _day(report, date(2024, 3, 23))['person_status'] == 'P'  # تعطیل کاری
            assert _day(report, date(2024, 3, 23))['is_holiday'] is True
            assert _day(report, date(2024, 4, 6))['person_status'] == 'L'
            assert _day(report, date(2024, 4, 7))['person_status'] == 'L'
            assert _day(report, date(2024, 4, 4))['person_status'] == 'M'
            assert _day(report, date(2024, 4, 5))['person_status'] == 'R'
            # مرخصی/مأموریت/استراحت ← موظفی روز صفر
            assert _day(report, date(2024, 4, 6))['daily_duty'] == 0
            assert _day(report, date(2024, 4, 4))['daily_duty'] == 0
            assert _day(report, date(2024, 4, 5))['daily_duty'] == 0

            # summary از همان توابع report layer می‌آید
            s = report['summary']
            assert s['friday_work_days'] == 2   # 03-22 و 04-19
            assert s['holiday_work_days'] == 1  # 03-23
            assert s['leave_days'] == 2
            assert s['mission_days'] == 1
            assert s['rest_days'] == 1
            # internal consistency (جمع‌ها با دقت دقیقه هم‌تراز با لایه گزارش)
            from core.detailed_monthly_report_v2 import (
                _hours_to_minutes, _minutes_to_hours,
            )

            def _sum_hhmm(key):
                return _minutes_to_hours(
                    _hours_to_minutes(sum(float(d[key] or 0) for d in report['days']))
                )

            assert s['total_work_hours'] == pytest.approx(
                _sum_hhmm('work_hours'))
            assert s['total_surplus'] == pytest.approx(_minutes_to_hours(
                sum(_hours_to_minutes(d['surplus']) for d in report['days'])))
            assert s['total_deficit'] == pytest.approx(_minutes_to_hours(
                sum(_hours_to_minutes(d['deficit']) for d in report['days'])))
            expected_ot_m = 0
            for wk in {_week_start(d['date']) for d in report['days']}:
                week_days = [d for d in report['days']
                             if _week_start(d['date']) == wk]
                work_m = sum(_hours_to_minutes(d['work_hours']) for d in week_days)
                req_m = sum(_hours_to_minutes(d['daily_duty']) for d in week_days)
                if req_m > 0 and work_m > req_m:
                    expected_ot_m += work_m - req_m
            assert s['weekly_overtime'] == pytest.approx(
                _minutes_to_hours(expected_ot_m))
        finally:
            _cleanup_holiday(db)


def _week_start(d):
    current = d
    while current.weekday() != 5:
        current -= timedelta(days=1)
    return current


# ---------------------------------------------------------------------------
# ۳) Source of Truth (مرحله ۱۶)
# ---------------------------------------------------------------------------
class TestSourceOfTruth:
    def test_duplicate_engine_removed(self):
        import core.detailed_monthly_report_v2 as mod
        assert not hasattr(DetailedMonthlyReportGeneratorV2,
                           '_calculate_day_work_hours_v2')
        assert not hasattr(mod, '_calculate_day_work_hours_v2')
        assert mod.compute_day_attendance is not None
        from core import attendance_calculator
        assert mod.compute_day_attendance is attendance_calculator.compute_day_attendance

        # هیچ جفت‌سازی/شب/ساعت‌سازی مستقلی در فایل گزارش نمانده است
        source = open(mod.__file__, encoding='utf-8').read()
        for forbidden in ('_calculate_day_work_hours_v2',
                          'first_exit.timestamp <',
                          'has_night_shift',
                          'end_of_day = make_aware'):
            assert forbidden not in source, forbidden

    def test_central_engine_called_for_every_day(self, db, make_user, gen,
                                                 monkeypatch):
        import core.detailed_monthly_report_v2 as mod
        calls = []
        real = mod.compute_day_attendance

        def spy(**kwargs):
            calls.append(kwargs['day'])
            return real(**kwargs)

        monkeypatch.setattr(mod, 'compute_day_attendance', spy)
        creds = make_user(role='user', balance_al=30, department='4')
        _seed_report_month(db, creds['user_id'])
        try:
            _make_report(gen, creds['user_id'])
            in_month = {d for d in calls if G_START <= d <= G_END}
            assert in_month == {G_START + timedelta(days=i) for i in range(31)}
        finally:
            _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۴) نمایش ۳ جفت (مرحله ۶/۷): کلاس در لایه report می‌ماند، کارکرد کامل است
# ---------------------------------------------------------------------------
def test_more_than_three_pairs_capped_for_display(db, make_user, gen):
    from datetime import datetime as dt
    from models.attendance import Attendance

    creds = make_user(role='user', balance_al=30, department='4')
    uid = creds['user_id']
    d = date(2024, 4, 10)
    for enter, exit_ in ((8, 10), (11, 13), (14, 16), (17, 19)):
        db.add(Attendance(user_id=uid, timestamp=dt(d.year, d.month, d.day, enter, 0),
                          punch=0, status=15, source='L'))
        db.add(Attendance(user_id=uid, timestamp=dt(d.year, d.month, d.day, exit_, 0),
                          punch=1, status=15, source='L'))
    db.commit()

    report = _make_report(gen, uid)
    day = _day(report, d)
    # نمایش: حداکثر ۳ جفت (تعداد ستون‌های UI تغییر نمی‌کند)
    assert len(day['attendance_pairs']) == 3
    # کارکرد: از همه pairهای مرکزی، نه فقط ۳ جفت نمایشی
    assert day['work_hours'] == pytest.approx(8.0)
    assert day['attendance_status'] == 'کامل4'


# ---------------------------------------------------------------------------
# ۵) گروه/برنامه کاری (مرحله ۹/۱۵): Actual از Central، Required از Policy
# ---------------------------------------------------------------------------
def _seed_user_policy(db, user_id, department, start_t, end_t):
    from models.attendance import AttendancePolicy, AttendancePolicyDay

    db.query(AttendancePolicy).filter(
        AttendancePolicy.user_id == user_id).delete()
    db.commit()
    policy = AttendancePolicy(
        employment_type_code=department,
        user_id=user_id,
        effective_from_date=date(2024, 3, 1),
        effective_to_date=date(2024, 4, 30),
        late_enabled=True, late_allowed_minutes=0,
        late_reference_mode='FIXED_TIME',
        early_leave_enabled=True, early_leave_allowed_minutes=0,
        early_leave_reference_mode='FIXED_TIME',
        is_active=True,
    )
    db.add(policy)
    db.flush()
    for wd in range(7):
        db.add(AttendancePolicyDay(
            policy_id=policy.id, weekday=wd,
            is_working_day=True, start_time=start_t, end_time=end_t,
        ))
    db.commit()


def test_groups_required_from_policy_actual_from_central(db, make_user, gen):
    from datetime import time
    from datetime import datetime as dt
    from models.attendance import Attendance
    from web.services.attendance_policy_service import (
        compute_required_minutes_for_range,
    )
    from models.employee import Employee

    a = make_user(role='employee', balance_al=None, department='1')
    b = make_user(role='employee', balance_al=None, department='4')

    from models.holiday import Holiday
    db.query(Holiday).filter(
        Holiday.holiday_date >= G_START,
        Holiday.holiday_date <= G_END,
    ).delete()
    db.commit()

    _seed_user_policy(db, a['user_id'], '1', time(7, 0), time(13, 0))   # 360/روز
    _seed_user_policy(db, b['user_id'], '4', time(9, 0), time(17, 0))   # 480/روز

    workdays = [date(2024, 3, 25), date(2024, 3, 26),
                date(2024, 3, 27), date(2024, 3, 28)]
    for uid in (a['user_id'], b['user_id']):
        for d in workdays:
            db.add(Attendance(user_id=uid,
                              timestamp=dt(d.year, d.month, d.day, 8, 0),
                              punch=0, status=15, source='L'))
            db.add(Attendance(user_id=uid,
                              timestamp=dt(d.year, d.month, d.day, 17, 0),
                              punch=1, status=15, source='L'))
        db.commit()

    results = {}
    for creds in (a, b):
        report = _make_report(gen, creds['user_id'])
        emp = db.query(Employee).filter(
            Employee.user_id == creds['user_id']).first()
        required = compute_required_minutes_for_range(
            db=db, employee=emp, start_date=G_START, end_date=G_END,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            hourly_leave_minutes_by_date={}, mission_dates=set(),
            hourly_mission_minutes_by_date={},
        )
        results[creds['user_id']] = {
            'actual': report['summary']['total_work_hours'],
            'duty': report['summary']['duty_hours'],
            'required_hours': required / 60,
        }

    ra, rb = results[a['user_id']], results[b['user_id']]

    # Actual از Central Engine — برای هر دو یکسان (۴ روز × ۹ ساعت)
    assert ra['actual'] == pytest.approx(rb['actual'])
    assert ra['actual'] == pytest.approx(36.0)

    # Required از Policy/Schedule هر فرد — متفاوت
    assert ra['duty'] == pytest.approx(ra['required_hours'])
    assert rb['duty'] == pytest.approx(rb['required_hours'])
    assert ra['duty'] != rb['duty']

    # نه hard-code (440 دقیقه/روز یا 7.33 ساعت)
    assert ra['duty'] != pytest.approx(31 * 440 / 60)
    assert rb['duty'] != pytest.approx(31 * 440 / 60)


# ---------------------------------------------------------------------------
# ۶) UI: route بدون تغییر، labelهای فعلی حفظ می‌شوند
# ---------------------------------------------------------------------------
def test_monthly_full_route_renders_existing_labels(
        db, client, make_user, monkeypatch):
    from .conftest import login_as

    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
    admin = make_user(role='super_admin', balance_al=None)
    target = make_user(role='user', balance_al=30, department='4')
    _seed_report_month(db, target['user_id'])
    try:
        login_as(client, admin['national_code'])
        resp = client.post('/reports/monthly-full', data={
            'target_user_id': target['user_id'],
            'year': J_YEAR,
            'month': J_MONTH,
        })
        assert resp.status_code == 200
        html = resp.text
        # labelهای موجود بدون تغییر
        assert 'کامل (خروج فردا)' in html
        assert 'کامل (ورود دیروز)' in html
        assert 'ناقص (4و/3خ)' in html
        # جدول/ستون‌ها: همچنان ۳ جفت
        assert '۳ جفت ورود/خروج' in html
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۷) dump قبل/بعد (مرحله ۱۳) — فقط با MONTHLY_FULL_DUMP=<path>
# ---------------------------------------------------------------------------
def test_dump_report_json(db, make_user, gen):
    path = os.getenv('MONTHLY_FULL_DUMP')
    if not path:
        pytest.skip('MONTHLY_FULL_DUMP not set')
    creds = make_user(role='user', balance_al=30, department='4')
    _seed_report_month(db, creds['user_id'])
    try:
        report = _make_report(gen, creds['user_id'])
        out = _normalize(report)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2, sort_keys=True)
    finally:
        _cleanup_holiday(db)


def _normalize(obj):
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, float):
        return round(obj, 9)
    return obj
