"""
تست‌های Central Attendance Calculation Engine (core/attendance_calculator.py)

این تست‌ها رفتار «مرجع» (منطق استخراج‌شده از web/routes/attendance.py) را ثابت
می‌کنند: status / night shift / warnings / work hours / first enter / last exit /
pairs و اینکه منبع واحد حقیقت (ONE SOURCE OF TRUTH) بودن حفظ شده است.
"""
from datetime import date, datetime, timedelta

import pytest

from core.attendance_calculator import (
    STATUS_COMPLETE,
    STATUS_IMBALANCE,
    STATUS_MISSING_ENTER,
    STATUS_MISSING_EXIT,
    STATUS_NIGHT_SHIFT,
    STATUS_NO_ATTENDANCE,
    STATUS_SEQUENCE_ERROR,
    WARN_ABNORMAL_GAP,
    WARN_ABNORMAL_TIME,
    WARN_DUPLICATE,
    WARN_FRIDAY_WORK,
    WARN_HOLIDAY_WORK,
    WARN_TOO_MANY,
    DayAttendanceResult,
    WorkScheduleContext,
    analyze_day_status,
    calculate_work_hours,
    compute_day_attendance,
)

DAY = date(2024, 5, 15)          # Wednesday
NEXT_DAY = DAY + timedelta(days=1)
PREV_DAY = DAY - timedelta(days=1)


class Rec:
    """Minimal punch record — only .timestamp / .punch are used by the engine."""

    def __init__(self, ts, punch):
        self.timestamp = ts
        self.punch = punch


def dt(h, m=0, s=0, d=None):
    d = d or DAY
    return datetime(d.year, d.month, d.day, h, m, s)


def status(day_records, prev=None, next_=None, is_friday=False, holiday_title=None):
    return analyze_day_status(
        day=DAY,
        day_records=day_records,
        prev_day_records=prev or [],
        next_day_records=next_ or [],
        is_friday=is_friday,
        holiday_title=holiday_title,
    )


def work_hours(day_records, is_night_shift):
    return calculate_work_hours(day_records, is_night_shift)


def warn_codes(status_info):
    return [w['code'] for w in status_info['warnings']]


def sec(seconds):
    """seconds → hours"""
    return seconds / 3600.0


# ============================================
# 1. بدون تردد
# ============================================
def test_no_attendance():
    s = status([])
    assert s['main_status'] == STATUS_NO_ATTENDANCE
    assert s['main_label'] == '⚪ بدون تردد'
    assert s['main_color'] == 'secondary'
    assert s['warnings'] == []
    assert work_hours([], False) == (0, None, None)


