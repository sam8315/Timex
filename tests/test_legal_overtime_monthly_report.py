"""تست اضافه‌کار قانونی — موظفی Σdaily_duty، کارکرد شامل جمعه."""
from datetime import date, timedelta
from typing import Optional

import pytest

from core.detailed_monthly_report_v2 import _hours_to_minutes, _minutes_to_hours
from core.legal_overtime_monthly_report import (
    WORKING_DAY_DUTY_MINUTES,
    build_legal_ot_summary,
    calculate_weekly_overtime,
    day_duty_minutes,
    proportional_weekly_required_minutes,
    week_start_saturday,
    weekly_required_minutes,
)
from web.services.report_policy_service import LEGAL_OT_DEFAULTS


def _day(
    d: date,
    work: float,
    *,
    is_friday: bool = False,
    is_day_off: bool = False,
    is_holiday: bool = False,
    person_status: str = 'P',
    daily_duty: Optional[float] = None,
    late_violation_minutes: int = 0,
    early_leave_violation_minutes: int = 0,
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
        'late_violation_minutes': late_violation_minutes,
        'early_leave_violation_minutes': early_leave_violation_minutes,
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

    def test_no_punch_day_is_outside_weekly_duty(self):
        days = _full_week([
            8,
            (0, {'person_status': 'N', 'daily_duty': 7.3333}),
            8, 8, 8, 8, 0,
        ])
        assert weekly_required_minutes(days) == 5 * WORKING_DAY_DUTY_MINUTES


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
        assert summary['combined_total'] == pytest.approx(10.0)  # 6 + 0 + 4
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
        assert summary['combined_total'] == pytest.approx(
            expected_ot + 5.0 + summary['friday_work_hours']
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

    @staticmethod
    def _mixed_week():
        return _full_week([
            8,
            7.5,
            (3, {'person_status': 'M'}),
            (2, {'person_status': 'R'}),
            (1, {'person_status': 'L'}),
            (5, {'is_holiday': True, 'is_day_off': True, 'person_status': 'P'}),
            4,
        ])

    @staticmethod
    def _assert_split_sums_to_total(summary):
        assert _hours_to_minutes(summary['working_day_work_hours']) + _hours_to_minutes(
            summary['non_working_day_work_hours']
        ) == _hours_to_minutes(summary['total_work_hours'])

    def test_working_and_non_working_day_work_split(self):
        """مبنای پیش‌فرض «کارکرد روز کاری»: ستون «کاری» و نه مرخصی/استراحت/مأموریت."""
        summary = build_legal_ot_summary(self._mixed_week(), {
            'duty_hours': 44.0,
            'total_work_hours': 30.5,
            'duty_days': 2,
        })
        assert summary['working_day_work_hours'] == pytest.approx(15.5)
        assert summary['working_day_work_days'] == 2
        assert summary['non_working_day_work_hours'] == pytest.approx(15.0)
        assert summary['non_working_day_work_days'] == 5
        self._assert_split_sums_to_total(summary)

    def test_work_card_split_independent_of_deficit_basis(self):
        """کارت کارکرد با مبنای «کل کارکرد» هم کاری/غیرکاری/مجموع را نشان می‌دهد."""
        summary = build_legal_ot_summary(
            self._mixed_week(),
            {'duty_hours': 44.0, 'total_work_hours': 30.5, 'duty_days': 2},
            policy=_settings(deficit_separate_non_working=False),
        )
        assert summary['work_split_enabled'] is False
        assert summary['working_day_work_hours'] == pytest.approx(15.5)
        assert summary['working_day_work_days'] == 2
        assert summary['non_working_day_work_hours'] == pytest.approx(15.0)
        assert summary['non_working_day_work_days'] == 5
        self._assert_split_sums_to_total(summary)

    def test_split_enabled_by_default(self):
        summary = build_legal_ot_summary(
            self._mixed_week(),
            {'duty_hours': 44.0, 'total_work_hours': 30.5, 'duty_days': 2},
        )
        assert summary['work_split_enabled'] is True

    def test_working_day_without_work_not_counted(self):
        days = _full_week([8, 0, 8, 8, 8, 8, 0])
        summary = build_legal_ot_summary(days, {
            'duty_hours': 44.0,
            'total_work_hours': 40.0,
            'duty_days': 6,
        })
        assert summary['working_day_work_days'] == 5
        assert summary['non_working_day_work_days'] == 0
        assert summary['non_working_day_work_hours'] == 0.0


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

    def test_monthly_deficit_includes_late_early_violations(self):
        """کسری ماهانه = max(0, duty-work) + تخلف تأخیر/تعجیل؛ OT تغییر نمی‌کند."""
        days = _full_week([
            (8, {'late_violation_minutes': 20, 'early_leave_violation_minutes': 10}),
            8, 8, 8, 8, 8, 0,
        ])
        ot_before_days = _full_week([8, 8, 8, 8, 8, 8, 0])
        base = {
            'duty_hours': 44.0,
            'total_work_hours': 48.0,
            'duty_days': 6,
        }
        summary = build_legal_ot_summary(days, dict(base))
        summary_no_late = build_legal_ot_summary(ot_before_days, dict(base))

        # کارکرد ۴۸ > موظفی ۴۴ → کمبود کارکرد ۰؛ فقط ۳۰د تخلف
        assert summary['monthly_deficit'] == pytest.approx(0.5)
        assert summary['total_late_violation'] == pytest.approx(20 / 60)
        assert summary['total_early_leave_violation'] == pytest.approx(10 / 60)
        # فرمول OT نباید به‌خاطر تأخیر/تعجیل عوض شود
        assert summary['overtime_total'] == pytest.approx(summary_no_late['overtime_total'])


class TestMonthlyDeficitElapsedDuty:
    """کسر کار: روز گذشته بدون تردد، روز جاری و آینده نسبت به زمان مرجع."""

    from datetime import datetime as _dt  # noqa: E402

    @staticmethod
    def _summary(days, ref, work_hours=0.0):
        duty = _minutes_to_hours(sum(_hours_to_minutes(d['daily_duty']) for d in days))
        return build_legal_ot_summary(
            days,
            {'duty_hours': duty, 'total_work_hours': work_hours},
            reference_at=ref,
        )

    def test_past_no_punch_day_counts_as_deficit(self):
        day = _day(date(2024, 3, 16), 0, person_status='N')
        s = self._summary([day], self._dt(2024, 3, 20, 12, 0))
        assert _hours_to_minutes(s['monthly_deficit']) == WORKING_DAY_DUTY_MINUTES

    def test_past_no_punch_with_leave_has_no_deficit(self):
        day = _day(date(2024, 3, 16), 0, person_status='L')
        s = self._summary([day], self._dt(2024, 3, 20, 12, 0))
        assert s['monthly_deficit'] == 0

    def test_current_day_only_elapsed_duty(self):
        from datetime import time
        day = _day(date(2024, 3, 16), 0, person_status='N')
        day['duty_start_time'] = time(7, 0)
        s = self._summary([day], self._dt(2024, 3, 16, 10, 0))
        assert _hours_to_minutes(s['monthly_deficit']) == 180

    def test_current_day_after_duty_end_is_full(self):
        day = _day(date(2024, 3, 16), 0, person_status='N')
        s = self._summary([day], self._dt(2024, 3, 16, 23, 0))
        assert _hours_to_minutes(s['monthly_deficit']) == WORKING_DAY_DUTY_MINUTES

    def test_future_day_excluded(self):
        day = _day(date(2024, 3, 25), 0, person_status='N')
        s = self._summary([day], self._dt(2024, 3, 20, 12, 0))
        assert s['monthly_deficit'] == 0

    def test_190_40_vs_158_39_is_not_zero(self):
        """۲۶ روز کاری × ۷:۲۰ = ۱۹۰:۴۰؛ کارکرد ۱۵۸:۳۹ بدون مجوز → کسری ۳۲:۰۱."""
        start = date(2024, 3, 16)  # شنبه
        days, work_total = [], 0
        for i in range(30):
            d = start + timedelta(days=i)
            if d.weekday() == 4:
                days.append(_day(d, 0, is_friday=True))
                continue
            minutes = 369 if i == 0 else 366
            work_total += minutes
            days.append(_day(d, _minutes_to_hours(minutes)))
        assert work_total == 158 * 60 + 39
        s = build_legal_ot_summary(
            days,
            {'duty_hours': _minutes_to_hours(190 * 60 + 40),
             'total_work_hours': _minutes_to_hours(work_total)},
            reference_at=self._dt(2024, 4, 30),
        )
        assert _hours_to_minutes(s['monthly_deficit']) == 32 * 60 + 1

    def test_default_excludes_friday_holiday_overtime_from_deficit(self):
        """مبنای پیش‌فرض «کارکرد روز کاری»: جمعه‌کاری کسر کار را پوشش نمی‌دهد."""
        days = _full_week([0, 0, 0, 0, 0, 0, 10])  # فقط جمعه‌کاری ۱۰ ساعت
        base = {'duty_hours': 44.0, 'total_work_hours': 10.0}
        ref = self._dt(2024, 4, 30)
        s = build_legal_ot_summary(days, dict(base), reference_at=ref)
        assert s['monthly_deficit'] == pytest.approx(44.0)
        # مبنای «کل کارکرد»: جمعه هم مثل همهٔ کارکرد کسر کار را پوشش می‌دهد
        days = _full_week([0, 0, 0, 0, 0, 0, 10])
        s2 = build_legal_ot_summary(
            days, dict(base), reference_at=ref,
            policy={'deficit_separate_non_working': False},
        )
        assert s2['monthly_deficit'] == pytest.approx(34.0)

    def test_ordinary_overtime_extracted_from_real_surplus_only(self):
        """هفته ۴۸ ساعت کار، موظفی ۴۴: فقط ۴ ساعت مازاد از اعتبار کسر می‌شود."""
        ref = self._dt(2024, 4, 30)
        base = {'duty_hours': 44.0 + 44.0, 'total_work_hours': 48.0}
        # هفته دوم بدون کارکرد → کمبود ۴۴ حتی با مازاد هفتهٔ اول
        wk1 = _full_week([8, 8, 8, 8, 8, 8, 0])
        sat2 = date(2024, 3, 23)
        wk2 = [
            _day(sat2 + timedelta(days=i), 0, is_friday=i == 6,
                 daily_duty=0.0 if i == 6 else None)
            for i in range(7)
        ]
        s = build_legal_ot_summary(wk1 + wk2, dict(base), reference_at=ref)
        assert s['overtime_total'] == pytest.approx(4.0)
        assert s['monthly_deficit'] == pytest.approx(44.0)
        for d in wk1 + wk2:
            d['week_block'] = None
        # تهاتر ماهانه: ۴ ساعت اضافه‌کار از کسر کار کم و خودش صفر می‌شود؛ بلوک هفته ناخالص
        s2 = build_legal_ot_summary(
            wk1 + wk2, dict(base), reference_at=ref,
            policy={'deficit_adjust_ordinary_overtime': True},
        )
        assert s2['overtime_deficit_offset'] == pytest.approx(4.0)
        assert s2['overtime_total'] == 0
        assert s2['weekly_overtime'] == 0
        assert s2['weekly_overtime_gross'] == pytest.approx(4.0)
        assert s2['monthly_deficit'] == pytest.approx(40.0)
        assert s2['monthly_deficit_gross'] == pytest.approx(44.0)
        assert wk2[0]['week_block']['weekly_deficit'] == pytest.approx(44.0)
        assert wk1[0]['week_block']['weekly_overtime'] == pytest.approx(4.0)
        assert wk1[0]['week_block']['weekly_deficit'] == 0

    def test_offset_limited_by_deficit(self):
        """اضافه‌کار ۸:۲۰ و کسر کار ۷:۲۰ (روز بدون تردد) → تهاتر ۷:۲۰، اضافه‌کار ۱:۰۰."""
        ref = self._dt(2024, 4, 30)
        days = _full_week([9, 9, 9, 9, 9, (0, {'person_status': 'N'}), 0])
        base = {'duty_hours': 44.0, 'total_work_hours': 45.0}
        s = build_legal_ot_summary(days, dict(base), reference_at=ref)
        assert _hours_to_minutes(s['overtime_total']) == 8 * 60 + 20
        assert _hours_to_minutes(s['monthly_deficit']) == WORKING_DAY_DUTY_MINUTES
        assert s['overtime_deficit_offset'] == 0
        days = _full_week([9, 9, 9, 9, 9, (0, {'person_status': 'N'}), 0])
        s2 = build_legal_ot_summary(
            days, dict(base), reference_at=ref,
            policy={'deficit_adjust_ordinary_overtime': True},
        )
        assert _hours_to_minutes(s2['overtime_deficit_offset']) == WORKING_DAY_DUTY_MINUTES
        assert _hours_to_minutes(s2['overtime_total']) == 60
        assert s2['monthly_deficit'] == 0
        assert _hours_to_minutes(s2['combined_total']) == 60

    def test_offset_skipped_for_legacy_method(self):
        ref = self._dt(2024, 4, 30)
        days = _full_week([9, 9, 9, 9, 9, (0, {'person_status': 'N'}), 0])
        s = build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 45.0}, reference_at=ref,
            policy={'deficit_adjust_ordinary_overtime': True, 'deficit_method': 'legacy'},
        )
        assert s['overtime_deficit_offset'] == 0
        assert _hours_to_minutes(s['overtime_total']) == 8 * 60 + 20

    def test_leave_work_covers_deficit_only_with_total_basis(self):
        """کارکرد ۴ ساعته در روز مرخصی؛ موظفی ۵×۷:۲۰ = ۳۶:۴۰."""
        ref = self._dt(2024, 4, 30)
        base = {'duty_hours': _minutes_to_hours(5 * WORKING_DAY_DUTY_MINUTES),
                'total_work_hours': 4.0}

        def week():
            return _full_week([0, 0, (4, {'person_status': 'L'}), 0, 0, 0, 0])

        s = build_legal_ot_summary(week(), dict(base), reference_at=ref)
        assert _hours_to_minutes(s['monthly_deficit']) == 5 * WORKING_DAY_DUTY_MINUTES
        s2 = build_legal_ot_summary(
            week(), dict(base), reference_at=ref,
            policy={'deficit_separate_non_working': False},
        )
        assert _hours_to_minutes(s2['monthly_deficit']) == 5 * WORKING_DAY_DUTY_MINUTES - 240

    def test_overtime_taken_from_separated_hours_in_base_first(self):
        """مأموریت ۱۰ ساعت داخل مبنای OT ولی روز غیرکاری برای کسر کار:
        OT = ۵۰ − ۳۶:۴۰ = ۱۳:۲۰؛ ۱۰ ساعتش از کارکرد مأموریت است، پس اعتبار روز کاری
        ۴۰ − ۳:۲۰ = ۳۶:۴۰ و کسر کار صفر (نه ۴۰ − ۱۳:۲۰)."""
        ref = self._dt(2024, 4, 30)
        base = {'duty_hours': _minutes_to_hours(5 * WORKING_DAY_DUTY_MINUTES),
                'total_work_hours': 50.0}
        days = _full_week([8, 8, (10, {'person_status': 'M'}), 8, 8, 8, 0])
        s = build_legal_ot_summary(days, dict(base), reference_at=ref)
        wb = days[0]['week_block']
        assert wb['deficit_work_hours'] == pytest.approx(40.0)
        assert wb['nonworking_in_base_hours'] == pytest.approx(10.0)
        assert _hours_to_minutes(s['weekly_overtime']) == 50 * 60 - 5 * WORKING_DAY_DUTY_MINUTES
        assert s['monthly_deficit'] == 0

    def test_legacy_method_keeps_old_behavior(self):
        day = _day(date(2024, 3, 16), 0, person_status='N')
        s = build_legal_ot_summary(
            [day], {'duty_hours': 7 + 20 / 60, 'total_work_hours': 0.0},
            reference_at=self._dt(2024, 3, 30),
            policy={'deficit_method': 'legacy'},
        )
        assert s['monthly_deficit'] == 0

    def test_late_early_counted_once_with_shortfall(self):
        day = _day(date(2024, 3, 16), 6 + 40 / 60, late_violation_minutes=25)
        s = build_legal_ot_summary(
            [day], {'duty_hours': 7 + 20 / 60, 'total_work_hours': 6 + 40 / 60},
            reference_at=self._dt(2024, 3, 30),
        )
        # موظفی ۷:۲۰، کارکرد ۶:۴۰ → کمبود ۴۰د؛ تخلف ۲۵د داخل آن است و اضافه نمی‌شود
        assert _hours_to_minutes(s['monthly_deficit']) == 40
    def test_late_early_violation_stays_additive_not_changed_by_reference(self):
        days = [_day(date(2024, 3, 16), 8.0, late_violation_minutes=20,
                     early_leave_violation_minutes=10)]
        s = build_legal_ot_summary(
            days, {'duty_hours': 7 + 20 / 60, 'total_work_hours': 8.0},
            reference_at=self._dt(2024, 3, 30),
        )
        assert _hours_to_minutes(s['monthly_deficit']) == 30


