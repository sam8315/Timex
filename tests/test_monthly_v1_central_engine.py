"""
Phase 7 — Regression برای انتقال `core/detailed_monthly_report.py` (v1) به
Central Attendance Engine.

پیش از این Phase، `DetailedMonthlyReportGenerator` یک موتور دوم برای
Actual Attendance داشت:

    _calculate_day_work_hours(...)      → وضعیت + ساعات + first/last
    _calculate_total_work_hours(...)    → pairing مستقل enter/exit
    get_attendance_status(...)          → وضعیت مستقل

این موتور دوم «فعال» بود: `main.py` → `ui.console.ConsoleUI` →
`_show_detailed_monthly_report` → همین generator → Excel/PDF export.

مرجع «Before» = همان کد، عیناً به صورت frozen در `_old_day_calc` زیر.
قراردادهای این فایل:

  - Actual Attendance فقط از `core.attendance_calculator.compute_day_attendance`
  - pairing، night shift و وضعیت فقط در موتور مرکزی
  - Policy / موظفی / اضافه‌کار / خلاصه ماهانه در لایه گزارش می‌ماند
  - labelهای نمایشی قبلی این گزارش حفظ می‌شوند
  - دقت خام موتور حفظ می‌شود؛ گرد کردن فقط در لایه گزارش
  - روزهای حاشیه ماه فقط context موتورند و در ماه لحاظ نمی‌شوند
"""
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import core.detailed_monthly_report as monthly_v1
from core.attendance_calculator import (
    STATUS_NIGHT_SHIFT,
    STATUS_NO_ATTENDANCE,
    compute_day_attendance,
)
from core.detailed_monthly_report import DetailedMonthlyReportGenerator
from models.holiday import Holiday
from tests.conftest import TestingSessionLocal

from .test_attendance_route_regression import (
    EXPECTED_STATUS,
    G_END,
    G_START,
    HOLIDAY_DATE,
    HOLIDAY_TITLE,
    J_MONTH,
    J_YEAR,
    _cleanup_holiday,
    _month_bounds,
    _seed_punches,
)

REPORT_MODULE = Path(monthly_v1.__file__)

# روزهایی که در آن‌ها موتور دوم v1 با موتور مرکزی اختلاف دارد.
#
# در هر چهار مورد «موتور دوم» اشتباه می‌کرد و موتور مرکزی همان نتیجه‌ای را
# می‌دهد که Phase 2-6 قبلاً تثبیت کرده (و با EXPECTED_STATUS در
# tests/test_attendance_route_regression.py هم‌خوان است):
#
# 2024-03-20 (1403/01/01) — فقط خروج ۰۶:۰۰؛ دیروز ورود ۲۲:۰۰.
#     v1 قبل از «حالت ۳» بی‌دلیل اولین خروج را حذف می‌کرد (`exits[1:]`) و
#     روز را «بدون تردد» می‌زد. درست: night_shift، ۶ ساعت.
# 2024-03-26 — فقط خروج ۱۷:۰۰؛ آخرین punch دیروز «خروج» بود.
#     v1 شرط سست «روز قبل ورودی داشته» را کافی می‌دانست و ۱۷ ساعت ساخت.
#     درست: missing_enter، ۰ ساعت.
# 2024-04-03 — فقط خروج ۰۶:۰۰؛ دیروز ورود ۲۲:۰۰. همان باگ `exits[1:]`.
#     درست: night_shift، ۶ ساعت.
# 2024-04-07 (1403/01/18) — خروج ۰۶:۰۰ سپس ورود ۲۲:۰۰ در همان روز.
#     v1 شرط `last_exit > first_enter` را داشت و روز را «بدون تردد» می‌زد.
#     درست: night_shift (state 1)، ۸ ساعت.
#
# یعنی مهاجرت v1 صرفاً «تغییر ظاهر» نبود: یک موتور دومِ واقعاً نادرست
# کنار گذاشته شد. تفاوت‌ها محدود و کاملاً قابل‌شمارش‌اند.
DOCUMENTED_DIFFERENCES = frozenset({
    date(2024, 3, 20),
    date(2024, 3, 26),
    date(2024, 4, 3),
    date(2024, 4, 7),
})


