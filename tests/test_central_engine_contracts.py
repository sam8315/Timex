"""
Phase 8 — قراردادهای سخت‌گیرانه‌ی Central Attendance Engine.

تست‌های موجود (`tests/test_attendance_calculator.py`) رفتار روزانه را خوب
پوشش می‌دهند. این فایل شکاف‌های قراردادی Phase 8 را قفل می‌کند:

  8.7  Night Shift   → سه state + درب‌های ضمنی 00:00:00 / 23:59:59
  8.8  Pairs         → sum(pair.hours) == work_hours در هر وضعیت
  8.9  Month Boundary→ context حاضر، ولی دامنه‌ی ماه بسته است
  8.10 Raw Precision → ثانیه‌ی خام حفظ می‌شود، نه گرد شده

هیچ business rule جدیدی اینجا اضافه نمی‌شود؛ فقط رفتار موجود قفل می‌شود.
"""
from datetime import date, datetime, timedelta

import pytest

from core.attendance_calculator import (
    STATUS_COMPLETE,
    STATUS_NIGHT_SHIFT,
    compute_day_attendance,
)

# ---------------------------------------------------------------------------
# کمک‌کننده‌ها
# ---------------------------------------------------------------------------


class Rec:
    """Minimal punch record — engine فقط .timestamp / .punch را می‌خواند."""

    def __init__(self, ts, punch):
        self.timestamp = ts
        self.punch = punch


def punch(day, h, m=0, s=0, is_enter=True):
    return Rec(datetime(day.year, day.month, day.day, h, m, s),
               0 if is_enter else 1)


def day_result(day, day_records, prev=(), next_=(), **kw):
    return compute_day_attendance(
        day=day,
        day_records=list(day_records),
        prev_day_records=list(prev),
        next_day_records=list(next_),
        **kw
    )


# ماه مرزی: 2024-03-31 آخرین روز مارس، 2024-04-01 اولین آوریل
MONTH_END = date(2024, 3, 31)
NEXT_MONTH_START = date(2024, 4, 1)
DAY_BEFORE_MONTH = date(2024, 2, 29)


# ============================================================
# 8.7 — قرارداد شیفت شب: سه state
# ============================================================
def test_night_state1_first_exit_before_first_enter():
    """
    state 1: اولین خروج زودتر از اولین ورود در همان روز.

    قرارداد دقیق: `first_enter` / `last_exit` همیشه punch واقعی هستند؛
    درب‌های ضمنی ۰۰:۰۰:۰۰ و ۲۳:۵۹:۵۹ در `pairs` ثبت می‌شوند.
    """
    day = date(2024, 5, 15)
    records = [punch(day, 6, 0, 0, is_enter=False),   # خروج صبحِ شیفت شب
               punch(day, 22, 0, 0, is_enter=True)]   # ورود شب

    result = day_result(day, records)

    assert result.is_night_shift is True
    assert result.main_status == STATUS_NIGHT_SHIFT

    # punch واقعی (نه ضمنی)
    assert result.first_enter == datetime(2024, 5, 15, 22, 0, 0)
    assert result.last_exit == datetime(2024, 5, 15, 6, 0, 0)

    # دو pair: ۰۰:۰۰→۰۶:۰۰ و ۲۲:۰۰→۲۳:۵۹:۵۹
    assert len(result.pairs) == 2
    assert result.pairs[0]['enter'] == datetime(2024, 5, 15, 0, 0, 0)
    assert result.pairs[0]['exit'] == datetime(2024, 5, 15, 6, 0, 0)
    assert result.pairs[1]['enter'] == datetime(2024, 5, 15, 22, 0, 0)
    assert result.pairs[1]['exit'] == datetime(2024, 5, 15, 23, 59, 59)

    assert result.work_hours == pytest.approx(6.0 + 7199 / 3600.0)


def test_night_state2_enters_gt_exits_and_next_day_first_punch_is_exit():
    """state 2: enters > exits و اولین punch روز بعد خروج است."""
    day = date(2024, 5, 15)
    nxt = day + timedelta(days=1)
    records = [punch(day, 22, 0, 0, is_enter=True)]
    next_records = [punch(nxt, 6, 0, 0, is_enter=False)]

    result = day_result(day, records, next_=next_records)

    assert result.is_night_shift is True
    assert result.main_status == STATUS_NIGHT_SHIFT
    # درب ضمنی: 23:59:59
    assert result.first_enter == datetime(2024, 5, 15, 22, 0, 0)
    assert result.last_exit == datetime(2024, 5, 15, 23, 59, 59)
    assert result.work_hours == pytest.approx(7199 / 3600.0)


