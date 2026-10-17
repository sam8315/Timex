"""نمایش و محاسبه H:MM برای گزارش تفصیلی / کامل ماهانه."""
from datetime import date, datetime, time

from web.routes.reports import format_hhmm
from web.services.report_policy_service import (
    DEFICIT_METHOD_LEGACY,
    LEGAL_OT_DEFAULTS,
)
from core.detailed_monthly_report_v2 import (
    _hours_to_minutes,
    _minutes_to_hours,
    _DEFAULT_DUTY_MINUTES,
    DetailedMonthlyReportGeneratorV2,
    apply_no_punch_deficit,
)


def test_format_hhmm_seven_twenty_not_decimal():
    assert format_hhmm(440 / 60) == '07:20'
    assert format_hhmm(7.33) == '07:20'  # تقریباً ۷:۲۰
    assert format_hhmm(0) == '-'
    assert format_hhmm(None) == '-'
    assert format_hhmm(-1.5) == '-01:30'


def test_default_duty_is_seven_twenty_minutes():
    assert _DEFAULT_DUTY_MINUTES == 440
    assert format_hhmm(_minutes_to_hours(_DEFAULT_DUTY_MINUTES)) == '07:20'


def test_surplus_deficit_uses_minute_math():
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    # کارکرد ۸:۰۰ در برابر موظفی ۷:۲۰ → اضافه ۰:۴۰
    surplus, deficit = gen._calculate_surplus_deficit(
        work_hours=8.0,
        is_day_off=False,
        person_status={'code': 'P'},
        daily_required_hours=_minutes_to_hours(440),
    )
    assert _hours_to_minutes(surplus) == 40
    assert deficit == 0.0
    assert format_hhmm(surplus) == '00:40'

    # کارکرد ۶:۰۰ → کسری ۱:۲۰
    surplus, deficit = gen._calculate_surplus_deficit(
        work_hours=6.0,
        is_day_off=False,
        person_status={'code': 'P'},
        daily_required_hours=_minutes_to_hours(440),
    )
    assert surplus == 0.0
    assert _hours_to_minutes(deficit) == 80
    assert format_hhmm(deficit) == '01:20'


def test_surplus_deficit_adds_late_early_violations():
    """کسری نهایی = کسری کارکرد + تخلف تأخیر + تخلف تعجیل."""
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    # کارکرد دقیق موظفی + ۱۵د تأخیر + ۱۰د تعجیل → کسری ۲۵د
    surplus, deficit = gen._calculate_surplus_deficit(
        work_hours=_minutes_to_hours(440),
        is_day_off=False,
        person_status={'code': 'P'},
        daily_required_hours=_minutes_to_hours(440),
        late_violation_minutes=15,
        early_leave_violation_minutes=10,
    )
    assert surplus == 0.0
    assert _hours_to_minutes(deficit) == 25

    # کارکرد ۶:۰۰ (کسری ۸۰د) + ۲۰د تأخیر → کسری ۱۰۰د
    surplus, deficit = gen._calculate_surplus_deficit(
        work_hours=6.0,
        is_day_off=False,
        person_status={'code': 'P'},
        daily_required_hours=_minutes_to_hours(440),
        late_violation_minutes=20,
        early_leave_violation_minutes=0,
    )
    assert surplus == 0.0
    assert _hours_to_minutes(deficit) == 100


def _nopunch_day(d, **extra):
    row = {
        'date': d,
        'person_status': 'N',
        'is_friday': False,
        'is_holiday': False,
        'has_duty': True,
        'surplus': 0.0,
        'deficit': 0.0,
        'daily_duty': _minutes_to_hours(440),
        'base_duty_minutes': 440,
        'work_hours': 0.0,
        'morning_hours': 0.0,
        'evening_hours': 0.0,
        'night_hours': 0.0,
        'late_violation_minutes': 0,
        'early_leave_violation_minutes': 0,
        'hourly_leave_minutes': 0,
        'hourly_mission_minutes': 0,
        'duty_start_time': time(7, 0),
    }
    row.update(extra)
    return row