# ============================================
# 2. ورود/خروج عادی
# ============================================
def test_normal_enter_exit():
    recs = [Rec(dt(8), 0), Rec(dt(17), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_COMPLETE
    assert s['main_label'] == '✅ کامل'
    assert s['warnings'] == []
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == pytest.approx(9.0)
    assert first_enter == dt(8)
    assert last_exit == dt(17)


# ============================================
# 3. چند ورود/خروج
# ============================================
def test_multiple_enter_exit():
    recs = [Rec(dt(8), 0), Rec(dt(12), 1), Rec(dt(13), 0), Rec(dt(17), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_COMPLETE
    assert s['warnings'] == []
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == pytest.approx(8.0)
    assert first_enter == dt(8)
    assert last_exit == dt(17)


# ============================================
# 4. ورود بدون خروج
# ============================================
def test_missing_exit():
    recs = [Rec(dt(8), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_MISSING_EXIT
    assert s['main_label'] == '⬅️ ورود بدون خروج'
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == 0.0          # بازه باز در روز عادی شمرده نمی‌شود
    assert first_enter == dt(8)
    assert last_exit is None


# ============================================
# 5. خروج بدون ورود
# ============================================
def test_missing_enter():
    recs = [Rec(dt(17), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_MISSING_ENTER
    assert s['main_label'] == '➡️ خروج بدون ورود'
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == 0.0
    assert first_enter is None
    assert last_exit == dt(17)


# ============================================
# 6. خطای ترتیب
# ============================================
def test_sequence_error_two_enters():
    recs = [Rec(dt(8), 0), Rec(dt(9), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_SEQUENCE_ERROR
    assert s['main_label'] == '❌ دو ورود پشت سر هم'
    assert s['main_color'] == 'danger'
    # ورود دوم نادیده گرفته می‌شود و بازه بازِ بدون خروج، صفر است
    wh, _, _ = work_hours(recs, False)
    assert wh == 0.0


def test_sequence_error_two_exits():
    recs = [Rec(dt(9), 1), Rec(dt(17), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_SEQUENCE_ERROR
    assert s['main_label'] == '❌ دو خروج پشت سر هم'


def test_sequence_error_vs_night_shift_priority():
    # خروج قبل از ورود → اول night_shift (اولویت بالاتر) سپس sequence_error
    recs = [Rec(dt(9), 1), Rec(dt(17), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_NIGHT_SHIFT


# ============================================
# 7. عدم تعادل (punch خارج از 0/1)
# ============================================
def test_imbalance():
    recs = [Rec(dt(8), 2)]
    s = status(recs)
    assert s['main_status'] == STATUS_IMBALANCE
    assert s['main_label'] == '⚠️ عدم تعادل'
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == 0.0
    assert first_enter is None and last_exit is None


# ============================================
# 8. شیفت شب — ساختار هم‌روز (خروج قبل از ورود)
# ============================================
def test_night_shift_same_day():
    recs = [Rec(dt(6), 1), Rec(dt(22), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_NIGHT_SHIFT
    assert s['main_label'] == '🌙 شیفت شب'
    wh, first_enter, last_exit = work_hours(recs, True)
    # ورود ضمنی 00:00 → 06:00  +  22:00 → خروج ضمنی 23:59:59
    assert wh == pytest.approx(sec(6 * 3600 + 7199))
    assert first_enter == dt(22)
    assert last_exit == dt(6)     # رفتار قبلی: هر دو موجود → بدون جایگزینی


# ============================================
# 9. شیفت شب — خروج روز بعد
# ============================================
def test_night_shift_next_day_exit():
    recs = [Rec(dt(22), 0)]
    nxt = [Rec(dt(6, 0, 0, NEXT_DAY), 1)]
    s = status(recs, next_=nxt)
    assert s['main_status'] == STATUS_NIGHT_SHIFT
    wh, first_enter, last_exit = work_hours(recs, True)
    assert wh == pytest.approx(sec(7199))
    assert first_enter == dt(22)
    assert last_exit == dt(23, 59, 59)     # خروج ضمنی برای نمایش


# ============================================
# 10. شیفت شب — ورود روز قبل
# ============================================
def test_night_shift_previous_day_enter():
    recs = [Rec(dt(6), 1)]
    prev = [Rec(dt(22, 0, 0, PREV_DAY), 0)]
    s = status(recs, prev=prev)
    assert s['main_status'] == STATUS_NIGHT_SHIFT
    wh, first_enter, last_exit = work_hours(recs, True)
    assert wh == pytest.approx(6.0)        # ورود ضمنی 00:00 → 06:00
    assert first_enter == dt(0)            # ورود ضمنی برای نمایش
    assert last_exit == dt(6)


# ============================================
# 11. تردد تکراری (< 2 دقیقه)
# ============================================
def test_duplicate_punches():
    recs = [Rec(dt(8), 0), Rec(dt(8, 0, 30), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_COMPLETE
    assert warn_codes(s) == [WARN_DUPLICATE]
    assert s['warnings'][0]['label'] == '🔁 تردد تکراری'
    wh, _, _ = work_hours(recs, False)
    assert wh == pytest.approx(sec(30))


# ============================================
# 12. فاصله غیرعادی (> 12 ساعت برای یک جفت)
# ============================================
def test_abnormal_gap():
    recs = [Rec(dt(8), 0), Rec(dt(21), 1)]
    s = status(recs)
    assert s['main_status'] == STATUS_COMPLETE
    assert warn_codes(s) == [WARN_ABNORMAL_GAP]
    assert s['warnings'][0]['label'] == '⏱️ فاصله 13.0h (08:00-21:00)'
    wh, _, _ = work_hours(recs, False)
    assert wh == pytest.approx(13.0)


# ============================================
# 13. ساعت غیرعادی
# ============================================
def test_abnormal_time_late_enter():
    recs = [Rec(dt(23), 0), Rec(dt(23, 30), 1)]
    s = status(recs)
    assert warn_codes(s) == [WARN_ABNORMAL_TIME]
    assert s['warnings'][0]['label'] == '🕐 ورود دیروقت'
    wh, _, _ = work_hours(recs, False)
    assert wh == pytest.approx(0.5)


def test_abnormal_time_early_exit():
    recs = [Rec(dt(1), 0), Rec(dt(4), 1)]
    s = status(recs)
    assert warn_codes(s) == [WARN_ABNORMAL_TIME]
    assert s['warnings'][0]['label'] == '🕐 خروج زودهنگام'
    wh, _, _ = work_hours(recs, False)
    assert wh == pytest.approx(3.0)


# ============================================
# 14. بیش از ۶ تردد
# ============================================
def test_too_many_punches():
    recs = [Rec(dt(8), 0), Rec(dt(9), 1), Rec(dt(10), 0), Rec(dt(11), 1),
            Rec(dt(12), 0), Rec(dt(13), 1), Rec(dt(14), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_MISSING_EXIT
    assert warn_codes(s) == [WARN_TOO_MANY]
    assert s['warnings'][0]['label'] == '🔢 7 تردد'
    wh, _, _ = work_hours(recs, False)
    assert wh == pytest.approx(3.0)


# ============================================
# 15. جمعه‌کاری
# ============================================
def test_friday_work():
    recs = [Rec(dt(8), 0), Rec(dt(17), 1)]
    s = status(recs, is_friday=True)
    assert s['is_friday'] is True
    assert s['main_status'] == STATUS_COMPLETE
    assert warn_codes(s) == [WARN_FRIDAY_WORK]
    assert s['warnings'][0]['color'] == 'info'


# ============================================
# 16. تعطیل‌کاری
# ============================================
def test_holiday_work():
    recs = [Rec(dt(8), 0), Rec(dt(17), 1)]
    s = status(recs, holiday_title='عید نوروز')
    assert s['is_holiday'] is True
    assert s['holiday_title'] == 'عید نوروز'
    assert warn_codes(s) == [WARN_HOLIDAY_WORK]
    assert s['warnings'][0]['color'] == 'danger'
    assert s['warnings'][0]['label'] == '🔴 تعطیل‌کاری (عید نوروز)'


# ============================================
# 17. استخراج pairها
# ============================================
def test_pair_extraction_multiple_intervals():
    recs = [Rec(dt(8), 0), Rec(dt(12), 1), Rec(dt(13), 0),
            Rec(dt(17), 1), Rec(dt(18), 0), Rec(dt(20), 1)]
    res = compute_day_attendance(day=DAY, day_records=recs)
    assert res.main_status == STATUS_COMPLETE
    assert res.work_hours == pytest.approx(10.0)
    assert len(res.pairs) == 3
    assert res.pairs[0] == {'enter': dt(8), 'exit': dt(12), 'hours': 4.0}
    assert res.pairs[1] == {'enter': dt(13), 'exit': dt(17), 'hours': 4.0}
    assert res.pairs[2] == {'enter': dt(18), 'exit': dt(20), 'hours': 2.0}
    # pairها باید دقیقاً همان ساعات محاسبه‌شده باشند
    assert sum(p['hours'] for p in res.pairs) == pytest.approx(res.work_hours)


def test_pair_extraction_night_shift_implicit_bounds():
    recs = [Rec(dt(6), 1), Rec(dt(22), 0)]
    res = compute_day_attendance(day=DAY, day_records=recs)
    assert res.is_night_shift is True
    assert len(res.pairs) == 2
    assert res.pairs[0]['enter'] == dt(0)
    assert res.pairs[0]['exit'] == dt(6)
    assert res.pairs[1]['enter'] == dt(22)
    assert res.pairs[1]['exit'] == dt(23, 59, 59)
    assert sum(p['hours'] for p in res.pairs) == pytest.approx(res.work_hours)


def test_pairs_never_change_work_hours():
    """افزودن pairs نباید الگوریتم ساعات کار را تغییر دهد."""
    cases = [
        [Rec(dt(8), 0), Rec(dt(17), 1)],
        [Rec(dt(8), 0)],
        [Rec(dt(17), 1)],
        [Rec(dt(6), 1), Rec(dt(22), 0)],
        [Rec(dt(8), 0), Rec(dt(12), 1), Rec(dt(13), 0), Rec(dt(17), 1)],
    ]
    for recs in cases:
        s = status(recs)
        is_night = s['main_status'] == STATUS_NIGHT_SHIFT
        wh, _, _ = work_hours(recs, is_night)
        res = compute_day_attendance(day=DAY, day_records=recs)
        assert res.work_hours == wh
        assert sum(p['hours'] for p in res.pairs) == pytest.approx(wh)


# ============================================
# 18. رفتار timezone
# ============================================
def test_timezone_aware_records_return_naive_output():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Tehran')
    except Exception:  # pragma: no cover
        pytest.skip('zoneinfo unavailable')
    recs = [Rec(dt(8).replace(tzinfo=tz), 0), Rec(dt(17).replace(tzinfo=tz), 1)]
    wh, first_enter, last_exit = work_hours(recs, False)
    assert wh == pytest.approx(9.0)
    assert first_enter.tzinfo is None      # رفتار قبلی: خروجی naive
    assert last_exit.tzinfo is None
    # pairها نیز از همان مقادیر naive ساخته می‌شوند
    res = compute_day_attendance(day=DAY, day_records=recs)
    assert all(p['enter'].tzinfo is None and p['exit'].tzinfo is None
               for p in res.pairs)
    # خودِ رکورد ورودی نباید تغییر کند
    assert recs[0].timestamp.tzinfo is not None


def test_timezone_aware_night_shift():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('Asia/Tehran')
    except Exception:  # pragma: no cover
        pytest.skip('zoneinfo unavailable')
    recs = [Rec(dt(6).replace(tzinfo=tz), 1), Rec(dt(22).replace(tzinfo=tz), 0)]
    s = status(recs)
    assert s['main_status'] == STATUS_NIGHT_SHIFT
    wh, first_enter, last_exit = work_hours(recs, True)
    assert wh == pytest.approx(sec(6 * 3600 + 7199))
    assert first_enter.tzinfo is None
    assert last_exit.tzinfo is None


# ============================================
# 19. context برنامه کاری (بدون قفل شدن به ساعت ثابت)
# ============================================
def test_schedule_context_does_not_affect_actual_attendance():
    recs = [Rec(dt(8), 0), Rec(dt(17), 1)]

    ctx_short = WorkScheduleContext(effective_work_minutes=390,   # 6:30
                                    schedule_code='GROUP_A')
    ctx_long = WorkScheduleContext(effective_work_minutes=480,    # 8:00
                                   schedule_code='GROUP_B')

    r1 = compute_day_attendance(day=DAY, day_records=recs,
                                schedule_context=ctx_short)
    r2 = compute_day_attendance(day=DAY, day_records=recs,
                                schedule_context=ctx_long)

    # محاسبه actual attendance کاملاً یکسان است (به schedule قفل نشده)
    assert r1.work_hours == r2.work_hours == pytest.approx(9.0)
    assert r1.main_status == r2.main_status == STATUS_COMPLETE
    assert r1.pairs == r2.pairs
    assert r1.first_enter == r2.first_enter
    assert r1.last_exit == r2.last_exit

    # context فقط در خروجی نگه داشته می‌شود
    assert r1.schedule_context.effective_work_minutes == 390
    assert r2.schedule_context.effective_work_minutes == 480
    assert r1.schedule_context is not r2.schedule_context


def test_engine_has_no_hardcoded_duty_hours():
    """هیچ مقدار ثابت موظفی (مثل 7:20) نباید در موتور تردد تعریف شده باشد."""
    import core.attendance_calculator as mod
    import inspect

    forbidden = {'DAILY_DUTY_HOURS', 'REQUIRED_HOURS', 'DUTY_HOURS',
                 'DEFAULT_DUTY_HOURS', 'STANDARD_WORK_HOURS'}
    assert forbidden.isdisjoint(dir(mod))

    source = inspect.getsource(mod)
    assert '7.33' not in source
    assert '7.20' not in source


# ============================================
# API موتور مرکزی / یک منبع حقیقت
# ============================================
def test_compute_day_attendance_result_shape():
    recs = [Rec(dt(22), 0)]
    nxt = [Rec(dt(6, 0, 0, NEXT_DAY), 1)]
    res = compute_day_attendance(
        day=DAY, day_records=recs, prev_day_records=[], next_day_records=nxt,
        is_friday=False, holiday_title=None)
    assert isinstance(res, DayAttendanceResult)
    assert res.day == DAY
    assert res.status == STATUS_NIGHT_SHIFT       # alias
    assert res.is_night_shift is True
    assert res.enter_count == 1
    assert res.exit_count == 0
    assert res.has_sequence_error is False
    assert res.sequence_error_detail == ''
    assert res.warning_codes == [WARN_ABNORMAL_TIME]
    # سازگاری با dict قدیمی analyze_day_status
    legacy = status(recs, next_=nxt)
    assert res.attendance_status_dict == legacy


def test_sequence_info_available_on_full_result():
    recs = [Rec(dt(8), 0), Rec(dt(9), 0)]
    res = compute_day_attendance(day=DAY, day_records=recs)
    assert res.has_sequence_error is True
    assert res.sequence_error_detail == 'دو ورود پشت سر هم'
    # ولی dict عمومی analyze_day_status کلیدهای قبلی را دارد (بدون اضافه شدن)
    assert set(status(recs).keys()) == {
        'main_status', 'main_label', 'main_color', 'warnings',
        'is_friday', 'is_holiday', 'holiday_title',
    }


def test_single_source_of_truth():
    """web.routes.attendance باید همان objectهای core را export کند."""
    import web.routes.attendance as route_mod
    from core import attendance_calculator as core_mod

    assert route_mod.analyze_day_status is core_mod.analyze_day_status
    assert route_mod.calculate_work_hours is core_mod.calculate_work_hours
    for name in ('STATUS_COMPLETE', 'STATUS_NIGHT_SHIFT', 'STATUS_MISSING_EXIT',
                 'STATUS_MISSING_ENTER', 'STATUS_SEQUENCE_ERROR',
                 'STATUS_IMBALANCE', 'STATUS_NO_ATTENDANCE', 'STATUS_LEAVE'):
        assert getattr(route_mod, name) == getattr(core_mod, name)


def test_status_priority_is_preserved():
    """شب > خطای ترتیب > کامل > ناقص‌ها > عدم تعادل"""
    # شب روی خطای ترتیب غالب است
    recs_night_seq = [Rec(dt(6), 1), Rec(dt(7), 1), Rec(dt(22), 0)]
    s = status(recs_night_seq)
    assert s['main_status'] == STATUS_NIGHT_SHIFT

    # خطای ترتیب روی complete/missing غالب است
    assert status([Rec(dt(8), 0), Rec(dt(9), 0)])['main_status'] == \
        STATUS_SEQUENCE_ERROR

    # نبود تردد
    assert status([])['main_status'] == STATUS_NO_ATTENDANCE
