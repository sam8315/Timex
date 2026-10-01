"""تست اضافه‌کار قانونی — موظفی Σdaily_duty، کارکرد شامل جمعه."""
from datetime import date, timedelta
from typing import Optional

import pytest

from core.detailed_monthly_report_v2 import _hours_to_minutes, _minutes_to_hours
from core.legal_overtime_monthly_report import (
    WORKING_DAY_DUTY_MINUTES,
    build_legal_ot_summary,
    calculate_weekly_overtime,
    proportional_weekly_required_minutes,
    week_start_saturday,
    weekly_required_minutes,
)


def _day(
    d: date,
    work: float,
    *,
    is_friday: bool = False,
    is_day_off: bool = False,
    is_holiday: bool = False,
    person_status: str = 'P',
    daily_duty: Optional[float] = None,
):
    if daily_duty is None:
        if is_friday or is_day_off or is_holiday or person_status in ('L', 'R', 'M', 'H'):
            daily_duty = 0.0
        else:
            daily_duty = _minutes_to_hours(WORKING_DAY_DUTY_MINUTES)
    return {
        'date': d,
        'work_hours': work,
        'is_friday': is_friday,
        'is_day_off': is_day_off or is_friday or is_holiday,
        'is_holiday': is_holiday,
        'person_status': person_status,
        'daily_duty': daily_duty,
    }


def _full_week(specs):
    """specs: لیست ۷ تایی از (work,) یا (work, kwargs)."""
    sat = date(2024, 3, 16)
    days = []
    for i, spec in enumerate(specs):
        if isinstance(spec, tuple):
            work, kwargs = spec[0], (spec[1] if len(spec) > 1 else {})
        else:
            work, kwargs = spec, {}
        is_fri = i == 6
        kwargs = {'is_friday': is_fri, 'is_day_off': is_fri, **kwargs}
        if is_fri and 'daily_duty' not in kwargs:
            kwargs.setdefault('daily_duty', 0.0)
        days.append(_day(sat + timedelta(days=i), work, **kwargs))
    return days


class TestWeeklyDutyFromDailyDuty:
    def test_full_week_sum_duty_is_44(self):
        days = _full_week([8, 8, 8, 8, 8, 8, 0])
        assert weekly_required_minutes(days) == 6 * WORKING_DAY_DUTY_MINUTES

    def test_leave_day_reduces_weekly_duty(self):
        days = _full_week([
            8, 8,
            (0, {'person_status': 'L', 'daily_duty': 0.0}),
            8, 8, 8, 0,
        ])
        assert weekly_required_minutes(days) == 5 * WORKING_DAY_DUTY_MINUTES

    def test_hourly_leave_reduces_daily_duty(self):
        # HL یک ساعت از موظفی روز کم شده → daily_duty = 6:20
        reduced = _minutes_to_hours(WORKING_DAY_DUTY_MINUTES - 60)
        sat = date(2024, 3, 16)
        days = [
            _day(sat, 8.0, daily_duty=reduced),
            _day(sat + timedelta(days=1), 8.0),
        ]
        assert weekly_required_minutes(days) == (
            WORKING_DAY_DUTY_MINUTES - 60 + WORKING_DAY_DUTY_MINUTES
        )

    def test_holiday_zero_duty(self):
        days = _full_week([
            8,
            (0, {'is_holiday': True, 'is_day_off': True, 'person_status': 'H', 'daily_duty': 0.0}),
            8, 8, 8, 8, 0,
        ])
        assert weekly_required_minutes(days) == 5 * WORKING_DAY_DUTY_MINUTES

    def test_policy_duty_priority_custom_minutes(self):
        # سیاست سفارشی: روز ۸ ساعته (۴۸۰ دقیقه)
        custom = _minutes_to_hours(480)
        sat = date(2024, 3, 16)
        days = [_day(sat + timedelta(days=i), 8.0, daily_duty=custom) for i in range(5)]
        assert weekly_required_minutes(days) == 5 * 480
        assert proportional_weekly_required_minutes(days) == 5 * 480


