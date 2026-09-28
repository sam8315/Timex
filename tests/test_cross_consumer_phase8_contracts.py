"""
Phase 8 — قرارداد cross-consumer و جداسازی «نمایش» از «Actual Work».

Phase 6 (`tests/test_cross_consumer_consistency.py`) توافق سه مصرف‌کننده را
روی یک seed استاندارد قفل کرده است. این فایل دو چیز را اضافه می‌کند:

  8.8  جداسازی سقف نمایشی pair از Actual Work
       `attendance_pairs` در گزارش ماهانه سقف نمایشی دارد (MAX_PAIRS)،
       ولی `work_hours` باید از *همه* pairها بیاید. اگر کسی سقف نمایش را
       به محاسبه نشت بدهد، ساعت کارکرد کم می‌شود — و هیچ تست قبلی این را
       با روزی که واقعاً بیش از ۳ بازه دارد نمی‌گرفت.

  8.12 برابری سه‌گانه روی Actual Attendance برای روزی با بیش از ۳ بازه.
"""
from datetime import date, datetime, timedelta

import pytest

from core.attendance_calculator import compute_day_attendance
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from models.attendance import Attendance
from models.holiday import Holiday
from tests.conftest import TestingSessionLocal

from .test_attendance_route_regression import (
    G_END,
    G_START,
    J_MONTH,
    J_YEAR,
    _cleanup_holiday,
    _seed_punches,
)
from .test_monthly_full_central_engine import _day, _make_report, _naive

# روزی با ۵ بازه‌ی کامل داخل ماه (بیش از سقف نمایشی ۳)
MANY_INTERVALS_DAY = date(2024, 3, 25)   # جمعه نیست، داخل ماه
MANY_INTERVALS = [
    (8, 0, 9, 0), (10, 0, 11, 0), (12, 0, 13, 0),
    (14, 0, 15, 0), (16, 0, 17, 0),
]
MAX_PAIRS = DetailedMonthlyReportGeneratorV2.MAX_PAIRS


@pytest.fixture()
def gen(monkeypatch):
    monkeypatch.setattr(
        'core.detailed_monthly_report_v2.SessionLocal', TestingSessionLocal)
    generator = DetailedMonthlyReportGeneratorV2()
    try:
        yield generator
    finally:
        generator.close()


@pytest.fixture()
def seeded(db, make_user):
    db.query(Holiday).filter(
        Holiday.holiday_date >= G_START,
        Holiday.holiday_date <= G_END,
    ).delete()
    db.commit()

    created = make_user(role='user', department='4')
    uid = created['user_id']
    _seed_punches(db, uid)

    # روی روز هدف، punchهای استاندارد seed را پاک و ۵ بازه می‌گذاریم
    db.query(Attendance).filter(
        Attendance.user_id == uid,
        Attendance.timestamp >= datetime.combine(MANY_INTERVALS_DAY, datetime.min.time()),
        Attendance.timestamp < datetime.combine(
            MANY_INTERVALS_DAY + timedelta(days=1), datetime.min.time()),
    ).delete()

    for h1, m1, h2, m2 in MANY_INTERVALS:
        db.add(Attendance(
            user_id=uid,
            timestamp=datetime(MANY_INTERVALS_DAY.year, MANY_INTERVALS_DAY.month,
                               MANY_INTERVALS_DAY.day, h1, m1),
            punch=0, source='M'))
        db.add(Attendance(
            user_id=uid,
            timestamp=datetime(MANY_INTERVALS_DAY.year, MANY_INTERVALS_DAY.month,
                               MANY_INTERVALS_DAY.day, h2, m2),
            punch=1, source='M'))
    db.commit()

    try:
        yield uid
    finally:
        _cleanup_holiday(db)