def _pday(d, work, status='P', *, base=WORKING_DAY_DUTY_MINUTES, hl=0, hm=0,
          is_friday=False, is_holiday=False):
    """روز با base_duty_minutes (مسیر واقعی V2)؛ daily_duty عمداً نامرتبط است."""
    return {
        'date': d,
        'work_hours': work,
        'is_friday': is_friday,
        'is_holiday': is_holiday,
        'is_day_off': is_friday or is_holiday,
        'person_status': status,
        'daily_duty': 0.0,
        'base_duty_minutes': 0 if (is_friday or is_holiday) else base,
        'hourly_leave_minutes': hl,
        'hourly_mission_minutes': hm,
    }


def _settings(**changes):
    return {**LEGAL_OT_DEFAULTS, **changes}


SAT = date(2024, 3, 16)


class TestPolicyDrivenDuty:
    def test_defaults_match_previous_behavior(self):
        cases = {
            'L': 0, 'SL': 0, 'M': 0, 'R': 0, 'N': 0,
            'A': WORKING_DAY_DUTY_MINUTES, 'P': WORKING_DAY_DUTY_MINUTES,
        }
        for status, expected in cases.items():
            assert day_duty_minutes(_pday(SAT, 0, status), _settings()) == expected
        assert day_duty_minutes(_pday(SAT, 8, hl=60), _settings()) == 380
        assert day_duty_minutes(_pday(SAT, 8, hm=30), _settings()) == 410

    @pytest.mark.parametrize('status,key', [
        ('L', 'duty_reduce_leave'),
        ('SL', 'duty_reduce_leave'),
        ('M', 'duty_reduce_mission'),
        ('R', 'duty_reduce_rest'),
        ('N', 'duty_reduce_no_punch'),
    ])
    def test_status_keeps_duty_when_option_off(self, status, key):
        day = _pday(SAT, 0, status)
        assert day_duty_minutes(day, _settings(**{key: False})) == WORKING_DAY_DUTY_MINUTES

    def test_absent_reduces_duty_when_option_on(self):
        day = _pday(SAT, 0, 'A')
        assert day_duty_minutes(day, _settings(duty_reduce_absent=True)) == 0

    def test_hourly_leave_and_mission_toggle(self):
        day = _pday(SAT, 8, hl=60, hm=30)
        assert day_duty_minutes(day, _settings()) == WORKING_DAY_DUTY_MINUTES - 90
        assert day_duty_minutes(
            day, _settings(duty_reduce_hourly_leave=False),
        ) == WORKING_DAY_DUTY_MINUTES - 30
        assert day_duty_minutes(
            day, _settings(duty_reduce_hourly_mission=False),
        ) == WORKING_DAY_DUTY_MINUTES - 60

    def test_holiday_never_has_duty(self):
        day = _pday(SAT, 0, 'H', is_holiday=True)
        assert day_duty_minutes(day, _settings(duty_reduce_leave=False)) == 0

    def test_weekly_duty_and_overtime_follow_policy(self):
        days = [_pday(SAT + timedelta(days=i), 8.0) for i in range(5)]
        days.append(_pday(SAT + timedelta(days=5), 0, 'L'))
        days.append(_pday(SAT + timedelta(days=6), 0, 'H', is_friday=True))
        assert weekly_required_minutes(days, _settings()) == 5 * WORKING_DAY_DUTY_MINUTES
        assert weekly_required_minutes(
            days, _settings(duty_reduce_leave=False),
        ) == 6 * WORKING_DAY_DUTY_MINUTES
        s = build_legal_ot_summary(
            days, {'duty_hours': 0, 'total_work_hours': 40.0},
            policy=_settings(duty_reduce_leave=False),
        )
        assert s['weekly_overtime'] == 0.0