def test_night_state3_exits_gt_enters_and_prev_day_last_punch_is_enter():
    """state 3: exits > enters و آخرین punch روز قبل ورود است."""
    day = date(2024, 5, 15)
    prev = day - timedelta(days=1)
    prev_records = [punch(prev, 22, 0, 0, is_enter=True)]
    records = [punch(day, 6, 0, 0, is_enter=False)]

    result = day_result(day, records, prev=prev_records)

    assert result.is_night_shift is True
    assert result.main_status == STATUS_NIGHT_SHIFT
    # درب ضمنی: 00:00:00
    assert result.first_enter == datetime(2024, 5, 15, 0, 0, 0)
    assert result.last_exit == datetime(2024, 5, 15, 6, 0, 0)
    assert result.work_hours == pytest.approx(6.0)


def test_night_state3_requires_prev_day_LAST_punch_to_be_enter():
    """
    نگهبند: اگر آخرین punch روز قبل «خروج» باشد، نباید شیفت شب شود.
    (همان قاعده‌ای که موتور دومِ قدیمی را غلط از دست می‌داد.)
    """
    day = date(2024, 5, 15)
    prev = day - timedelta(days=1)
    prev_records = [punch(prev, 8, 0, 0, is_enter=True),
                    punch(prev, 17, 0, 0, is_enter=False)]
    records = [punch(day, 6, 0, 0, is_enter=False)]

    result = day_result(day, records, prev=prev_records)

    assert result.is_night_shift is False
    assert result.main_status != STATUS_NIGHT_SHIFT
    assert result.work_hours == 0.0


def test_night_shift_implicit_bounds_are_exact():
    """درب‌های ضمنی دقیقاً 00:00:00 و 23:59:59 هستند (بدون round)."""
    day = date(2024, 5, 15)
    nxt = day + timedelta(days=1)

    state2 = day_result(day, [punch(day, 22, 0, 0)],
                        next_=[punch(nxt, 6, 0, 0, is_enter=False)])
    assert state2.last_exit.time() == datetime(2024, 1, 1, 23, 59, 59).time()

    state3 = day_result(day, [punch(day, 6, 0, 0, is_enter=False)],
                        prev=[punch(day - timedelta(days=1), 22, 0, 0)])
    assert state3.first_enter.time() == datetime(2024, 1, 1, 0, 0, 0).time()


def test_implicit_bounds_only_when_one_side_is_missing():
    """
    قاعده‌ی دقیق درب‌های ضمنی:

      · اگر هر دو punch واقعی موجود باشند → هر دو واقعی می‌مانند
        و درب ضمنی فقط داخل `pairs` دیده می‌شود (state 1).
      · اگر یکی از دو punch واقعی غایب باشد → همان یکی ضمنی
        پر می‌شود (۰۰:۰۰:۰۰ یا ۲۳:۵۹:۵۹) (state 2 و 3).

    این رفتار نباید تغییر کند؛ مصرف‌کننده‌ها روی آن حساب می‌کنند.
    """
    day = date(2024, 5, 15)
    nxt = day + timedelta(days=1)
    prev = day - timedelta(days=1)

    # هر دو واقعی (state 1) → واقعی می‌مانند
    both = day_result(day, [punch(day, 6, 0, 0, is_enter=False),
                            punch(day, 22, 0, 0, is_enter=True)])
    assert both.first_enter == datetime(2024, 5, 15, 22, 0, 0)
    assert both.last_exit == datetime(2024, 5, 15, 6, 0, 0)

    # فقط ورود واقعی (state 2) → خروج ضمنی
    only_enter = day_result(day, [punch(day, 22, 0, 0)],
                            next_=[punch(nxt, 6, 0, 0, is_enter=False)])
    assert only_enter.first_enter == datetime(2024, 5, 15, 22, 0, 0)
    assert only_enter.last_exit == datetime(2024, 5, 15, 23, 59, 59)

    # فقط خروج واقعی (state 3) → ورود ضمنی
    only_exit = day_result(day, [punch(day, 6, 0, 0, is_enter=False)],
                           prev=[punch(prev, 22, 0, 0, is_enter=True)])
    assert only_exit.first_enter == datetime(2024, 5, 15, 0, 0, 0)
    assert only_exit.last_exit == datetime(2024, 5, 15, 6, 0, 0)


def test_non_night_day_never_gets_implicit_bounds():
    """روز عادی نباید هیچ درب ضمنی بگیرد (نه ۰۰:۰۰:۰۰، نه ۲۳:۵۹:۵۹)."""
    day = date(2024, 5, 15)
    missing_exit = day_result(day, [punch(day, 8, 0, 0)])

    assert missing_exit.is_night_shift is False
    assert missing_exit.first_enter == datetime(2024, 5, 15, 8, 0, 0)
    assert missing_exit.last_exit is None
    assert missing_exit.work_hours == 0.0

    missing_enter = day_result(day, [punch(day, 17, 0, 0, is_enter=False)])
    assert missing_enter.is_night_shift is False
    assert missing_enter.first_enter is None
    assert missing_enter.last_exit == datetime(2024, 5, 15, 17, 0, 0)
    assert missing_enter.work_hours == 0.0