class TestArticle51WithFridayInBase:
    def test_redistribution_not_overtime(self):
        """۵×۷ + ۱۰ = ۴۵؛ موظفی ۴۴ → اضافه‌کار ۱."""
        days = _full_week([7, 7, 7, 7, 7, 10, 0])
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 45.0,
            'duty_days': 6,
        })
        assert summary['hourly_overtime'] == 0.0
        assert summary['weekly_overtime'] == pytest.approx(1.0)
        assert summary['overtime_total'] == pytest.approx(1.0)
        assert summary['total_work_days'] == 6

    def test_friday_subtracted_from_weekly_ot_base(self):
        """کارکرد ۵۴، جمعه۴ کسر → مبنای ۵۰؛ موظفی ۴۴ → هفتگی ۶؛ جمعه ۴ جدا."""
        days = _full_week([9, 9, 8, 8, 8, 8, 4])
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 54.0,
            'duty_days': 6,
        })
        assert summary['weekly_overtime'] == pytest.approx(6.0)
        assert summary['overtime_total'] == pytest.approx(6.0)
        assert summary['friday_work_hours'] == pytest.approx(4.0)
        assert summary['overtime_coefficient'] == pytest.approx(1.4)
        assert summary['friday_work_coefficient'] == pytest.approx(1.96)
        assert summary['total_work_days'] == 7
        wb = days[0]['week_block']
        assert wb['work_hours'] == pytest.approx(54.0)
        assert wb['work_base_hours'] == pytest.approx(50.0)
        assert wb['weekly_overtime'] == pytest.approx(6.0)
        assert '−' in wb['formula']

    def test_holiday_work_separate_bucket(self):
        """تعطیل‌کاری مثل جمعه از مبنای هفتگی کم و در سطل جدا می‌آید."""
        days = _full_week([
            8, 8, 8, 8, 8,
            (5, {
                'is_holiday': True,
                'is_day_off': True,
                'person_status': 'P',
                'daily_duty': 0.0,
            }),
            0,
        ])
        # کارکرد ۴۵؛ تعطیل‌کاری ۵؛ موظفی ۵×۷:۲۰؛ مبنای OT = ۴۰
        summary = build_legal_ot_summary(days, {
            'duty_hours': _minutes_to_hours(5 * WORKING_DAY_DUTY_MINUTES),
            'total_work_hours': 45.0,
            'duty_days': 5,
        })
        assert summary['holiday_work_hours'] == pytest.approx(5.0)
        assert summary['holiday_work_days'] == 1
        assert summary['holiday_work_coefficient'] == pytest.approx(1.4)
        assert summary['friday_work_hours'] == 0.0
        expected_ot = _minutes_to_hours(
            _hours_to_minutes(40.0) - 5 * WORKING_DAY_DUTY_MINUTES
        )
        assert summary['weekly_overtime'] == pytest.approx(expected_ot)
        assert summary['overtime_holiday_total'] == pytest.approx(
            expected_ot + 5.0
        )
        wb = days[0]['week_block']
        assert wb['holiday_work_hours'] == pytest.approx(5.0)
        assert wb['work_base_hours'] == pytest.approx(40.0)

    def test_leave_lowers_duty_increases_ot(self):
        """یک روز مرخصی: موظفی ۵×۷:۲۰؛ کارکرد ۴۰ → OT = ۴۰−۳۶:۴۰."""
        days = _full_week([
            8, 8,
            (0, {'person_status': 'L', 'daily_duty': 0.0}),
            8, 8, 8, 0,
        ])
        summary = build_legal_ot_summary(days, {
            'duty_hours': _minutes_to_hours(5 * WORKING_DAY_DUTY_MINUTES),
            'total_work_hours': 40.0,
            'duty_days': 5,
        })
        expected = _minutes_to_hours(
            _hours_to_minutes(40.0) - 5 * WORKING_DAY_DUTY_MINUTES
        )
        assert summary['weekly_overtime'] == pytest.approx(expected)

    def test_partial_week(self):
        sat = date(2024, 3, 16)
        days = [
            _day(sat, 10.0),
            _day(sat + timedelta(days=1), 10.0),
            _day(sat + timedelta(days=2), 10.0),
        ]
        cap_m = weekly_required_minutes(days)
        assert cap_m == 3 * WORKING_DAY_DUTY_MINUTES
        expected = _minutes_to_hours(_hours_to_minutes(30.0) - cap_m)
        assert calculate_weekly_overtime(days) == pytest.approx(expected)