class TestWeeklyDeficit:
    from datetime import datetime as _dt  # noqa: E402

    def test_past_week_shows_deficit_and_signed_formula(self):
        days = _full_week([7, 7, 7, 7, 7, 0, 0])
        build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 35.0},
            reference_at=self._dt(2024, 4, 30),
        )
        wb = days[0]['week_block']
        assert wb['weekly_overtime'] == 0.0
        assert wb['weekly_deficit'] == pytest.approx(9.0)
        assert wb['formula'].endswith('= -09:00')
        assert wb['deficit_note'] == ''

    def test_overtime_week_has_zero_deficit(self):
        days = _full_week([9, 9, 8, 8, 8, 8, 4])
        build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 54.0},
            reference_at=self._dt(2024, 4, 30),
        )
        wb = days[0]['week_block']
        assert wb['weekly_overtime'] == pytest.approx(6.0)
        assert wb['weekly_deficit'] == 0.0
        assert wb['formula'].endswith('= 06:00')

    def test_current_week_counts_only_elapsed_duty(self):
        # شنبه تا دوشنبه سپری شده (هر روز ۷ ساعت)، مرجع سه‌شنبه ۰۰:۰۰
        days = _full_week([7, 7, 7, 0, 0, 0, 0])
        build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 21.0},
            reference_at=self._dt(2024, 3, 19, 0, 0),
        )
        wb = days[0]['week_block']
        # موظفی سپری‌شده ۳×۷:۲۰ = ۲۲ → کسر ۱ ساعت (نه ۴۴ − ۲۱)
        assert wb['weekly_deficit'] == pytest.approx(1.0)
        assert 'سپری‌شده' in wb['deficit_note']

    def test_violation_in_same_week_deficit(self):
        days = _full_week([
            (8, {'late_violation_minutes': 20}), 8, 8, 8, 8, 8, 0,
        ])
        build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 48.0},
            reference_at=self._dt(2024, 4, 30),
        )
        wb = days[0]['week_block']
        assert _hours_to_minutes(wb['weekly_deficit']) == 20
        assert _hours_to_minutes(wb['deficit_violation_hours']) == 20
        assert wb['deficit_shortfall_hours'] == 0
        assert 'تأخیر/تعجیل' in wb['deficit_note']

    def test_no_punch_day_out_of_ot_duty_but_in_deficit(self):
        days = _full_week([8, 8, 8, 8, 8, (0, {'person_status': 'N'}), 0])
        s = build_legal_ot_summary(
            days, {'duty_hours': 44.0, 'total_work_hours': 40.0},
            reference_at=self._dt(2024, 4, 30),
        )
        wb = days[0]['week_block']
        assert _hours_to_minutes(wb['duty_hours']) == 5 * WORKING_DAY_DUTY_MINUTES
        # OT = ۴۰ − ۳۶:۴۰ = ۳:۲۰، ولی روز بدون تردد کسر کار است
        assert _hours_to_minutes(wb['weekly_overtime']) == 40 * 60 - 5 * WORKING_DAY_DUTY_MINUTES
        assert _hours_to_minutes(wb['weekly_deficit']) == WORKING_DAY_DUTY_MINUTES
        assert 'موظفی کسر کار' in wb['deficit_note']
        assert s['monthly_deficit'] == wb['weekly_deficit']