# ============================================================
# 8.8 — قرارداد pairs
# ============================================================
@pytest.mark.parametrize(
    'label, build',
    [
        ('normal', lambda d, n: (
            [punch(d, 8), punch(d, 12, is_enter=False),
             punch(d, 13), punch(d, 17, is_enter=False)], [], [])),
        ('multiple-intervals', lambda d, n: (
            [punch(d, 6), punch(d, 7), punch(d, 8), punch(d, 9, is_enter=False),
             punch(d, 10), punch(d, 11, is_enter=False),
             punch(d, 12), punch(d, 13, is_enter=False)], [], [])),
        ('missing-exit', lambda d, n: ([punch(d, 8)], [], [])),
        ('missing-enter', lambda d, n: (
            [punch(d, 17, is_enter=False)], [], [])),
        ('imbalance', lambda d, n: (
            [punch(d, 8), punch(d, 12, is_enter=False), punch(d, 13)], [], [])),
        ('no-attendance', lambda d, n: ([], [], [])),
        ('night-state2', lambda d, n: (
            [punch(d, 22)], [], [punch(n, 6, is_enter=False)])),
        ('night-state3', lambda d, n: (
            [punch(d, 6, is_enter=False)], [punch(d - timedelta(days=1), 22)], [])),
    ]
)
def test_pairs_sum_equals_work_hours(label, build):
    """قرارداد موتور: sum(pair['hours']) == work_hours — همیشه."""
    day = date(2024, 5, 15)
    nxt = day + timedelta(days=1)
    day_records, prev_records, next_records = build(day, nxt)

    result = day_result(day, day_records, prev=prev_records, next_=next_records)

    total = sum(p['hours'] for p in result.pairs)
    assert total == pytest.approx(result.work_hours), label
    assert result.work_hours == pytest.approx(total), label


def test_pairs_never_rounded_but_work_hours_matches():
    """pair hours خام‌اند؛ اگر روز گرد شود pairs نباید گرد شوند."""
    day = date(2024, 5, 15)
    result = day_result(day, [punch(day, 8, 0, 0), punch(day, 8, 0, 30, is_enter=False)])

    assert len(result.pairs) == 1
    # ۳۰ ثانیه = 30/3600 ساعت، نه 0.01
    assert result.pairs[0]['hours'] == pytest.approx(30 / 3600.0)
    assert result.work_hours == pytest.approx(30 / 3600.0)


# ============================================================
# 8.10 — دقت خام
# ============================================================
@pytest.mark.parametrize('seconds', [1, 7, 30, 59, 61, 90, 3599])
def test_raw_precision_is_never_rounded_to_two_decimals(seconds):
    """موتور ثانیه‌ی خام را نگه می‌دارد؛ گرد کردن وظیفه‌ی consumer است."""
    day = date(2024, 5, 15)
    records = [punch(day, 8, 0, 0),
               punch(day, 8, 0, 0, is_enter=False)].copy()
    # ساخت فاصله‌ی دقیق «seconds» ثانیه
    start = datetime(2024, 5, 15, 8, 0, 0)
    records = [Rec(start, 0), Rec(start + timedelta(seconds=seconds), 1)]

    result = day_result(day, records)

    expected = seconds / 3600.0
    assert result.work_hours == pytest.approx(expected, abs=0.0)
    # مقدار خام ≠ مقدار گرد‌شده، مگر وقتی تصادفاً برابر باشند
    if round(expected, 2) != expected:
        assert result.work_hours != round(expected, 2), seconds


def test_raw_precision_30_seconds_is_not_zero_point_zero_one():
    """مثال صریح صورت مسئله: ۳۰ ثانیه نباید 0.01 شود."""
    day = date(2024, 5, 15)
    start = datetime(2024, 5, 15, 8, 0, 0)
    result = day_result(day, [Rec(start, 0),
                              Rec(start + timedelta(seconds=30), 1)])

    assert result.work_hours == pytest.approx(0.008333333333333333)
    assert result.work_hours != 0.01
    assert round(result.work_hours, 6) == 0.008333


def test_raw_precision_accumulates_across_many_intervals():
    """جمع pairها هم دقت خام را نگه می‌دارد (نه sum از مقادیر گردشده)."""
    day = date(2024, 5, 15)
    base = datetime(2024, 5, 15, 8, 0, 0)
    records = []
    for i in range(4):
        s = base + timedelta(minutes=30 * i, seconds=30)
        e = s + timedelta(seconds=30)
        records.append(Rec(s, 0))
        records.append(Rec(e, 1))

    result = day_result(day, records)

    assert result.work_hours == pytest.approx(4 * 30 / 3600.0)
    assert len(result.pairs) == 4
    assert all(p['hours'] == pytest.approx(30 / 3600.0) for p in result.pairs)


