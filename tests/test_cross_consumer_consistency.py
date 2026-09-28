"""
Phase 6 — Cross-Consumer Consistency Audit (یک dataset → سه مصرف‌کننده).

سه مصرف‌کننده‌ی Actual Attendance روی یک seed مشترک (Phase 3):

    /attendance                      (دید شخصی  — web/routes/attendance.py)
    /admin/attendance/user/{id}      (دید ادمین — web/routes/admin.py)
    /reports/monthly-full            (گزارش     — core/detailed_monthly_report_v2.py)

قراردادها:
    - work_hours خام (بدون round در سطح روز) از یک منبع: compute_day_attendance
    - status / warnings / first_enter / last_exit در دو مسیر یکسان
    - نگاشت display ماهانه فقط در لایه گزارش (_display_status)
    - مرز ماه: روزهای context فقط context موتورند، در ماه لحاظ نمی‌شوند
    - شیفت شب: سه state + 00:00:00 / 23:59:59 ضمنی

تنها تفاوت آگاهانه/مستند (دسته F + تغییر مستند Phase 5 دسته A):
    1403/01/18 (2024-04-07) روز مرخصی با الگوی شب:
        · مسیرها  : leave-override قدیمی → work_hours = 0.0
        · ماهانه  : مقدار موتور مرکزی   → 6 + 7199/3600 ساعت
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import re

import pytest

import core.attendance_calculator as engine_mod
import core.detailed_monthly_report_v2 as monthly_mod
import web.routes.admin as admin_mod
import web.routes.attendance as attendance_route_mod
from core.attendance_calculator import (
    DayAttendanceResult,
    STATUS_NO_ATTENDANCE,
    compute_day_attendance,
)
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from models.holiday import Holiday
from tests.conftest import TestingSessionLocal, login_as

from .test_admin_attendance_central_engine import (
    _capture_admin_context,
    _seed_target,
)
from .test_attendance_route_regression import (
    G_END,
    G_START,
    HOLIDAY_DATE,
    HOLIDAY_TITLE,
    J_MONTH,
    J_YEAR,
    LEAVE_DATES,
    _capture_context,
    _cleanup_holiday,
    _fetch_records_with_margin,
    _month_bounds,
)
from .test_monthly_full_central_engine import _day, _make_report, _naive

# تنها روز مرخصی + الگوی شب → تفاوت مستند مسیرها در مقابل ماهانه
LEAVE_NIGHT_DAY = date(2024, 4, 7)

NIGHT_DAYS = {
    date(2024, 3, 20),   # state 3: خروجِ صبح + ورودِ دیروز (00:00:00 ضمنی)
    date(2024, 4, 2),    # state 2: ورودِ شب + خروجِ روز بعد (23:59:59 ضمنی)
    date(2024, 4, 3),    # state 3: فقط خروجِ صبح
    date(2024, 4, 19),   # state 2: فقط ورودِ شب (23:59:59 ضمنی)
}

LEGACY_STATUS_KEYS = {
    'main_status', 'main_label', 'main_color', 'warnings',
    'is_friday', 'is_holiday', 'holiday_title',
}


@pytest.fixture()
def gen(monkeypatch):
    monkeypatch.setattr(
        'core.detailed_monthly_report_v2.SessionLocal', TestingSessionLocal)
    generator = DetailedMonthlyReportGeneratorV2()
    try:
        yield generator
    finally:
        generator.close()


def _views(db, client, make_user, monkeypatch, gen):
    """سه نمای روی یک seed مشترک: /attendance، /admin/...، monthly-full."""
    # holidayهای باقی‌مانده از تست‌های دیگر نباید روی این ماه اثر بگذارند
    db.query(Holiday).filter(
        Holiday.holiday_date >= G_START,
        Holiday.holiday_date <= G_END,
    ).delete()
    db.commit()

    admin, target = _seed_target(db, make_user)
    uid = target['user_id']

    login_as(client, target['national_code'])
    att_ctx, _ = _capture_context(client, monkeypatch, J_YEAR, J_MONTH)

    login_as(client, admin['national_code'])
    adm_ctx, _ = _capture_admin_context(
        client, monkeypatch, uid, J_YEAR, J_MONTH)

    report = _make_report(gen, uid, J_YEAR, J_MONTH)
    return att_ctx, adm_ctx, report, uid


def _by_date(days):
    return {d['date']: d for d in days}


def _month_days():
    out = set()
    current, month_end = _month_bounds()
    while current <= month_end:
        out.add(current)
        current += timedelta(days=1)
    return out


def _engine_days(db, uid):
    """فراخوانی مستقیم موتور مرکزی با همان context مسیرها (-1/+2 روز)."""
    records = _fetch_records_with_margin(db, uid)
    days_dict = {}
    for rec in records:
        days_dict.setdefault(rec.timestamp.date(), []).append(rec)
    out = {}
    for current in _month_days():
        out[current] = compute_day_attendance(
            day=current,
            day_records=days_dict.get(current, []),
            prev_day_records=days_dict.get(current - timedelta(days=1), []),
            next_day_records=days_dict.get(current + timedelta(days=1), []),
            is_friday=current.weekday() == 4,
            holiday_title=HOLIDAY_TITLE if current == HOLIDAY_DATE else None,
        )
    return out


def _expected_monthly(main_status, enters, exits):
    """قرارداد نگاشت display ماهانه — آینه‌ی _display_status (لایه نمایش)."""
    if main_status == STATUS_NO_ATTENDANCE or (enters == 0 and exits == 0):
        return 'بدون تردد', False
    if main_status == 'night_shift':
        if exits == 0:
            return 'کامل (خروج فردا)', False
        if enters == 0:
            return 'کامل (ورود دیروز)', False
        if enters == exits:
            return ('کامل' if enters == 1 else f'کامل{enters}'), False
        return f'ناقص ({enters}و/{exits}خ)', True
    if exits == 0:
        return f'ورود بدون خروج ({enters} ورود)', True
    if enters == 0:
        return f'خروج بدون ورود ({exits} خروج)', True
    if enters == exits:
        return ('کامل' if enters == 1 else f'کامل{enters}'), False
    return f'ناقص ({enters}و/{exits}خ)', True


def _counts(day):
    enters = sum(1 for r in day['records'] if r.punch == 0)
    exits = sum(1 for r in day['records'] if r.punch == 1)
    return enters, exits


# ---------------------------------------------------------------------------
# ۱) /attendance در برابر /admin/attendance/user: نمای یکسان روزبه‌روز
# ---------------------------------------------------------------------------
def test_views_identical_across_attendance_and_admin(
        db, client, make_user, monkeypatch, gen):
    att_ctx, adm_ctx, report, uid = _views(
        db, client, make_user, monkeypatch, gen)
    try:
        att, adm = _by_date(att_ctx['days']), _by_date(adm_ctx['days'])
        assert set(att) == set(adm) == _month_days()
        assert len(att) == 31

        for g in sorted(att):
            a, b = att[g], adm[g]
            assert a['work_hours'] == b['work_hours'], f'work_hours {g}'
            assert a['first_enter'] == b['first_enter'], f'first_enter {g}'
            assert a['last_exit'] == b['last_exit'], f'last_exit {g}'
            assert a['is_friday'] == b['is_friday'], f'is_friday {g}'
            assert a['is_holiday'] == b['is_holiday'], f'is_holiday {g}'
            assert a['holiday_title'] == b['holiday_title'], f'title {g}'
            sa, sb = a['status'], b['status']
            assert sa['main_status'] == sb['main_status'], f'status {g}'
            assert sa['main_label'] == sb['main_label'], f'label {g}'
            assert sa['warnings'] == sb['warnings'], f'warnings {g}'

        total_att = sum(d['work_hours'] for d in att_ctx['days'])
        total_adm = sum(d['work_hours'] for d in adm_ctx['days'])
        assert total_att == total_adm

        nights_att = {g for g in att
                      if att[g]['status']['main_status'] == 'night_shift'}
        nights_adm = {g for g in adm
                      if adm[g]['status']['main_status'] == 'night_shift'}
        assert nights_att == nights_adm == NIGHT_DAYS
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۲) work_hours: موتور == ماهانه (بدون استثنا)؛ مسیرها == موتور
#    به‌جز leave-override مستندِ روز مرخصی+شب
# ---------------------------------------------------------------------------
def test_work_hours_single_source_engine_monthly_routes(
        db, client, make_user, monkeypatch, gen):
    att_ctx, adm_ctx, report, uid = _views(
        db, client, make_user, monkeypatch, gen)
    try:
        att, adm = _by_date(att_ctx['days']), _by_date(adm_ctx['days'])
        engine = _engine_days(db, uid)

        # (الف) موتور مرکزی == گزارش ماهانه برای هر ۳۱ روز
        for g in sorted(engine):
            assert engine[g].work_hours == _day(report, g)['work_hours'],                 f'engine/monthly {g}'

        # (ب) دو مسیر == هم (بدون استثنا)
        for g in sorted(engine):
            assert att[g]['work_hours'] == adm[g]['work_hours'], f'adm {g}'
            assert att[g]['first_enter'] == engine[g].first_enter, f'fe {g}'
            assert att[g]['last_exit'] == engine[g].last_exit, f'le {g}'

        # (ج) مسیرها == موتور، فقط با استثنای مستند leave-override
        diffs = [g for g in sorted(engine)
                 if att[g]['work_hours'] != engine[g].work_hours]
        assert diffs == [LEAVE_NIGHT_DAY], diffs
        assert att[LEAVE_NIGHT_DAY]['work_hours'] == 0.0
        assert engine[LEAVE_NIGHT_DAY].is_night_shift is True   # state 1
        assert engine[LEAVE_NIGHT_DAY].work_hours == 6 + 7199 / 3600

        # (د) گرد نکردن در سطح روز — رشته‌های C (Phase 5) در هر سه نما
        for g, raw in ((date(2024, 3, 30), 30 / 3600),          # تردد ۳۰ ثانیه‌ای
                       (date(2024, 4, 2), 7199 / 3600),          # 23:59:59
                       (G_START, 6.0),
                       (G_END, 7199 / 3600)):
            assert att[g]['work_hours'] == raw, f'att {g}'
            assert adm[g]['work_hours'] == raw, f'adm {g}'
            assert _day(report, g)['work_hours'] == raw, f'mon {g}'

        # (ه) جمع‌ها: دو مسیر برابر؛ ماهانه = مسیرها + روز مرخصی+شب مستند
        total_att = sum(d['work_hours'] for d in att_ctx['days'])
        total_adm = sum(d['work_hours'] for d in adm_ctx['days'])
        total_mon = sum(d['work_hours'] for d in report['days'])
        assert total_att == total_adm
        assert total_mon == pytest.approx(
            total_att + (6 + 7199 / 3600), abs=1e-9)
        assert report['summary']['total_work_hours'] == round(total_mon, 2)
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۳) نگاشت display ماهانه + مرز ماه + برچسب‌های شیفت شب
# ---------------------------------------------------------------------------
def test_monthly_display_mapping_boundary_and_night_labels(
        db, client, make_user, monkeypatch, gen):
    att_ctx, adm_ctx, report, uid = _views(
        db, client, make_user, monkeypatch, gen)
    try:
        att, adm = _by_date(att_ctx['days']), _by_date(adm_ctx['days'])
        engine = _engine_days(db, uid)
        mon = _by_date(report['days'])

        assert set(mon) == _month_days() == set(att) == set(adm)
        assert len(report['days']) == 31
        assert G_START - timedelta(days=1) not in mon     # context فقط
        assert G_END + timedelta(days=1) not in mon

        for g in sorted(engine):
            e = engine[g]
            enters, exits = _counts(att[g])
            label, incomplete = _expected_monthly(e.main_status, enters, exits)
            assert mon[g]['attendance_status'] == label, f'mapping {g}'
            assert mon[g]['has_incomplete'] == incomplete, f'incomplete {g}'
            assert mon[g]['is_friday'] == att[g]['is_friday'] ==                 adm[g]['is_friday'], f'friday {g}'
            assert mon[g]['is_holiday'] == att[g]['is_holiday'] ==                 adm[g]['is_holiday'], f'holiday {g}'

            # دو مسیر: status موتور (به‌جز روزهای leave که override قدیمی دارند)
            if g not in LEAVE_DATES:
                sd = att[g]['status']
                for key, value in e.attendance_status_dict.items():
                    assert sd.get(key) == value, f'status {g} {key}'

        # برچسب‌های شب مرزی (state 2 و 3) + زمان‌های ضمنی
        assert mon[G_START]['attendance_status'] == 'کامل (ورود دیروز)'
        assert mon[date(2024, 4, 3)]['attendance_status'] == 'کامل (ورود دیروز)'
        assert mon[date(2024, 4, 2)]['attendance_status'] == 'کامل (خروج فردا)'
        assert mon[G_END]['attendance_status'] == 'کامل (خروج فردا)'
        assert att[G_START]['first_enter'] == datetime(2024, 3, 20, 0, 0)
        assert att[G_END]['last_exit'] == datetime(2024, 4, 19, 23, 59, 59)
        assert _naive(mon[G_START]['attendance_pairs'][0]['enter']) ==             datetime(2024, 3, 20, 0, 0)
        assert _naive(mon[G_END]['attendance_pairs'][-1]['exit']) ==             datetime(2024, 4, 19, 23, 59, 59)
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۴) قرارداد pairs + بازبینی ایستای منبع واحد (یک واقعیت)
# ---------------------------------------------------------------------------
def test_pairs_guarantee_and_static_source_of_truth(
        db, client, make_user, monkeypatch, gen):
    att_ctx, adm_ctx, report, uid = _views(
        db, client, make_user, monkeypatch, gen)
    try:
        att = _by_date(att_ctx['days'])
        engine = _engine_days(db, uid)

        # (الف) قرارداد موتور: sum(pairs) == work_hours + سقف نمایشی ۳
        for g in sorted(engine):
            mon = _day(report, g)
            pairs = mon['attendance_pairs']
            assert len(pairs) <= 3, f'cap {g}'
            assert mon['work_hours'] == sum(p['hours'] for p in pairs),                 f'pairs-sum {g}'

        # (ب) روز بدون تردد: قرارداد DayAttendanceResult
        empty = engine[date(2024, 3, 29)]
        assert isinstance(empty, DayAttendanceResult)
        assert empty.main_status == STATUS_NO_ATTENDANCE
        assert empty.work_hours == 0.0
        assert empty.enter_count == 0 and empty.exit_count == 0
        assert empty.pairs == []
        assert set(empty.attendance_status_dict) == LEGACY_STATUS_KEYS

        # (ج) سه مصرف‌کننده مستقیماً از همان تابع موتور صدا می‌زنند
        assert (attendance_route_mod.compute_day_attendance
                is engine_mod.compute_day_attendance)
        assert (admin_mod.compute_day_attendance
                is engine_mod.compute_day_attendance)
        assert (monthly_mod.compute_day_attendance
                is engine_mod.compute_day_attendance)

        # (د) موتور واقعیت = بدون موظفی/سیاست/بدون hard-code
        src = Path(engine_mod.__file__).read_text(encoding='utf-8')
        for token in ('7.20', '7.33', '7:20', 'DAILY_DUTY_HOURS',
                      'compute_required_minutes'):
            assert token not in src, token
        assert not re.search(r'\b440\b', src)
        assert 'from web' not in src and 'import web' not in src
    finally:
        _cleanup_holiday(db)