class TestWeeklyColumnMatchesCards:
    """کارت‌های خلاصه = جمع ستون محاسبات هفتگی."""

    from datetime import datetime as _dt  # noqa: E402

    def _month(self):
        start = date(2024, 3, 16)  # شنبه
        works = [
            [8, 8, 8, 8, 8, 8, 4],
            [7, 6, 0, 7, 7, 7, 0],
            [8, (0, {'person_status': 'L'}), 8, 9, 8, 8, 0],
            [5, 5, 5, 5, 5, 5, 0],
        ]
        days = []
        for w, week in enumerate(works):
            for i, spec in enumerate(week):
                work, kw = spec if isinstance(spec, tuple) else (spec, {})
                d = start + timedelta(days=7 * w + i)
                if w == 1 and i == 0:
                    kw = {**kw, 'late_violation_minutes': 30}
                if w == 0 and i == 1:
                    kw = {**kw, 'early_leave_violation_minutes': 15}
                days.append(_day(d, work, is_friday=i == 6, **kw))
        return days

    @staticmethod
    def _blocks(days):
        return [d['week_block'] for d in days if d.get('week_block')]

    @pytest.mark.parametrize('policy', [
        None,
        {'deficit_separate_non_working': False},
        {'deficit_adjust_ordinary_overtime': True},
        {'duty_reduce_leave': False},
    ])
    def test_deficit_and_duty_cards_are_week_sums(self, policy):
        days = self._month()
        s = build_legal_ot_summary(
            days, {'duty_hours': 999.0, 'duty_days': 99, 'total_work_hours': 0.0},
            reference_at=self._dt(2024, 4, 30), policy=policy,
        )
        blocks = self._blocks(days)
        assert len(blocks) == 4
        offset_m = _hours_to_minutes(s['overtime_deficit_offset'])
        assert _hours_to_minutes(s['monthly_deficit_gross']) == sum(
            _hours_to_minutes(b['weekly_deficit']) for b in blocks
        )
        assert _hours_to_minutes(s['monthly_deficit']) == (
            _hours_to_minutes(s['monthly_deficit_gross']) - offset_m
        )
        assert _hours_to_minutes(s['duty_hours']) == sum(
            _hours_to_minutes(b['duty_hours']) for b in blocks
        )
        assert s['duty_days'] == sum(b['working_day_count'] for b in blocks)
        assert _hours_to_minutes(s['weekly_overtime_gross']) == sum(
            _hours_to_minutes(b['weekly_overtime']) for b in blocks
        )
        assert _hours_to_minutes(s['weekly_overtime']) == (
            _hours_to_minutes(s['weekly_overtime_gross']) - offset_m
        )

    @pytest.mark.parametrize('reduce_leave,n_days', [(True, 5), (False, 6)])
    def test_duty_card_follows_duty_reduce_policy(self, reduce_leave, n_days):
        days = [_pday(SAT + timedelta(days=i), 8.0) for i in range(5)]
        days.append(_pday(SAT + timedelta(days=5), 0, 'L'))
        days.append(_pday(SAT + timedelta(days=6), 0, 'H', is_friday=True))
        s = build_legal_ot_summary(
            days, {'duty_hours': 0, 'duty_days': 0, 'total_work_hours': 40.0},
            reference_at=self._dt(2024, 4, 30),
            policy=_settings(duty_reduce_leave=reduce_leave),
        )
        wb = days[0]['week_block']
        assert _hours_to_minutes(s['duty_hours']) == n_days * WORKING_DAY_DUTY_MINUTES
        assert s['duty_hours'] == wb['duty_hours']
        assert s['duty_days'] == n_days == wb['working_day_count']