def test_week_start_saturday():
    assert week_start_saturday(date(2024, 3, 22)) == date(2024, 3, 16)


class TestSummaryWorkDays:
    def test_total_work_days_counts_days_with_work(self):
        days = _full_week([8, 0, 8, 8, 0, 8, 4])
        # set friday present
        days[-1]['person_status'] = 'P'
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 36.0,
            'duty_days': 4,
        })
        assert summary['total_work_days'] == 5  # 8,8,8,8,4


class TestStatusDayCounts:
    def test_present_includes_friday_and_holiday_work(self):
        """حضور هر روز با status=P را می‌شمارد (نه فقط روز کاری عادی)."""
        days = _full_week([
            8, 8, 8, 8, 8,
            (5, {'is_holiday': True, 'is_day_off': True, 'person_status': 'P', 'daily_duty': 0.0}),
            4,  # جمعه حاضر
        ])
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 49.0,
            'duty_days': 5,
            # مقادیر قدیمی V2 که جمعه/تعطیل را از حضور حذف می‌کرد
            'present_days': 5,
        })
        assert summary['present_days'] == 7
        assert summary['friday_work_days'] == 1

    def test_status_counts_sum_equals_month_days(self):
        """جمع وضعیت‌های روزشمار باید برابر تعداد روزهای ماه باشد."""
        # ماه ۳۰ روزهٔ ساختگی با وضعیت‌های متنوع
        start = date(2024, 3, 1)
        statuses = (
            ['P'] * 12
            + ['L'] * 5
            + ['M'] * 3
            + ['A'] * 2
            + ['R'] * 2
            + ['H'] * 4
            + ['P'] * 2  # جمعه/تعطیل‌کاری هم P
        )
        assert len(statuses) == 30
        days = []
        for i, st in enumerate(statuses):
            d = start + timedelta(days=i)
            is_fri = d.weekday() == 4
            is_hol = st == 'H'
            work = 8.0 if st == 'P' else 0.0
            days.append(_day(
                d, work,
                is_friday=is_fri,
                is_holiday=is_hol,
                is_day_off=is_fri or is_hol or st in ('L', 'R', 'M', 'H'),
                person_status=st,
                daily_duty=0.0 if st != 'P' or is_fri else _minutes_to_hours(WORKING_DAY_DUTY_MINUTES),
            ))

        summary = build_legal_ot_summary(days, {
            'duty_hours': 100.0,
            'total_work_hours': 100.0,
            'duty_days': 12,
        })
        day_status_sum = (
            summary['present_days']
            + summary['leave_days']
            + summary['mission_days']
            + summary['absent_days']
            + summary['rest_days']
            + summary['holiday_days']
        )
        assert summary['month_days'] == 30
        assert summary['status_days_total'] == 30
        assert day_status_sum == len(days)
        assert day_status_sum == summary['month_days']
        assert summary['present_days'] == 14
        assert summary['leave_days'] == 5
        assert summary['mission_days'] == 3
        assert summary['absent_days'] == 2
        assert summary['rest_days'] == 2
        assert summary['holiday_days'] == 4

    def test_morning_evening_night_percentages(self):
        """کارت‌های صبح/عصر/شب و درصد نسبت به جمع سه سطل."""
        days = _full_week([8, 8, 8, 8, 8, 8, 0])
        for d in days:
            d['morning_hours'] = 5.0 if d['work_hours'] else 0.0
            d['evening_hours'] = 3.0 if d['work_hours'] else 0.0
            d['night_hours'] = 0.0
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 48.0,
            'duty_days': 6,
        })
        assert summary['total_morning'] == pytest.approx(30.0)
        assert summary['total_evening'] == pytest.approx(18.0)
        assert summary['total_night'] == pytest.approx(0.0)
        assert summary['morning_percent'] == pytest.approx(62.5)
        assert summary['evening_percent'] == pytest.approx(37.5)
        assert summary['night_percent'] == pytest.approx(0.0)
        assert (
            summary['morning_percent']
            + summary['evening_percent']
            + summary['night_percent']
        ) == pytest.approx(100.0)