# ---------------------------------------------------------------------------
# Fixture: generator متصل به test DB
# ---------------------------------------------------------------------------
@pytest.fixture()
def gen(monkeypatch):
    monkeypatch.setattr(
        'core.detailed_monthly_report.SessionLocal', TestingSessionLocal)
    generator = DetailedMonthlyReportGenerator()
    try:
        yield generator
    finally:
        generator.close()


@pytest.fixture()
def seeded(db, make_user):
    """کارمند با گروه '4' + همان punchهای ثابت Phase 3 (1403/01)."""
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


def _make_report(gen, uid, year=J_YEAR, month=J_MONTH):
    report = gen.generate_detailed_report(uid, year, month)
    assert report.get('success'), report.get('message')
    return report


def _by_date(days):
    return {d['date']: d for d in days}


def _month_days():
    out, current = [], _month_bounds()[0]
    month_end = _month_bounds()[1]
    while current <= month_end:
        out.append(current)
        current += timedelta(days=1)
    return out


def _engine_days(db, uid):
    """موتور مرکزی با context روز قبل/بعد — منبع مرجع actual attendance."""
    from models.attendance import Attendance
    records = db.query(Attendance).filter(
        Attendance.user_id == uid,
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()

    days_dict = {}
    for rec in records:
        days_dict.setdefault(rec.timestamp.date(), []).append(rec)

    return {
        current: compute_day_attendance(
            day=current,
            day_records=days_dict.get(current, []),
            prev_day_records=days_dict.get(current - timedelta(days=1), []),
            next_day_records=days_dict.get(current + timedelta(days=1), []),
            is_friday=current.weekday() == 4,
            holiday_title=HOLIDAY_TITLE if current == HOLIDAY_DATE else None,
        )
        for current in _month_days()
    }


def _expected_label(result):
    """قرارداد نگاشت display نسخه v1 (آینه‌ی _display_status — لایه نمایش)."""
    enters, exits = result.enter_count, result.exit_count

    if result.main_status == STATUS_NO_ATTENDANCE or (enters == 0 and exits == 0):
        return 'بدون تردد', False
    if result.main_status == STATUS_NIGHT_SHIFT:
        if exits == 0:
            return 'کامل(خروج سیستمی)', False
        if enters == 0:
            return 'کامل(ورود سیستمی)', False
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


# ---------------------------------------------------------------------------
# frozen: منطق نسخه v1 پیش از Phase 7 (عیناً، شامل pairing مستقل)
# ---------------------------------------------------------------------------
def _old_total_work_hours(enters, exits) -> float:
    total = 0.0
    for i, enter in enumerate(sorted(enters, key=lambda x: x.timestamp)):
        if i < len(exits):
            exit_time = exits[i].timestamp
            if exit_time > enter.timestamp:
                total += (exit_time - enter.timestamp).total_seconds() / 3600
    return total


def _old_day_calc(current, day_attendances, all_attendances, current_day_index):
    """کپی frozen از _calculate_day_work_hours قبل از Phase 7."""
    if not day_attendances:
        return {'work_hours': 0.0, 'first_enter': None, 'last_exit': None,
                'attendance_status': 'بدون تردد', 'has_incomplete': False}

    enters = sorted([a for a in day_attendances if a.punch == 0],
                    key=lambda x: x.timestamp)
    exits = sorted([a for a in day_attendances if a.punch == 1],
                   key=lambda x: x.timestamp)

    prev_day = current - timedelta(days=1)
    prev_att = [a for a in all_attendances if a.timestamp.date() == prev_day]
    prev_enters = [a for a in prev_att if a.punch == 0]
    prev_exits = [a for a in prev_att if a.punch == 1]
    if prev_enters and not prev_exits and exits:
        exits = exits[1:]

    def make_aware(d, hour, minute, second, microsecond, ref):
        naive = datetime.combine(d, datetime.min.time().replace(
            hour=hour, minute=minute, second=second, microsecond=microsecond))
        return naive.replace(tzinfo=ref.tzinfo) if ref.tzinfo else naive

    def get_status(enter_count, exit_count, suffix=''):
        if suffix:
            return f'کامل{suffix}'
        if enter_count == exit_count:
            return 'کامل' if enter_count == 1 else f'کامل{enter_count}'
        return f'ناقص ({enter_count}و/{exit_count}خ)'

    if enters and exits:
        first_enter = min(e.timestamp for e in enters)
        last_exit = max(e.timestamp for e in exits)
        if last_exit.date() > current:
            end_of_day = make_aware(current, 23, 59, 59, 999999, first_enter)
            return {'work_hours': round((end_of_day - first_enter).total_seconds() / 3600, 2),
                    'first_enter': first_enter, 'last_exit': end_of_day,
                    'attendance_status': get_status(len(enters), len(exits), '(خروج سیستمی)'),
                    'has_incomplete': False}
        if last_exit > first_enter:
            return {'work_hours': round(_old_total_work_hours(enters, exits), 2),
                    'first_enter': first_enter, 'last_exit': last_exit,
                    'attendance_status': get_status(len(enters), len(exits)),
                    'has_incomplete': len(enters) != len(exits)}

    if enters and not exits:
        first_enter = min(e.timestamp for e in enters)
        next_day = current + timedelta(days=1)
        next_exits = [a for a in all_attendances
                      if a.timestamp.date() == next_day and a.punch == 1]
        if next_exits:
            end_of_day = make_aware(current, 23, 59, 59, 999999, first_enter)
            return {'work_hours': round((end_of_day - first_enter).total_seconds() / 3600, 2),
                    'first_enter': first_enter, 'last_exit': end_of_day,
                    'attendance_status': get_status(len(enters), 0, '(خروج سیستمی)'),
                    'has_incomplete': False}
        return {'work_hours': 0.0, 'first_enter': first_enter, 'last_exit': None,
                'attendance_status': f'ورود بدون خروج ({len(enters)} ورود)',
                'has_incomplete': True}

    if exits and not enters:
        last_exit = max(e.timestamp for e in exits)
        prev_enters = [a for a in all_attendances
                       if a.timestamp.date() == (current - timedelta(days=1))
                       and a.punch == 0]
        if prev_enters:
            start_of_day = make_aware(current, 0, 0, 0, 0, last_exit)
            return {'work_hours': round((last_exit - start_of_day).total_seconds() / 3600, 2),
                    'first_enter': start_of_day, 'last_exit': last_exit,
                    'attendance_status': get_status(0, len(exits), '(ورود سیستمی)'),
                    'has_incomplete': False}
        return {'work_hours': 0.0, 'first_enter': None, 'last_exit': last_exit,
                'attendance_status': f'خروج بدون ورود ({len(exits)} خروج)',
                'has_incomplete': True}

    return {'work_hours': 0.0, 'first_enter': None, 'last_exit': None,
            'attendance_status': 'بدون تردد', 'has_incomplete': False}


# ---------------------------------------------------------------------------
# ۱) قرارداد: v1 مستقیماً همان تابع موتور مرکزی را صدا می‌زند
# ---------------------------------------------------------------------------
def test_v1_uses_central_engine_directly():
    assert monthly_v1.compute_day_attendance is compute_day_attendance


def test_v1_has_no_own_attendance_engine():
    """موتور دوم باید از فایل v1 حذف شده باشد (نه فقط بلااستفاده)."""
    source = REPORT_MODULE.read_text(encoding='utf-8')

    for removed in ('_calculate_day_work_hours', '_calculate_total_work_hours'):
        assert removed not in source, f'{removed} هنوز در v1 وجود دارد'

    # هیچ pairing / محاسبه ساعت مستقلی نمانده باشد
    assert not re.search(r'total_seconds\(\)\s*/\s*3600', source), \
        'v1 هنوز ساعت کارکرد را خودش حساب می‌کند'
    assert not re.search(r'\.punch\s*==', source), \
        'v1 هنوز خودش رکوردهای enter/exit را تفکیک می‌کند'

    # موظفی/سیاست همچنان در لایه گزارش است (خارج از Central Engine)
    assert 'DAILY_REQUIRED_HOURS' in source


# ---------------------------------------------------------------------------
# ۲) Actual Attendance هر روز = خروجی مستقیم موتور مرکزی
# ---------------------------------------------------------------------------
def test_every_day_comes_from_central_engine(db, gen, seeded):
    report = _make_report(gen, seeded)
    days = _by_date(report['days'])
    engine = _engine_days(db, seeded)

    assert set(days) == set(_month_days()), 'فقط روزهای داخل ماه در گزارش'

    for g, result in engine.items():
        day = days[g]
        # ساعت کارکرد: مقدار خام موتور (گرد کردن فقط لایه نمایش گزارش)
        assert day['work_hours'] == round(float(result.work_hours), 2), f'work_hours {g}'
        # first enter / last exit
        for key, expected in (('first_enter', result.first_enter),
                              ('last_exit', result.last_exit)):
            actual = day[key]
            if expected is None:
                assert actual is None, f'{key} {g}'
            else:
                assert actual is not None, f'{key} {g}'
                assert actual.replace(tzinfo=None) == expected.replace(tzinfo=None), \
                    f'{key} {g}'
        # وضعیت نمایشی v1 از وضعیت فنی موتور
        assert (day['attendance_status'], day['has_incomplete']) == \
            _expected_label(result), f'status {g}'


# ---------------------------------------------------------------------------
# ۳) Before/After: تفاوت‌ها فقط و فقط در روزهای مستند
# ---------------------------------------------------------------------------
def test_before_after_difference_is_enumerated(db, gen, seeded):
    """
    منطق قدیمی v1 در `_old_day_calc` نگه داشته شده. تفاوت «قبل/بعد» باید
    محدود به روزهای شیفت شب باشد؛ هر روز دیگری باید دقیقاً یکسان باشد.
    """
    from models.attendance import Attendance
    all_records = db.query(Attendance).filter(
        Attendance.user_id == seeded,
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()

    by_day = {}
    for rec in all_records:
        by_day.setdefault(rec.timestamp.date(), []).append(rec)

    report = _make_report(gen, seeded)
    days = _by_date(report['days'])

    # روزهایی که موتور مرکزی آن‌ها را night shift می‌داند
    engine = _engine_days(db, seeded)
    night_days = {g for g, r in engine.items() if r.main_status == STATUS_NIGHT_SHIFT}

    differing = set()
    for index, g in enumerate(_month_days()):
        old = _old_day_calc(g, by_day.get(g, []), all_records, index)
        new = days[g]
        if (round(old['work_hours'], 2) != new['work_hours']
                or old['attendance_status'] != new['attendance_status']):
            differing.add(g)

    # تفاوت «قبل/بعد» باید دقیقاً همان فهرست مستند باشد — نه بیشتر، نه کمتر.
    assert differing == DOCUMENTED_DIFFERENCES, (
        f'differing={sorted(differing)} '
        f'expected={sorted(DOCUMENTED_DIFFERENCES)}')

    # در هر روزِ متفاوت، اختلاف فقط در تشخیص شیفت شب است: موتور دوم یا
    # شب را از دست می‌داد (بدون تردد) یا شب را غلط حدس می‌زد.
    for g in sorted(differing):
        old = _old_day_calc(
            g, by_day.get(g, []), all_records, _month_days().index(g))
        engine_night = engine[g].main_status == STATUS_NIGHT_SHIFT
        old_guessed_night = 'سیستمی' in old['attendance_status']
        assert old_guessed_night != engine_night, \
            f'{g}: انتظار اختلاف فقط در state machine شیفت شب داشتیم'
        # و نتیجه موتور مرکزی باید با انتظار canonical Phase 3 یکی باشد.
        # برای روزهای مرخصی، EXPECTED_STATUS مقدار «بعد از leave-override»
        # مسیرها را نگه می‌دارد؛ خود موتور وضعیت خام (night_shift) را برمی‌گرداند
        # و override در لایه route اعمال می‌شود (رفتار مستند 1403/01/18).
        expected = EXPECTED_STATUS[g]
        if expected == 'leave':
            expected = STATUS_NIGHT_SHIFT
        assert engine[g].main_status == expected, f'engine status {g}'

    # روزهای کاملاً عادی باید byte-for-byte یکسان باشند
    normal = [g for g in _month_days()
              if g not in night_days and engine[g].enter_count == engine[g].exit_count
              and engine[g].enter_count > 0]
    assert normal, 'باید حداقل یک روز کامل وجود داشته باشد'
    for index, g in enumerate(_month_days()):
        if g not in normal:
            continue
        old = _old_day_calc(g, by_day.get(g, []), all_records, index)
        assert old['work_hours'] == days[g]['work_hours'], f'work_hours {g}'
        assert old['attendance_status'] == days[g]['attendance_status'], f'status {g}'
        assert old['has_incomplete'] == days[g]['has_incomplete'], f'incomplete {g}'


# ---------------------------------------------------------------------------
# ۴) دقت خام موتور حفظ می‌شود (فقط نمایش گرد می‌کند)
# ---------------------------------------------------------------------------
def test_raw_precision_preserved(db, gen, seeded):
    """مقدار موتور خام اعشار بیشتری دارد؛ گزارش فقط آن را نمایشی گرد می‌کند."""
    report = _make_report(gen, seeded)
    days = _by_date(report['days'])

    # هیچ روزی نباید بیش از ۲ رقم اعشار داشته باشد (فقط لایه نمایش)
    for g, day in days.items():
        assert round(day['work_hours'], 2) == day['work_hours'], f'precision {g}'

    # موتور مرکزی خام (بدون هیچ گرد کردنی) باید جایی اعشار بیشتری بدهد
    engine = _engine_days(db, seeded)
    raw = [float(r.work_hours) for r in engine.values()]
    assert any(abs(v - round(v, 2)) > 1e-9 for v in raw), \
        'انتظار حداقل یک مقدار با اعشار بیش از ۲ رقم در خروجی خام موتور'

    # و گزارش باید دقیقاً همان مقدار خام را (با گرد کردن نمایشی) نشان دهد
    for g, result in engine.items():
        assert days[g]['work_hours'] == round(float(result.work_hours), 2), g


# ---------------------------------------------------------------------------
# ۵) مرز ماه: context حاضر است، ولی روزهای بیرون از ماه شمرده نمی‌شوند
# ---------------------------------------------------------------------------
def test_month_boundary_context_only(db, gen, seeded):
    report = _make_report(gen, seeded)
    dates = {d['date'] for d in report['days']}

    # روزهای seed خارج از ماه (context مرزی) نباید در گزارش باشند
    assert date(2024, 3, 19) not in dates
    assert date(2024, 4, 20) not in dates
    assert G_START in dates and G_END in dates

    engine = _engine_days(db, seeded)

    # روز اول ماه باید ورودِ دیروز را به‌عنوان شیفت شب دیده باشد
    assert engine[G_START].main_status == STATUS_NIGHT_SHIFT, \
        'روز اول ماه باید context روز قبل را ببیند'

    # روز آخر ماه فقط ورودِ شب دارد و خروجش فرداست (داخل ماه نیست)
    assert engine[G_END].main_status == STATUS_NIGHT_SHIFT, \
        'روز آخر ماه باید context روز بعد را ببیند'

    # مجموع گزارش = مجموع ساعات روزهای داخل ماه (بدون روزهای context)
    total = sum(d['work_hours'] for d in report['days'])
    assert total == pytest.approx(
        sum(round(float(engine[g].work_hours), 2) for g in _month_days()))


# ---------------------------------------------------------------------------
# ۶) لایه گزارسی: موظفی/اضافه‌کار/خلاصه همچنان در Policy/Report است
# ---------------------------------------------------------------------------
def test_policy_stays_in_report_layer(gen, seeded):
    report = _make_report(gen, seeded)

    assert 'summary' in report and 'days' in report
    for day in report['days']:
        # ساختار گزارش تغییری نکرده
        for key in ('person_status', 'person_status_name', 'overtime',
                    'morning_hours', 'evening_hours', 'night_hours',
                    'has_duty', 'daily_duty', 'is_friday', 'is_holiday'):
            assert key in day, f'کلید {day["date"]}.{key} حذف شده'
        # تفکیک shift از time_calculator می‌آید، نه از موتور مرکزی؛
        # بدون تردد باید صفر باشد.
        breakdown = (day['morning_hours'] + day['evening_hours']
                     + day['night_hours'])
        assert breakdown >= 0.0, f'breakdown {day["date"]}'
        if not day['work_hours']:
            assert breakdown == 0.0, f'بدون کارکرد، تفکیک هم باید صفر باشد: {day["date"]}'