class TestPolicyDrivenWork:
    def _week(self):
        return [
            _pday(SAT, 8.0),
            _pday(SAT + timedelta(days=1), 8.0),
            _pday(SAT + timedelta(days=2), 4.0, 'R'),
            _pday(SAT + timedelta(days=3), 3.0, 'L'),
            _pday(SAT + timedelta(days=4), 8.0),
            _pday(SAT + timedelta(days=5), 5.0, 'P', is_holiday=True),
            _pday(SAT + timedelta(days=6), 6.0, 'P', is_friday=True),
        ]

    def test_all_four_buckets_always_separated(self):
        days = self._week()
        s = build_legal_ot_summary(days, {'duty_hours': 0, 'total_work_hours': 42.0})
        wb = days[0]['week_block']
        # کل ۴۲ − جمعه ۶ − تعطیل ۵ − استراحت ۴ − مرخصی ۳ = ۲۴
        assert wb['work_base_hours'] == pytest.approx(24.0)
        assert s['friday_work_hours'] == pytest.approx(6.0)
        assert s['holiday_work_hours'] == pytest.approx(5.0)
        assert s['rest_work_hours'] == pytest.approx(4.0)
        assert s['rest_work_days'] == 1
        assert s['leave_work_hours'] == pytest.approx(3.0)
        assert s['leave_work_days'] == 1
        assert s['combined_total'] == pytest.approx(
            s['weekly_overtime'] + 6.0 + 5.0 + 4.0 + 3.0
        )

    def test_old_work_separate_keys_have_no_effect(self):
        base_days = self._week()
        build_legal_ot_summary(base_days, {'duty_hours': 0, 'total_work_hours': 42.0})
        days = self._week()
        build_legal_ot_summary(
            days, {'duty_hours': 0, 'total_work_hours': 42.0},
            policy=_settings(
                work_separate_friday=False, work_separate_holiday=False,
                work_separate_rest=False, work_separate_leave=False,
            ),
        )
        assert days[0]['week_block']['work_base_hours'] == pytest.approx(
            base_days[0]['week_block']['work_base_hours']
        )

    @pytest.mark.parametrize('reduce_rest', [True, False])
    @pytest.mark.parametrize('reduce_leave', [True, False])
    def test_every_hour_counted_once(self, reduce_rest, reduce_leave):
        days = self._week()
        build_legal_ot_summary(
            days, {'duty_hours': 0, 'total_work_hours': 42.0},
            policy=_settings(duty_reduce_rest=reduce_rest, duty_reduce_leave=reduce_leave),
        )
        wb = days[0]['week_block']
        parts = (
            wb['work_base_hours'] + wb['friday_hours'] + wb['holiday_work_hours']
            + wb['rest_work_hours'] + wb['leave_work_hours']
        )
        assert parts == pytest.approx(wb['work_hours'])