def _engine_for_day(db, uid, target):
    records = db.query(Attendance).filter(
        Attendance.user_id == uid,
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()
    by_day = {}
    for rec in records:
        by_day.setdefault(rec.timestamp.date(), []).append(rec)

    return compute_day_attendance(
        day=target,
        day_records=by_day.get(target, []),
        prev_day_records=by_day.get(target - timedelta(days=1), []),
        next_day_records=by_day.get(target + timedelta(days=1), []),
        is_friday=target.weekday() == 4,
    )


# ============================================================
# 8.8 — سقف نمایشی pair نباید Actual Work را کوتاه کند
# ============================================================
def test_display_pair_cap_does_not_truncate_actual_work(db, gen, seeded):
    report = _make_report(gen, seeded, J_YEAR, J_MONTH)
    day = _day(report, MANY_INTERVALS_DAY)
    engine = _engine_for_day(db, seeded, MANY_INTERVALS_DAY)

    # موتور باید هر ۵ بازه را داشته باشد
    assert len(engine.pairs) == 5, 'موتور نباید pair را محدود کند'
    assert engine.work_hours == pytest.approx(5.0)

    # لایه‌ی نمایش فقط ۳ تا نشان می‌دهد
    assert len(day['attendance_pairs']) == MAX_PAIRS
    assert MAX_PAIRS < len(engine.pairs), 'این تست باید روزی با بیش از سقف بگیرد'

    # و Actual Work همچنان کل ۵ ساعت است، نه ۳ ساعت
    assert day['work_hours'] == pytest.approx(5.0)
    assert day['work_hours'] == pytest.approx(
        sum(p['hours'] for p in engine.pairs))

    # pairهای نمایش‌داده‌شده همان ۳ تای اول موتور باشند (نه بازمحاسبه‌شده)
    shown = day['attendance_pairs']
    for shown_pair, engine_pair in zip(shown, engine.pairs[:MAX_PAIRS]):
        assert _naive(shown_pair['enter']) == engine_pair['enter']
        assert _naive(shown_pair['exit']) == engine_pair['exit']
        assert shown_pair['hours'] == pytest.approx(engine_pair['hours'])


def test_monthly_total_uses_uncapped_work_hours(gen, seeded):
    """مجموع ماه هم باید از کارکرد کامل بیاید، نه از pairهای نمایشی."""
    report = _make_report(gen, seeded, J_YEAR, J_MONTH)
    day = _day(report, MANY_INTERVALS_DAY)

    day_sum = sum(d['work_hours'] for d in report['days'])
    reported_total = report['summary']['total_work_hours']

    # مجموع روزها باید شامل کل ۵ ساعت آن روز باشد
    assert day_sum >= day['work_hours']
    # و مقدار گزارش‌شده نباید کمتر از مجموع واقعی روزها باشد
    # (سقف نمایشی نباید ساعت را از مجموع ماه هم کم کند)
    assert reported_total == pytest.approx(day_sum, abs=0.05)


# ============================================================
# 8.12 — برابری سه‌گانه روی این روز خاص
# ============================================================
def test_three_way_parity_on_many_intervals_day(db, gen, seeded):
    """
    موتور ↔ گزارش ماهانه برای روزی با ۵ بازه باید دقیقاً یکی باشند.
    (برابری کامل با routeها در `test_cross_consumer_consistency.py` قفل است؛
    اینجا تمرکز روی روزِ چندبازه‌ای است که آن تست نداشت.)
    """
    report = _make_report(gen, seeded, J_YEAR, J_MONTH)
    day = _day(report, MANY_INTERVALS_DAY)
    engine = _engine_for_day(db, seeded, MANY_INTERVALS_DAY)

    assert day['work_hours'] == pytest.approx(engine.work_hours)
    assert engine.is_night_shift is False

    # اولین ورود و آخرین خروج از طریق pairهای نمایشی قابل بازسازی‌اند
    assert _naive(day['attendance_pairs'][0]['enter']) == engine.first_enter
    assert _naive(day['attendance_pairs'][-1]['exit']) == engine.pairs[2]['exit']

    # هر ۵ بازه دقیقاً یک ساعته و مجموعشان ۵ ساعت
    hours = [p['hours'] for p in engine.pairs]
    assert hours == [1.0] * 5
    assert sum(hours) == pytest.approx(day['work_hours'])


def test_shift_breakdown_uses_full_bounds_not_capped_pairs(gen, seeded):
    """
    Regression برای نشت سقف نمایشی (Phase 8).

    قبلاً `morning/evening/night` از `attendance_pairs[-1]['exit']` گرفته
    می‌شد، ولی آن لیست سقف‌خورده است. برای روزی با ۵ بازه، تفکیک شیفت
    تا ۱۵:۰۰ محاسبه می‌شد نه تا ۱۷:۰۰.

    حالا تفکیک از مرزهای کامل موتور می‌آید، در حالی که `attendance_pairs`
    همچنان سقف‌خورده می‌ماند (بدون تغییر UI).
    """
    report = _make_report(gen, seeded, J_YEAR, J_MONTH)
    day = _day(report, MANY_INTERVALS_DAY)

    # جفت‌های نمایشی فقط ۳ تای اول‌اند → آخرین exit نمایشی 13:00 است
    shown_last = _naive(day['attendance_pairs'][-1]['exit'])
    assert shown_last == datetime(2024, 3, 25, 13, 0)

    # تفکیک شیفت، بازه‌ی زمانی 08:00 → 17:00 را می‌پوشاند (صبح+عصر)،
    # نه بازه‌ی کوتاه‌شده‌ی 08:00 → 13:00 که از pairهای سقف‌خورده می‌آمد.
    breakdown = (day['morning_hours'] + day['evening_hours']
                 + day['night_hours'])
    assert breakdown == pytest.approx(9.0), (
        'تفکیک شیفت باید کل بازه‌ی 08:00→17:00 را بپوشاند')
    assert breakdown > 0

    # مقدار اشتباهِ قبلی (از pairهای سقف‌خورده) دقیقاً 5.0 بود
    assert breakdown != pytest.approx(5.0), (
        'اگر تفکیک 5.0 شد یعنی دوباره از pairهای نمایشی خوانده شده است')


def test_no_consumer_recomputes_actual_work(db, gen, seeded):
    """
    نگهبند ساختاری: هیچ‌کدام از سه مسیر نباید `/3600` خودش را داشته باشد
    (سقف نمایشی و گرد کردن مجاز است، محاسبه‌ی ساعت نه).
    """
    import pathlib
    import re

    import core.detailed_monthly_report_v2 as monthly_mod
    import web.routes.admin as admin_mod
    import web.routes.attendance as att_mod

    for mod in (att_mod, admin_mod, monthly_mod):
        src = pathlib.Path(mod.__file__).read_text(encoding='utf-8')
        code = re.sub(r'#.*', '', src)
        code = re.sub(r'""".*?"""', '', code, flags=re.S)
        assert not re.search(r'total_seconds\(\)\s*/\s*3600', code), (
            f'{mod.__name__} نباید ساعت کارکرد را خودش حساب کند')
        assert not re.search(r'/\s*3600\.0', code), (
            f'{mod.__name__} نباید ساعت کارکرد را خودش حساب کند')
