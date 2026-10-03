"""نمایش و محاسبه H:MM برای گزارش تفصیلی / کامل ماهانه."""
from datetime import date

from web.routes.reports import format_hhmm
from core.detailed_monthly_report_v2 import (
    _hours_to_minutes,
    _minutes_to_hours,
    _DEFAULT_DUTY_MINUTES,
    DetailedMonthlyReportGeneratorV2,
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
