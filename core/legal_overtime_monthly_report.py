"""
گزارش ماهانه اضافه‌کار قانونی — تبصره ۱ ماده ۵۱ قانون کار.

اضافه‌کار پرداختی = max(0, کارکرد هفته − سطل‌های تفکیک‌شده − موظفی هفته)
- کارکرد هفته: همهٔ روزها از جمله جمعه
- موظفی هفته: جمع موظفی روزها؛ اینکه بدون تردد/غیبت/مرخصی/HL/مأموریت/HM/
  استراحت موظفی را کم کنند از سیاست گزارش (`duty_reduce_*`) می‌آید.
- کارکرد جمعه/تعطیل/استراحت/مرخصی همیشه در سطل جدا است و از مبنای
  اضافه‌کار هفتگی کسر می‌شود.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Dict, List, Optional

from web.services.report_policy_service import (
    DEFICIT_METHOD_LEGACY,
    LEGAL_OT_DEFAULTS,
    LEGAL_OVERTIME_MONTHLY,
    apply_overrides,
    month_end,
    resolve_report_policy,
)
from core.detailed_monthly_report_v2 import (
    DetailedMonthlyReportGeneratorV2,
    _hours_to_minutes,
    _minutes_to_hours,
    punch_grace_totals,
)

WEEKLY_REQUIRED_HOURS = 44.0
# Fallback وقتی daily_duty روی روز نباشد (تست‌های واحد / داده ناقص)
WORKING_DAY_DUTY_MINUTES = 440
# شروع پیش‌فرض موظفی وقتی Policy ساعت شروع ندارد
DEFAULT_DUTY_START = time(7, 0)
# ضرایب پرداختی (نمایش در گزارش)
OVERTIME_COEFFICIENT = 1.4
FRIDAY_WORK_COEFFICIENT = 1.96
HOLIDAY_WORK_COEFFICIENT = 1.4


def _is_friday_work_day(day: Dict) -> bool:
    return bool(day.get('is_friday') and day.get('person_status') == 'P')


def _is_holiday_work_day(day: Dict) -> bool:
    """تعطیل رسمی غیرجمعه با حضور."""
    return bool(
        day.get('is_holiday')
        and not day.get('is_friday')
        and day.get('person_status') == 'P'
    )


_LEAVE_STATUSES = ('L', 'SL')
_NON_WORKING_PERSON_STATUSES = ('L', 'SL', 'R', 'M')


def _is_working_day_type(day: Dict) -> bool:
    """ستون وضعیت روز «کاری» و فرد مرخصی/استراحت/مأموریت نباشد."""
    return (
        not day.get('is_day_off')
        and day.get('person_status') not in _NON_WORKING_PERSON_STATUSES
    )


def is_personal_working_day(day: Dict, settings: Optional[Dict] = None) -> bool:
    """روز کاری برای کسر کار: با مبنای «کل کارکرد» همهٔ روزها؛ با مبنای «کارکرد روز کاری»
    فقط روزهای کاری فرد."""
    settings = settings or LEGAL_OT_DEFAULTS
    if not settings['deficit_separate_non_working']:
        return True
    return _is_working_day_type(day)
_STATUS_DUTY_KEY = {
    'L': 'duty_reduce_leave',
    'SL': 'duty_reduce_leave',
    'M': 'duty_reduce_mission',
    'R': 'duty_reduce_rest',
    'N': 'duty_reduce_no_punch',
    'A': 'duty_reduce_absent',
}
WORK_BUCKETS = ('friday', 'holiday', 'rest', 'leave')


def _resolve_settings(policy=None) -> Dict:
    return {
        **LEGAL_OT_DEFAULTS,
        **dict(getattr(policy, 'settings', policy) or {}),
    }


def day_duty_minutes(day: Dict, settings: Optional[Dict] = None) -> int:
    """موظفی روز برای محاسبهٔ هفتگی طبق سیاست گزارش.

    مبنا `base_duty_minutes` (موظفی Policy پیش از کسرها) است. روزهای قدیمی
    بدون این فیلد از `daily_duty` (که کسرها از قبل در آن اعمال شده) استفاده می‌کنند.
    """
    settings = settings or LEGAL_OT_DEFAULTS
    key = _STATUS_DUTY_KEY.get(day.get('person_status'))
    if key and settings[key]:
        return 0
    base = day.get('base_duty_minutes')
    if base is None:
        return _hours_to_minutes(day.get('daily_duty') or 0)
    minutes = int(base)
    if settings['duty_reduce_hourly_leave']:
        minutes -= int(day.get('hourly_leave_minutes') or 0)
    if settings['duty_reduce_hourly_mission']:
        minutes -= int(day.get('hourly_mission_minutes') or 0)
    return max(0, minutes)


_UNEXCUSED_DUTY_KEYS = ('duty_reduce_no_punch', 'duty_reduce_absent')


def deficit_duty_minutes(day: Dict, settings: Optional[Dict] = None) -> int:
    """موظفی روز برای کسر کار: مثل `day_duty_minutes`، ولی بدون تردد/غیبت
    موظفی را حذف نمی‌کند (آن کسرها فقط مبنای اضافه‌کار را تنظیم می‌کنند)."""
    settings = settings or LEGAL_OT_DEFAULTS
    return day_duty_minutes(
        day, {**settings, **{k: False for k in _UNEXCUSED_DUTY_KEYS}},
    )


def work_bucket(day: Dict, settings: Optional[Dict] = None) -> Optional[str]:
    """سطل جدای کارکرد روز؛ None = جزو مبنای اضافه‌کار هفته."""
    status = day.get('person_status')
    if _is_friday_work_day(day):
        return 'friday'
    if _is_holiday_work_day(day):
        return 'holiday'
    if status == 'R':
        return 'rest'
    if status in _LEAVE_STATUSES:
        return 'leave'
    return None


def _bucket_minutes(days: List[Dict], settings: Dict) -> Dict[str, int]:
    totals = {b: 0 for b in WORK_BUCKETS}
    for d in days:
        bucket = work_bucket(d, settings)
        if bucket:
            totals[bucket] += _hours_to_minutes(d.get('work_hours') or 0)
    return totals


def _bucket_days(days: List[Dict], settings: Dict, bucket: str) -> List[Dict]:
    """روزهای سطل؛ جمعه/تعطیل‌کاری با حضور (P) شمرده می‌شوند، استراحت/مرخصی
    فقط وقتی کارکرد داشته باشند."""
    need_work = bucket in ('rest', 'leave')
    return [
        d for d in days
        if work_bucket(d, settings) == bucket
        and (not need_work or _hours_to_minutes(d.get('work_hours') or 0) > 0)
    ]


def count_duty_bearing_days(
    week_days: List[Dict], settings: Optional[Dict] = None,
) -> int:
    """روزهایی که پس از کسرهای سیاست هنوز موظفی دارند."""
    return sum(1 for d in week_days if day_duty_minutes(d, settings) > 0)


def weekly_required_minutes(
    week_days: List[Dict], settings: Optional[Dict] = None,
) -> int:
    """موظفی هفتگی = جمع موظفی روزها طبق سیاست گزارش (`day_duty_minutes`)."""
    total = sum(day_duty_minutes(d, settings) for d in week_days)
    if total > 0 or any('base_duty_minutes' in d for d in week_days):
        return total

    # Fallback نادر: اگر هیچ daily_duty ست نشده، روزهای غیرجمعهٔ بدون وضعیت معاف
    n = 0
    for d in week_days:
        if d.get('is_friday') or d.get('is_holiday') or d.get('is_day_off'):
            continue
        if d.get('person_status') in ('L', 'R', 'M', 'H', 'N'):
            continue
        n += 1
    return n * WORKING_DAY_DUTY_MINUTES


# نام قدیمی برای سازگاری تست/فراخوانی
def proportional_weekly_required_minutes(
    week_days: List[Dict], settings: Optional[Dict] = None,
) -> int:
    return weekly_required_minutes(week_days, settings)


def week_start_saturday(d):
    current = d
    while current.weekday() != 5:
        current -= timedelta(days=1)
    return current


def _fmt_hhmm(hours: float) -> str:
    total_minutes = _hours_to_minutes(hours)
    sign = '-' if total_minutes < 0 else ''
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _week_metrics(
    week_days: List[Dict],
    settings: Optional[Dict] = None,
    ref: Optional[datetime] = None,
) -> Dict:
    """تفاضل هفته = کارکرد − سطل‌های تفکیک‌شده − Σموظفی.

    اضافه‌کار = max(0, تفاضل). کسر کار = max(0, موظفی سپری‌شده − کارکرد قابل
    احتساب) + تأخیر/تعجیل مازاد؛ کسر کار ماهانه جمع همین عدد هفته‌هاست
    (پیش از تهاتر با اضافه‌کار در `build_legal_ot_summary`).
    با ref، موظفی روزهای آینده/بخش سپری‌نشدهٔ روز جاری در کسر کار نمی‌آید.
    """
    settings = settings or LEGAL_OT_DEFAULTS
    n_calendar = len(week_days)
    n_duty_days = count_duty_bearing_days(week_days, settings)
    threshold_m = weekly_required_minutes(week_days, settings)

    work_total_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0) for d in week_days
    )
    buckets = _bucket_minutes(week_days, settings)
    # مبنای اضافه‌کار عادی: بدون سطل‌های جدا
    work_base_m = work_total_m - sum(buckets.values())

    # کسر کار: کارکرد روز کاری فرد، و کارکرد روز غیرکاری که هنوز در مبنای اضافه‌کار است
    deficit_work_m = nonworking_in_base_m = 0
    for d in week_days:
        work_m = _hours_to_minutes(d.get('work_hours') or 0)
        if is_personal_working_day(d, settings):
            deficit_work_m += work_m
        elif work_bucket(d, settings) is None:
            nonworking_in_base_m += work_m

    if threshold_m > 0 and work_base_m > threshold_m:
        week_ot_m = work_base_m - threshold_m
    else:
        week_ot_m = 0

    # کسر کار هفته = کمبود کارکرد قابل احتساب نسبت به موظفی سپری‌شده
    # + تأخیر/تعجیلی که در کمبود کارکرد همان روز نیامده.
    deficit_duty_m = unelapsed_m = 0
    violation_m = 0
    for d in week_days:
        duty_day_m = deficit_duty_minutes(d, settings)
        deficit_duty_m += duty_day_m
        day_unelapsed_m = (
            _unelapsed_minutes(duty_day_m, d, ref) if ref is not None else 0
        )
        unelapsed_m += day_unelapsed_m
        v = int(d.get('late_violation_minutes') or 0) + int(
            d.get('early_leave_violation_minutes') or 0
        )
        if v > 0:
            day_short_m = max(
                0,
                duty_day_m - day_unelapsed_m
                - _hours_to_minutes(d.get('work_hours') or 0),
            )
            violation_m += max(0, v - day_short_m)
    elapsed_duty_m = deficit_duty_m - unelapsed_m

    # ساعتی که اضافه‌کار شده کسر کار همان هفته را پوشش نمی‌دهد؛
    # اضافه‌کار اول از کارکرد روز غیرکاریِ داخل مبنا برداشته می‌شود
    credit_m = deficit_work_m - max(0, week_ot_m - nonworking_in_base_m)
    shortfall_m = max(0, elapsed_duty_m - credit_m)
    week_deficit_m = shortfall_m + violation_m

    duty_h = _minutes_to_hours(threshold_m)
    work_total_h = _minutes_to_hours(work_total_m)
    work_base_h = _minutes_to_hours(work_base_m)
    weekly_h = _minutes_to_hours(week_ot_m)

    if n_duty_days > 0 and threshold_m == n_duty_days * WORKING_DAY_DUTY_MINUTES:
        if n_duty_days >= 6:
            duty_note = f'{n_duty_days}×۷:۲۰ = ۴۴'
        else:
            duty_note = f'{n_duty_days}×۷:۲۰'
    else:
        duty_note = f'Σ موظفی ({n_duty_days} روز)'

    parts = [_fmt_hhmm(work_total_h)]
    for bucket in WORK_BUCKETS:
        if buckets[bucket] > 0:
            parts.append(_fmt_hhmm(_minutes_to_hours(buckets[bucket])))
    parts.append(_fmt_hhmm(duty_h))
    diff_h = _minutes_to_hours(work_base_m - threshold_m)
    formula = f"{' − '.join(parts)} = {_fmt_hhmm(diff_h)}"
    note_parts = []
    if violation_m > 0:
        note_parts.append(
            f'کمبود {_fmt_hhmm(_minutes_to_hours(shortfall_m))}'
            f' + تأخیر/تعجیل {_fmt_hhmm(_minutes_to_hours(violation_m))}'
        )
    if unelapsed_m > 0:
        note_parts.append(
            f'موظفی سپری‌شده {_fmt_hhmm(_minutes_to_hours(elapsed_duty_m))}'
        )
    elif deficit_duty_m != threshold_m:
        note_parts.append(
            f'موظفی کسر کار {_fmt_hhmm(_minutes_to_hours(deficit_duty_m))}'
        )
    deficit_note = ' | '.join(note_parts)

    return {
        'day_count': n_calendar,
        'working_day_count': n_duty_days,
        'duty_hours': duty_h,
        'duty_note': duty_note,
        'work_hours': work_total_h,
        'work_base_hours': work_base_h,
        'friday_hours': _minutes_to_hours(buckets['friday']),
        'holiday_work_hours': _minutes_to_hours(buckets['holiday']),
        'rest_work_hours': _minutes_to_hours(buckets['rest']),
        'leave_work_hours': _minutes_to_hours(buckets['leave']),
        'hourly_overtime': 0.0,
        'weekly_overtime': weekly_h,
        'deficit_work_hours': _minutes_to_hours(deficit_work_m),
        'nonworking_in_base_hours': _minutes_to_hours(nonworking_in_base_m),
        'deficit_shortfall_hours': _minutes_to_hours(shortfall_m),
        'deficit_violation_hours': _minutes_to_hours(violation_m),
        'weekly_deficit': _minutes_to_hours(week_deficit_m),
        'deficit_note': deficit_note,
        'formula': formula,
    }


def calculate_weekly_overtime(
    days: List[Dict],
    settings: Optional[Dict] = None,
    ref: Optional[datetime] = None,
) -> float:
    """جمع اضافه‌کار هفتگی؛ بلوک هفته روی اولین روز با rowspan."""
    weeks: Dict = {}
    for day in days:
        start = week_start_saturday(day['date'])
        weeks.setdefault(start, []).append(day)

    ordered_starts = sorted(weeks.keys())
    weekly_m = 0
    for start in ordered_starts:
        week_days = sorted(weeks[start], key=lambda d: d['date'])
        metrics = _week_metrics(week_days, settings, ref)
        weekly_m += _hours_to_minutes(metrics['weekly_overtime'])
        first = week_days[0]
        for d in week_days:
            d['week_overtime'] = metrics['weekly_overtime']
            d['week_rowspan'] = 0
            d['week_block'] = None
        first['week_rowspan'] = len(week_days)
        first['week_block'] = metrics
    return _minutes_to_hours(weekly_m)


def _unelapsed_minutes(duty_m: int, day: Dict, ref: datetime) -> int:
    if duty_m <= 0:
        return 0
    d = day['date']
    if d < ref.date():
        return 0
    if d > ref.date():
        return duty_m
    start = day.get('duty_start_time') or DEFAULT_DUTY_START
    elapsed_m = int((ref - datetime.combine(d, start)).total_seconds() // 60)
    return duty_m - min(duty_m, max(0, elapsed_m))


def _monthly_deficit_minutes(
    days: List[Dict], summary: Dict, settings: Dict,
) -> Dict:
    """کسر کار ماهانه: روش تجمیعی = جمع `weekly_deficit` بلوک‌های هفته؛
    روش legacy از موظفی خلاصهٔ پایه (V2). فقط عدد؛ بدون تغییر روزها."""
    late_v_m = sum(int(d.get('late_violation_minutes') or 0) for d in days)
    early_v_m = sum(int(d.get('early_leave_violation_minutes') or 0) for d in days)

    if settings.get('deficit_method') == DEFICIT_METHOD_LEGACY:
        base_duty_m = _hours_to_minutes(summary.get('duty_hours') or 0)
        work_m = _hours_to_minutes(summary.get('total_work_hours') or 0)
        nopunch_m = sum(
            _hours_to_minutes(d.get('daily_duty') or 0)
            for d in days if d.get('person_status') == 'N'
        )
        duty_m = max(0, base_duty_m - nopunch_m)
        total = max(0, duty_m - work_m) + late_v_m + early_v_m
        return {'total_m': total, 'late_v_m': late_v_m, 'early_v_m': early_v_m}

    total = sum(
        _hours_to_minutes(d['week_block']['weekly_deficit'])
        for d in days if d.get('week_block')
    )
    return {'total_m': total, 'late_v_m': late_v_m, 'early_v_m': early_v_m}


def build_legal_ot_summary(
    days: List[Dict],
    base_summary: Dict,
    reference_at: Optional[datetime] = None,
    policy=None,
) -> Dict:
    """خلاصهٔ پرداختی — overtime_total = جمع weekly_overtime.

    با `deficit_adjust_ordinary_overtime` (روش تجمیعی) اضافه‌کار عادی ماه با کسر کار
    ماه تهاتر می‌شود: min(هر دو) از هر دو کم می‌شود؛ بلوک‌های هفته ناخالص می‌مانند.

    policy: ResolvedReportPolicy یا dict تنظیمات؛ پیش‌فرض = پیش‌فرض‌های کد.
    """
    settings = _resolve_settings(policy)
    for day in days:
        day['week_overtime'] = 0.0
        day['week_rowspan'] = 0
        day['week_block'] = None
        day['hourly_overtime'] = 0.0
        day['surplus'] = 0.0
        day['deficit'] = 0.0
        day['daily_excess_over_8'] = 0.0

    ref = reference_at or datetime.now()
    # روش legacy موظفی را کامل (بدون توجه به زمان مرجع) حساب می‌کند
    week_ref = None if settings.get('deficit_method') == DEFICIT_METHOD_LEGACY else ref
    weekly = calculate_weekly_overtime(days, settings, week_ref)
    overtime_total = weekly

    bucket_m = _bucket_minutes(days, settings)
    friday_work_hours = _minutes_to_hours(bucket_m['friday'])
    friday_work_days = len(_bucket_days(days, settings, 'friday'))
    holiday_work_hours = _minutes_to_hours(bucket_m['holiday'])
    holiday_work_days = len(_bucket_days(days, settings, 'holiday'))
    rest_work_hours = _minutes_to_hours(bucket_m['rest'])
    rest_work_days = len(_bucket_days(days, settings, 'rest'))
    leave_work_hours = _minutes_to_hours(bucket_m['leave'])
    leave_work_days = len(_bucket_days(days, settings, 'leave'))

    # روزهایی که واقعاً کارکرد داشته‌اند
    total_work_days = sum(
        1 for d in days if _hours_to_minutes(d.get('work_hours') or 0) > 0
    )
    # کارت کارکرد: روز کاری فرد + روز غیرکاری = کل کارکرد (مستقل از مبنای کسر کار)
    working_day_m = non_working_day_m = 0
    working_day_days = non_working_day_days = 0
    for d in days:
        work_m = _hours_to_minutes(d.get('work_hours') or 0)
        if work_m <= 0:
            continue
        if _is_working_day_type(d):
            working_day_m += work_m
            working_day_days += 1
        else:
            non_working_day_m += work_m
            non_working_day_days += 1
    hourly_leave_minutes = sum(int(d.get('hourly_leave_minutes') or 0) for d in days)
    hourly_mission_minutes = sum(
        int(d.get('hourly_mission_minutes') or 0) for d in days
    )

    summary = dict(base_summary)
    summary.update(punch_grace_totals(days))
    summary['grace_included_in_work'] = _hours_to_minutes(
        summary.get('total_work_hours') or 0
    ) == (
        _hours_to_minutes(summary['total_punch_hours'])
        + _hours_to_minutes(summary['total_grace_hours'])
    )
    deficit = _monthly_deficit_minutes(days, summary, settings)
    weekly_gross_m = _hours_to_minutes(weekly)
    deficit_gross_m = deficit['total_m']
    # روش legacy کسر کار را از کل کارکرد (شامل مازاد) می‌گیرد و تهاتر دوباره نمی‌خواهد
    offset_m = (
        min(weekly_gross_m, deficit_gross_m)
        if settings.get('deficit_adjust_ordinary_overtime')
        and settings.get('deficit_method') != DEFICIT_METHOD_LEGACY
        else 0
    )
    weekly = overtime_total = _minutes_to_hours(weekly_gross_m - offset_m)
    monthly_deficit = _minutes_to_hours(deficit_gross_m - offset_m)
    late_v_m = deficit['late_v_m']
    early_v_m = deficit['early_v_m']
    # حضور = هر روز با وضعیت P (جمعه/تعطیل‌کاری هم شمرده می‌شود)
    present_days = sum(1 for d in days if d.get('person_status') == 'P')
    leave_days = sum(1 for d in days if d.get('person_status') in ('L', 'SL'))
    absent_days = sum(1 for d in days if d.get('person_status') == 'A')
    no_punch_days = sum(1 for d in days if d.get('person_status') == 'N')
    rest_days = sum(1 for d in days if d.get('person_status') == 'R')
    holiday_days = sum(1 for d in days if d.get('person_status') == 'H')
    mission_days = sum(1 for d in days if d.get('person_status') == 'M')
    status_days_total = (
        present_days + leave_days + absent_days + no_punch_days
        + rest_days + holiday_days + mission_days
    )

    overtime_holiday_total = _minutes_to_hours(
        _hours_to_minutes(overtime_total) + _hours_to_minutes(holiday_work_hours)
    )
    # مجموع کارت‌های خلاصه: اضافه‌کار هفتگی + همهٔ سطل‌های تفکیک‌شده
    combined_total = _minutes_to_hours(
        _hours_to_minutes(overtime_total) + sum(bucket_m.values())
    )

    morning_m = sum(_hours_to_minutes(d.get('morning_hours') or 0) for d in days)
    evening_m = sum(_hours_to_minutes(d.get('evening_hours') or 0) for d in days)
    night_m = sum(_hours_to_minutes(d.get('night_hours') or 0) for d in days)
    # اگر روزها شیفت ندارند (تست‌های واحد ساده)، از خلاصهٔ پایه استفاده کن
    if morning_m + evening_m + night_m == 0:
        morning_m = _hours_to_minutes(summary.get('total_morning') or 0)
        evening_m = _hours_to_minutes(summary.get('total_evening') or 0)
        night_m = _hours_to_minutes(summary.get('total_night') or 0)
    total_morning = _minutes_to_hours(morning_m)
    total_evening = _minutes_to_hours(evening_m)
    total_night = _minutes_to_hours(night_m)
    shift_total_m = morning_m + evening_m + night_m
    if shift_total_m > 0:
        morning_percent = round(100.0 * morning_m / shift_total_m, 1)
        evening_percent = round(100.0 * evening_m / shift_total_m, 1)
        night_percent = round(max(0.0, 100.0 - morning_percent - evening_percent), 1)
    else:
        morning_percent = evening_percent = night_percent = 0.0

    # کارت موظفی = جمع ستون «موظفی هفتگی» (پس از محاسبهٔ کسر legacy روی موظفی پایه)
    week_blocks = [d['week_block'] for d in days if d.get('week_block')]
    duty_hours = _minutes_to_hours(
        sum(_hours_to_minutes(b['duty_hours']) for b in week_blocks)
    )
    duty_days = sum(b['working_day_count'] for b in week_blocks)

    summary.update({
        'duty_hours': duty_hours,
        'duty_days': duty_days,
        'hourly_overtime': 0.0,
        'daily_overtime': 0.0,
        'weekly_overtime': weekly,
        'overtime_total': overtime_total,
        'friday_work_hours': friday_work_hours,
        'friday_work_days': friday_work_days,
        'holiday_work_hours': holiday_work_hours,
        'holiday_work_days': holiday_work_days,
        'rest_work_hours': rest_work_hours,
        'rest_work_days': rest_work_days,
        'leave_work_hours': leave_work_hours,
        'leave_work_days': leave_work_days,
        'overtime_holiday_total': overtime_holiday_total,
        'combined_total': combined_total,
        'total_morning': total_morning,
        'total_evening': total_evening,
        'total_night': total_night,
        'morning_percent': morning_percent,
        'evening_percent': evening_percent,
        'night_percent': night_percent,
        'total_work_days': total_work_days,
        'work_split_enabled': bool(settings['deficit_separate_non_working']),
        'working_day_work_hours': _minutes_to_hours(working_day_m),
        'working_day_work_days': working_day_days,
        'non_working_day_work_hours': _minutes_to_hours(non_working_day_m),
        'non_working_day_work_days': non_working_day_days,
        'present_days': present_days,
        'leave_days': leave_days,
        'absent_days': absent_days,
        'no_punch_days': no_punch_days,
        'rest_days': rest_days,
        'holiday_days': holiday_days,
        'mission_days': mission_days,
        'status_days_total': status_days_total,
        'month_days': len(days),
        'hourly_leave_minutes': hourly_leave_minutes,
        'hourly_leave_hours': _minutes_to_hours(hourly_leave_minutes),
        'hourly_mission_minutes': hourly_mission_minutes,
        'hourly_mission_hours': _minutes_to_hours(hourly_mission_minutes),
        'monthly_deficit': monthly_deficit,
        'total_deficit': monthly_deficit,
        'weekly_overtime_gross': _minutes_to_hours(weekly_gross_m),
        'monthly_deficit_gross': _minutes_to_hours(deficit_gross_m),
        'overtime_deficit_offset': _minutes_to_hours(offset_m),
        'total_late_violation': _minutes_to_hours(late_v_m),
        'total_early_leave_violation': _minutes_to_hours(early_v_m),
        'total_late_violation_minutes': late_v_m,
        'total_early_leave_violation_minutes': early_v_m,
        'total_surplus': overtime_total,
        'report_policy_source': getattr(policy, 'source', 'default'),
        'report_policy_label': getattr(policy, 'label', 'پیش‌فرض سیستم'),
        'report_policy_settings': settings,
        'report_reference_at': ref.isoformat(timespec='minutes'),
        'overtime_coefficient': OVERTIME_COEFFICIENT,
        'friday_work_coefficient': FRIDAY_WORK_COEFFICIENT,
        'holiday_work_coefficient': HOLIDAY_WORK_COEFFICIENT,
    })
    return summary


class LegalOvertimeMonthlyReportGenerator:
    """تولید گزارش ماهانه با اضافه‌کار قانونی."""

    def __init__(self):
        self._v2 = DetailedMonthlyReportGeneratorV2()

    def close(self):
        self._v2.close()

    def generate_report(
        self, user_id: str, year: int, month: int,
        reference_at: Optional[datetime] = None,
        policy_overrides: Optional[Dict] = None,
    ) -> Dict:
        report = self._v2.generate_detailed_report(user_id, year, month)
        if not report.get('success'):
            return report

        days = report.get('days') or []
        reference_at = reference_at or datetime.now()
        policy = apply_overrides(
            resolve_report_policy(
                self._v2.db, LEGAL_OVERTIME_MONTHLY, month_end(year, month),
            ),
            policy_overrides,
        )
        report['report_policy'] = policy
        report['reference_at'] = reference_at
        report['summary'] = build_legal_ot_summary(
            days, report.get('summary') or {},
            reference_at=reference_at, policy=policy,
        )
        report['report_kind'] = 'legal_ot'
        report['report_title'] = 'گزارش اضافه‌کار قانونی'
        return report
