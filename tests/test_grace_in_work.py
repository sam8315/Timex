"""جمع دقایق داخل فرجه با کارکرد سه گزارش ماهانه."""
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

from core.detailed_monthly_report_v2 import (
    DetailedMonthlyReportGeneratorV2,
    _hours_to_minutes,
    _minutes_to_hours,
    punch_grace_totals,
)
from core.legal_overtime_monthly_report import build_legal_ot_summary
from web.services.attendance_policy_service import (
    PolicyDayInfo,
    ResolvedPolicy,
    compute_late_early_for_day,
    effective_work_hours,
    grace_credit_minutes,
)

SATURDAY = date(2024, 3, 16)  # شنبه، weekday=5
DUTY_MINUTES = 420  # 07:00–14:00
PUNCH_MINUTES = 415  # 07:10–14:05


def _policy(*, late_enabled, late_allowed, early_enabled, early_allowed, include_grace):
    policy = SimpleNamespace(
        late_enabled=late_enabled,
        late_allowed_minutes=late_allowed,
        late_reference_mode='FIXED_TIME',
        early_leave_enabled=early_enabled,
        early_leave_allowed_minutes=early_allowed,
        early_leave_reference_mode='FIXED_TIME',
        include_grace_in_work=include_grace,
    )
    return ResolvedPolicy(
        policy=policy,
        employment_type_code='1',
        policy_days={
            5: PolicyDayInfo(
                weekday=5,
                is_working_day=True,
                start_time=time(7, 0),
                end_time=time(14, 0),
                required_minutes=DUTY_MINUTES,
            ),
        },
        is_employee_override=False,
    )


def _late_early(resolved, enter_h, enter_m, exit_h, exit_m):
    return compute_late_early_for_day(
        resolved=resolved,
        target_date=SATURDAY,
        first_enter=datetime(2024, 3, 16, enter_h, enter_m),
        last_exit=datetime(2024, 3, 16, exit_h, exit_m),
    )


def _effective(resolved, late_early, punch_minutes):
    grace_m = grace_credit_minutes(late_early)
    work = effective_work_hours(
        _minutes_to_hours(punch_minutes),
        grace_m,
        bool(resolved.policy.include_grace_in_work),
    )
    return grace_m, work


def _surplus_deficit(work_hours, late_early):
    gen = DetailedMonthlyReportGeneratorV2.__new__(DetailedMonthlyReportGeneratorV2)
    return gen._calculate_surplus_deficit(
        work_hours=work_hours,
        is_day_off=False,
        person_status={'code': 'P'},
        daily_required_hours=_minutes_to_hours(DUTY_MINUTES),
        late_violation_minutes=late_early['late_violation_minutes'],
        early_leave_violation_minutes=late_early['early_leave_violation_minutes'],
    )


def _legal_summary(work_hours, late_early):
    day = {
        'date': SATURDAY,
        'work_hours': work_hours,
        'is_friday': False,
        'is_day_off': False,
        'is_holiday': False,
        'person_status': 'P',
        'daily_duty': _minutes_to_hours(DUTY_MINUTES),
        'late_violation_minutes': late_early['late_violation_minutes'],
        'early_leave_violation_minutes': late_early['early_leave_violation_minutes'],
    }
    return build_legal_ot_summary([day], {
        'duty_hours': _minutes_to_hours(DUTY_MINUTES),
        'total_work_hours': work_hours,
    })


def test_ali_late_disabled_grace_credit_is_zero():
    """تأخیر خاموش است؛ ۱۰ دقیقه دیرآمدن فرجه نیست و کارکرد ۰۶:۵۵ می‌ماند."""
    resolved = _policy(
        late_enabled=False,
        late_allowed=0,
        early_enabled=True,
        early_allowed=15,
        include_grace=True,
    )
    late_early = _late_early(resolved, 7, 10, 14, 5)
    grace_m, work = _effective(resolved, late_early, PUNCH_MINUTES)

    assert late_early['late_minutes'] == 0
    assert late_early['early_leave_minutes'] == 0
    assert grace_m == 0
    assert _hours_to_minutes(work) == PUNCH_MINUTES

    surplus, deficit = _surplus_deficit(work, late_early)
    summary = _legal_summary(work, late_early)
    assert _hours_to_minutes(surplus) == 0
    assert _hours_to_minutes(deficit) == 5
    assert summary['overtime_total'] == pytest.approx(0.0)
    assert summary['monthly_deficit'] == pytest.approx(5 / 60)