def test_no_punch_is_not_absence_and_follows_elapsed_rules():
    """بدون تردد غیبت نیست؛ کسری‌اش مثل گزارش قانونی به زمان مرجع بستگی دارد."""
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    day = date(2024, 4, 2)
    recorded = gen._determine_person_status(day, {day: "A"}, {}, is_day_off=False)
    assert recorded == {"code": "A", "name": "غایب"}
    missing = gen._determine_person_status(day, {}, {}, is_day_off=False)
    assert missing == {"code": "N", "name": "بدون تردد"}

    ref = datetime(2024, 4, 2, 10, 0)
    past = _nopunch_day(date(2024, 4, 1))
    today = _nopunch_day(date(2024, 4, 2))
    future = _nopunch_day(date(2024, 4, 3))
    present = _nopunch_day(
        date(2024, 4, 1),
        person_status='P',
        surplus=_minutes_to_hours(40),
        work_hours=8.0,
    )
    apply_no_punch_deficit(
        [past, today, future, present], LEGAL_OT_DEFAULTS, ref,
    )
    assert past['surplus'] == 0.0
    assert _hours_to_minutes(past['deficit']) == 440
    assert _hours_to_minutes(today['deficit']) == 180
    assert future['deficit'] == 0.0
    assert _hours_to_minutes(present['surplus']) == 40
    assert present['deficit'] == 0.0

    with_leave = _nopunch_day(date(2024, 4, 1), hourly_leave_minutes=60)
    apply_no_punch_deficit([with_leave], LEGAL_OT_DEFAULTS, ref)
    assert _hours_to_minutes(with_leave['deficit']) == 380

    legacy = _nopunch_day(date(2024, 4, 1))
    apply_no_punch_deficit(
        [legacy],
        {**LEGAL_OT_DEFAULTS, 'deficit_method': DEFICIT_METHOD_LEGACY},
        ref,
    )
    assert legacy['deficit'] == 0.0


def test_past_no_punch_deficit_is_included_in_monthly_total():
    """مرجع بعد از ماه: کسری روزهای بدون تردد در مجموع کسری می‌آید."""
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    short = _nopunch_day(
        date(2024, 4, 2),
        person_status='P',
        work_hours=6.0,
        deficit=_minutes_to_hours(80),
        has_duty=True,
    )
    missed = _nopunch_day(date(2024, 4, 3))
    later = _nopunch_day(date(2024, 5, 1))
    days = [short, missed, later]
    apply_no_punch_deficit(days, LEGAL_OT_DEFAULTS, datetime(2024, 4, 30, 12, 0))
    summary = gen._calculate_monthly_summary(days)
    assert _hours_to_minutes(missed['deficit']) == 440
    assert later['deficit'] == 0.0
    assert _hours_to_minutes(summary['total_deficit']) == 440 + 80
    assert summary['overall_status'] == 'کسری'


def test_leave_on_day_off_counts_as_holiday_not_leave():
    """مرخصی روی جمعه/تعطیل → وضعیت H؛ فقط روز کاری به‌عنوان L شمرده می‌شود."""
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    d = date(2024, 4, 1)
    statuses = {d: 'AL'}

    working = gen._determine_person_status(d, statuses, {}, is_day_off=False)
    assert working == {'code': 'L', 'name': 'مرخصی'}

    day_off = gen._determine_person_status(d, statuses, {}, is_day_off=True)
    assert day_off == {'code': 'H', 'name': 'تعطیل'}


def test_leave_days_summary_excludes_friday_and_holiday_in_range():
    """بازه ۱–۷ با یک جمعه و یک تعطیل → leave_days=5 نه 7."""
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    days = []
    for i in range(1, 8):
        is_friday = i == 5
        is_holiday = i == 3
        is_day_off = is_friday or is_holiday
        status = gen._determine_person_status(
            date(2024, 4, i),
            {date(2024, 4, j): 'AL' for j in range(1, 8)},
            {},
            is_day_off=is_day_off,
        )
        days.append({
            'date': date(2024, 4, i),
            'person_status': status['code'],
            'is_friday': is_friday,
            'is_holiday': is_holiday,
            'has_duty': False,
            'surplus': 0.0,
            'deficit': 0.0,
            'daily_duty': 0.0,
            'work_hours': 0.0,
            'morning_hours': 0.0,
            'evening_hours': 0.0,
            'night_hours': 0.0,
            'late_violation_minutes': 0,
            'early_leave_violation_minutes': 0,
        })

    summary = gen._calculate_monthly_summary(days)
    assert summary['leave_days'] == 5
    assert summary['holiday_days'] == 2
