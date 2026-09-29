"""
Phase 7 — یافته‌ی بازرسی: `core/attendance_analyzer.py` یک موتور دومِ
Actual Attendance است، ولی مهاجرت آن به Central Engine در این Phase
عمداً انجام نشد.

چرا؟

`AttendanceAnalyzer.get_user_attendance_range` ساعت کارکرد را مستقل حساب
می‌کند (`core/attendance_analyzer.py:322`):

    delta = out_record.timestamp - in_record.timestamp
    total_work_hours += delta.total_seconds() / 3600.0

ولی «روز» در این تابع با روزِ تقویمی یکی نیست: هر شیفت با
`'date': pending_in.timestamp.date()` کلید می‌خورد (یعنی **روزِ ورود**)، و
ساعت شیفت هم به‌طور کامل به همان روز نسبت داده می‌شود.

Central Engine برعکس است: روز تقویمی است و کارکردِ یک شیفت شبانه بین دو
روز **تقسیم** می‌شود (مثلاً ورود ۲۲:۰۰ با خروج ۰۶:۰۰ فردا → روز اول ~۲ ساعت
تا ۲۳:۵۹:۵۹، روز دوم ۶ ساعت از ۰۰:۰۰).

روی همان seed استاندارد Phase 3 این تفاوت یعنی:

    2024-03-19 ورود ۲۲:۰۰  /  2024-03-20 خروج ۰۶:۰۰

    تحلیلگر (فعلی) : یک ردیف برای 2024-03-19 با 8.0 ساعت
    موتور مرکزی    : 2024-03-19 → 1.99972 ساعت
                     2024-03-20 → 6.0 ساعت

پس مهاجرت مستقیم باعث می‌شد:
  - حدود ۶ ساعت از مجموع `summary.total_work_hours` حذف شود،
  - ردیف روز 2024-03-20 در خروجی ظاهر شود (یا ردیف دیگری حذف شود)،
  - یعنی **ظاهر گزارش کنسولی تغییر کند**.

تغییر ظاهر گزارش و تغییر semantics نسبت‌دادنِ ساعت به روز، خارج از
قانون «ZERO UI CHANGE» و خارج از محدوده‌ی یک audit/migration ساده است و
تصمیم محصولی می‌خواهد. طبق قانون «انتشار تغییر غیرمنتظره»، این یافته
اینجا **مستند و pin** می‌شود، نه اینکه خودسرانه اعمال شود.

آنچه این فایل تضمین می‌کند:
  - وضعیت فعلی (قبل از هر تصمیم آینده) pin می‌شود تا تغییر ناخواسته دیده شود
  - قرارداد day-attribution شیفت‌محور صریحاً ثبت می‌شود
  - انحراف از رفتار موتور مرکزی اندازه‌گیری و مستند می‌شود
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import core.attendance_analyzer as analyzer_mod
from core.attendance_analyzer import AttendanceAnalyzer
from core.attendance_calculator import compute_day_attendance
from models.holiday import Holiday
from tests.conftest import TestingSessionLocal

from .test_attendance_route_regression import (
    G_END,
    G_START,
    _cleanup_holiday,
    _seed_punches,
)

ANALYZER_MODULE = Path(analyzer_mod.__file__)

# شب مرزیِ مرز ماه: ورود ۲۲:۰۰ در ۲۰۲۴-۰۳-۱۹ و خروج ۰۶:۰۰ در ۲۰۲۴-۰۳-۲۰
NIGHT_ENTER_DAY = date(2024, 3, 19)
NIGHT_EXIT_DAY = date(2024, 3, 20)


@pytest.fixture()
def analyzer(monkeypatch):
    monkeypatch.setattr(
        'core.attendance_analyzer.SessionLocal', TestingSessionLocal)
    instance = AttendanceAnalyzer()
    try:
        yield instance
    finally:
        instance.close()


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
    try:
        yield uid
    finally:
        _cleanup_holiday(db)


def _engine_days(db, uid, from_date, to_date):
    from models.attendance import Attendance
    records = db.query(Attendance).filter(
        Attendance.user_id == uid,
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()
    by_day = {}
    for rec in records:
        by_day.setdefault(rec.timestamp.date(), []).append(rec)

    out = {}
    current = from_date
    while current <= to_date:
        out[current] = compute_day_attendance(
            day=current,
            day_records=by_day.get(current, []),
            prev_day_records=by_day.get(current - timedelta(days=1), []),
            next_day_records=by_day.get(current + timedelta(days=1), []),
            is_friday=current.weekday() == 4,
        )
        current += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# ۱) هنوز یک موتور دوم است (یافته‌ی بازرسی، نه اشکال پنهان)
# ---------------------------------------------------------------------------
def test_analyzer_still_has_own_work_hours_math():
    """
    pin عمدی: اگر روزی مهاجرت این ماژول انجام شد، این تست عمداً می‌شکند تا
    تصمیم آگاهانه گرفته شود (نه به‌صورت تصادفی و بی‌صدا).
    """
    source = ANALYZER_MODULE.read_text(encoding='utf-8')

    assert re.search(
        r'total_work_hours\s*\+=\s*delta\.total_seconds\(\)\s*/\s*3600', source), \
        'اگر این الگو ناپدید شد، تحلیلگر مهاجرت داده شده — تست‌های این فایل ' \
        'و تصمیم محصولی مربوط به آن باید به‌روزرسانی شوند'

    # روز = روزِ ورودِ شیفت (نه روز تقویمی)
    assert "'date': pending_in.timestamp.date()" in source, \
        'قرارداد نسبت‌دادن شیفت به روزِ ورود تغییر کرده است'


# ---------------------------------------------------------------------------
# ۲) قرارداد فعلی خروجی pin می‌شود
# ---------------------------------------------------------------------------
def test_current_output_contract(analyzer, seeded):
    result = analyzer.get_user_attendance_range(seeded, NIGHT_ENTER_DAY, G_END)

    assert 'error' not in result, result.get('error')
    for key in ('user', 'from_date', 'to_date', 'days', 'summary'):
        assert key in result, f'کلید {key} حذف شده'

    for day in result['days']:
        for key in ('date', 'first_enter', 'last_exit', 'enter_count',
                    'exit_count', 'is_complete', 'work_hours', 'night_hours',
                    'has_sequence_error', 'sequence_errors', 'all_records'):
            assert key in day, f'کلید day.{key} حذف شده'

    for key in ('total_days', 'complete_days', 'incomplete_days',
                'sequence_error_days', 'total_work_hours',
                'total_night_hours'):
        assert key in result['summary'], f'کلید summary.{key} حذف شده'


# ---------------------------------------------------------------------------
# ۳) انحراف دقیق از رفتار موتور مرکزی (شیفت شبِ مرزی)
# ---------------------------------------------------------------------------
def test_shift_attribution_differs_from_central_engine(db, analyzer, seeded):
    """
    انحراف شناخته‌شده و اندازه‌گیری‌شده. اگر روزی مهاجرت انجام شود، این تست
    عمداً می‌شکند و آن‌وقت باید تصمیم آگاهانه ثبت شود.
    """
    result = analyzer.get_user_attendance_range(
        seeded, NIGHT_ENTER_DAY, G_END)
    days = {d['date']: d for d in result['days']}

    # تحلیلگر: یک ردیف، با کل ساعت شیفت، روی روزِ ورود
    assert NIGHT_EXIT_DAY not in days, \
        'روزِ خروج نباید ردیف جدا داشته باشد (قرارداد شیفت‌محور)'
    assert days[NIGHT_ENTER_DAY]['work_hours'] == pytest.approx(8.0), \
        'کل شیفت ۲۲:۰۰→۰۶:۰۰ باید به روزِ ورود نسبت داده شود'

    # موتور مرکزی: روز تقویمی، ساعت بین دو روز تقسیم می‌شود
    engine = _engine_days(db, seeded, NIGHT_ENTER_DAY, G_END)
    enter_result = engine[NIGHT_ENTER_DAY]
    exit_result = engine[NIGHT_EXIT_DAY]

    assert enter_result.main_status == 'night_shift'
    assert exit_result.main_status == 'night_shift'

    enter_hours = float(enter_result.work_hours)
    exit_hours = float(exit_result.work_hours)

    # مجموع دو روز موتور = کل شیفت (به‌علاوه یک ثانیه مرزی ۲۳:۵۹:۵۹→۰۰:۰۰)
    assert enter_hours + exit_hours == pytest.approx(8.0, abs=0.01)
    # ولی هیچ‌کدام به‌تنهایی ۸ ساعت نیست — همین ریشه‌ی ناسازگاری است
    assert enter_hours < 8.0 and exit_hours < 8.0