def test_in_grace_late_added_when_switch_on():
    """تأخیر فعال با فرجه ۱۵ و ورود ۰۷:۱۰: ۱۰ دقیقه به کارکرد اضافه می‌شود."""
    resolved = _policy(
        late_enabled=True,
        late_allowed=15,
        early_enabled=True,
        early_allowed=15,
        include_grace=True,
    )
    late_early = _late_early(resolved, 7, 10, 14, 5)
    grace_m, work = _effective(resolved, late_early, PUNCH_MINUTES)

    assert late_early['is_late'] is False
    assert late_early['late_violation_minutes'] == 0
    assert grace_m == 10
    assert _hours_to_minutes(work) == 425

    surplus, deficit = _surplus_deficit(work, late_early)
    summary = _legal_summary(work, late_early)
    assert _hours_to_minutes(surplus) == 5
    assert _hours_to_minutes(deficit) == 0
    assert summary['overtime_total'] == pytest.approx(5 / 60)
    assert summary['monthly_deficit'] == pytest.approx(0.0)
    assert summary['total_late_violation'] == pytest.approx(0.0)


def test_switch_off_keeps_punch_hours():
    resolved = _policy(
        late_enabled=True,
        late_allowed=15,
        early_enabled=True,
        early_allowed=15,
        include_grace=False,
    )
    late_early = _late_early(resolved, 7, 10, 14, 5)
    grace_m, work = _effective(resolved, late_early, PUNCH_MINUTES)

    assert grace_m == 10
    assert _hours_to_minutes(work) == PUNCH_MINUTES

    surplus, deficit = _surplus_deficit(work, late_early)
    summary = _legal_summary(work, late_early)
    assert _hours_to_minutes(surplus) == 0
    assert _hours_to_minutes(deficit) == 5
    assert summary['overtime_total'] == pytest.approx(0.0)
    assert summary['monthly_deficit'] == pytest.approx(5 / 60)


def test_over_grace_credits_nothing_and_keeps_full_violation():
    """ورود ۰۷:۲۵ با فرجه ۱۵: اعتبار صفر و کل ۲۵ دقیقه تخلف است."""
    resolved = _policy(
        late_enabled=True,
        late_allowed=15,
        early_enabled=True,
        early_allowed=15,
        include_grace=True,
    )
    # 07:25 → 14:05 = 6:40
    punch = 6 * 60 + 40
    late_early = _late_early(resolved, 7, 25, 14, 5)
    grace_m, work = _effective(resolved, late_early, punch)

    assert late_early['is_late'] is True
    assert late_early['late_violation_minutes'] == 25
    assert grace_m == 0
    assert _hours_to_minutes(work) == punch

    surplus, deficit = _surplus_deficit(work, late_early)
    summary = _legal_summary(work, late_early)
    # کمبود کارکرد ۲۰ دقیقه (۷:۰۰ − ۶:۴۰) + تخلف ۲۵ دقیقه
    assert _hours_to_minutes(surplus) == 0
    assert _hours_to_minutes(deficit) == 20 + 25
    assert summary['overtime_total'] == pytest.approx(0.0)
    assert summary['monthly_deficit'] == pytest.approx((20 + 25) / 60)
    assert summary['total_late_violation'] == pytest.approx(25 / 60)


def test_summary_card_splits_punch_grace_and_sum():
    """کارت خلاصه کارکرد واقعی، فرجه و جمع آن‌ها را جدا نشان می‌دهد."""
    punch = _minutes_to_hours(PUNCH_MINUTES)
    grace_m = 10
    work = _minutes_to_hours(PUNCH_MINUTES + grace_m)
    days = [{
        'date': SATURDAY,
        'work_hours': work,
        'punch_hours': punch,
        'grace_credit_minutes': grace_m,
        'is_friday': False,
        'is_holiday': False,
        'is_day_off': False,
        'person_status': 'P',
        'daily_duty': _minutes_to_hours(DUTY_MINUTES),
    }]
    totals = punch_grace_totals(days)
    assert _hours_to_minutes(totals['total_punch_hours']) == PUNCH_MINUTES
    assert _hours_to_minutes(totals['total_grace_hours']) == grace_m
    assert _hours_to_minutes(totals['total_punch_grace_hours']) == PUNCH_MINUTES + grace_m

    summary = build_legal_ot_summary(days, {
        'duty_hours': _minutes_to_hours(DUTY_MINUTES),
        'total_work_hours': work,
    })
    assert summary['grace_included_in_work'] is True
    assert _hours_to_minutes(summary['total_punch_grace_hours']) == _hours_to_minutes(
        summary['total_work_hours']
    )