# ============================================================
# 8.9 — قرارداد مرز ماه
# ============================================================
def test_scenario_a_last_day_enter_next_month_exit_context_present():
    """
    آخر ماه ۲۲:۰۰ ENTER / اول ماه بعد ۰۶:۰۰ EXIT.
    روز آخر باید context روز بعد را ببیند و کارکردش تا ۲۳:۵۹:۵۹ باشد.
    """
    next_records = [punch(NEXT_MONTH_START, 6, 0, 0, is_enter=False)]

    last_day = day_result(MONTH_END, [punch(MONTH_END, 22, 0, 0)],
                          next_=next_records)

    assert last_day.is_night_shift is True
    assert last_day.main_status == STATUS_NIGHT_SHIFT
    assert last_day.last_exit == datetime(2024, 3, 31, 23, 59, 59)
    assert last_day.work_hours == pytest.approx(7199 / 3600.0)


def test_scenario_b_day_before_month_enter_first_day_exit_context_present():
    """
    روز قبل ماه ۲۲:۰۰ ENTER / روز اول ماه ۰۶:۰۰ EXIT.
    روز اول باید context روز قبل را ببیند.
    """
    prev_records = [punch(DAY_BEFORE_MONTH, 22, 0, 0, is_enter=True)]

    first_day = day_result(NEXT_MONTH_START,
                           [punch(NEXT_MONTH_START, 6, 0, 0, is_enter=False)],
                           prev=prev_records)

    assert first_day.is_night_shift is True
    assert first_day.main_status == STATUS_NIGHT_SHIFT
    assert first_day.first_enter == datetime(2024, 4, 1, 0, 0, 0)
    assert first_day.work_hours == pytest.approx(6.0)


def test_scenario_b_prior_day_still_owns_its_own_evening():
    """
    نگهبند: context یک‌طرفه نیست — روز قبل هم باید روز اول را ببیند و
    کارکرد خودش را (تا ۲۳:۵۹:۵۹) نگه دارد.
    """
    first_day_records = [punch(NEXT_MONTH_START, 6, 0, 0, is_enter=False)]

    prior = day_result(DAY_BEFORE_MONTH, [punch(DAY_BEFORE_MONTH, 22, 0, 0)],
                       next_=first_day_records)

    assert prior.is_night_shift is True
    assert prior.work_hours == pytest.approx(7199 / 3600.0)


def test_month_scope_excludes_out_of_month_days_from_totals():
    """
    قرارداد دامنه: موتور per-day است، پس «مجموع» را مصرف‌کننده می‌سازد.
    شبیه‌سازی مجموعه‌ی روزهای ماه فقط، و اثبات اینکه روزهای context
    وقتی در آن مجموع نیستند، چیزی به مجموع اضافه نمی‌کنند.
    """
    prev_records = [punch(DAY_BEFORE_MONTH, 22, 0, 0, is_enter=True)]
    first_records = [punch(NEXT_MONTH_START, 6, 0, 0, is_enter=False)]

    # فقط روزهای داخل ماه در مجموع
    month_days = []
    current = NEXT_MONTH_START
    while current.month == NEXT_MONTH_START.month:
        records = first_records if current == NEXT_MONTH_START else []
        month_days.append(day_result(current, records,
                                      prev=prev_records if current == NEXT_MONTH_START else []))
        current += timedelta(days=1)

    month_total = sum(r.work_hours for r in month_days)
    assert month_total == pytest.approx(6.0)

    # روز قبلِ ماه در مجموع نیست، حتی با اینکه context هست
    prior = day_result(DAY_BEFORE_MONTH, [punch(DAY_BEFORE_MONTH, 22, 0, 0)],
                       next_=first_records)
    assert prior.work_hours > 0
    assert prior not in month_days
    assert month_total == pytest.approx(6.0), \
        'روز context نباید در مجموع ماه بیاید'


def test_out_of_month_day_is_still_computable_but_is_consumers_choice():
    """
    موتور روزِ خارج از ماه را رد نمی‌کند (per-day است)؛ انتخابِ دامنه
    کاملاً در اختیار مصرف‌کننده است — و قراردادش این است که context
    را ببیند ولی در ماه نشمرده شود.
    """
    first_records = [punch(NEXT_MONTH_START, 6, 0, 0, is_enter=False)]
    prior = day_result(DAY_BEFORE_MONTH, [punch(DAY_BEFORE_MONTH, 22, 0, 0)],
                       next_=first_records)
    # روز قبل ماه کاملاً قابل محاسبه است
    assert prior.work_hours > 0
    assert prior.day == DAY_BEFORE_MONTH
