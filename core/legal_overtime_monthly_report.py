"""
گزارش ماهانه اضافه‌کار قانونی — تبصره ۱ ماده ۵۱ قانون کار.

اضافه‌کار پرداختی = max(0, کارکرد هفته − موظفی هفته)
- کارکرد هفته: همهٔ روزها از جمله جمعه
- موظفی هفته: جمع daily_duty روزها (Effective Required از Policy؛
  مرخصی/HL/مأموریت/HM/استراحت/تعطیل رسمی موظفی را کم یا صفر می‌کنند)
- جمعه‌کاری سطل جدا با نرخ متفاوت؛ از مبنای اضافه‌کار هفتگی کسر می‌شود
تا دوباره‌شماری نشود.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from core.detailed_monthly_report_v2 import (
    DetailedMonthlyReportGeneratorV2,
    _hours_to_minutes,
    _minutes_to_hours,
)

WEEKLY_REQUIRED_HOURS = 44.0
# Fallback وقتی daily_duty روی روز نباشد (تست‌های واحد / داده ناقص)
WORKING_DAY_DUTY_MINUTES = 440
# ضرایب پرداختی (نمایش در گزارش)
OVERTIME_COEFFICIENT = 1.4
FRIDAY_WORK_COEFFICIENT = 1.96


def count_duty_bearing_days(week_days: List[Dict]) -> int:
    """روزهایی که هنوز موظفی دارند (پس از کسر مرخصی/تعطیل/…)."""
    return sum(
        1 for d in week_days
        if _hours_to_minutes(d.get('daily_duty') or 0) > 0
    )


def weekly_required_minutes(week_days: List[Dict]) -> int:
    """موظفی هفتگی = جمع موظفی مؤثر روزها.

    اولویت با Policy/Effective Required روی هر روز (`daily_duty` از موتور V2):
    مرخصی روزانه، HL، مأموریت، HM، استراحت، تعطیل رسمی و روز غیرکاری Policy
    موظفی همان روز را صفر یا کم می‌کنند.
    """
    total = sum(_hours_to_minutes(d.get('daily_duty') or 0) for d in week_days)
    if total > 0:
        return total

    # Fallback نادر: اگر هیچ daily_duty ست نشده، روزهای غیرجمعهٔ بدون وضعیت معاف
    n = 0
    for d in week_days:
        if d.get('is_friday') or d.get('is_holiday') or d.get('is_day_off'):
            continue
        if d.get('person_status') in ('L', 'R', 'M', 'H'):
            continue
        n += 1
    return n * WORKING_DAY_DUTY_MINUTES


# نام قدیمی برای سازگاری تست/فراخوانی
def proportional_weekly_required_minutes(week_days: List[Dict]) -> int:
    return weekly_required_minutes(week_days)


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


def _week_metrics(week_days: List[Dict]) -> Dict:
    """اضافه‌کار هفته = max(0, کارکرد − جمعه − Σdaily_duty)."""
    n_calendar = len(week_days)
    n_duty_days = count_duty_bearing_days(week_days)
    threshold_m = weekly_required_minutes(week_days)

    work_total_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0) for d in week_days
    )
    friday_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0)
        for d in week_days
        if d.get('is_friday')
    )
    # مبنای اضافه‌کار عادی: کارکرد منهای جمعه (جمعه سطل جدا با ضریب ۱٫۹۶)
    work_base_m = work_total_m - friday_m

    if threshold_m > 0 and work_base_m > threshold_m:
        week_ot_m = work_base_m - threshold_m
    else:
        week_ot_m = 0

    duty_h = _minutes_to_hours(threshold_m)
    work_total_h = _minutes_to_hours(work_total_m)
    work_base_h = _minutes_to_hours(work_base_m)
    friday_h = _minutes_to_hours(friday_m)
    weekly_h = _minutes_to_hours(week_ot_m)

    if n_duty_days > 0 and threshold_m == n_duty_days * WORKING_DAY_DUTY_MINUTES:
        if n_duty_days >= 6:
            duty_note = f'{n_duty_days}×۷:۲۰ = ۴۴'
        else:
            duty_note = f'{n_duty_days}×۷:۲۰'
    else:
        duty_note = f'Σ موظفی ({n_duty_days} روز)'

    if friday_m > 0:
        formula = (
            f"max(0, {_fmt_hhmm(work_total_h)} − {_fmt_hhmm(friday_h)} − "
            f"{_fmt_hhmm(duty_h)}) = {_fmt_hhmm(weekly_h)}"
        )
    else:
        formula = (
            f"max(0, {_fmt_hhmm(work_base_h)} − {_fmt_hhmm(duty_h)}) "
            f"= {_fmt_hhmm(weekly_h)}"
        )

    return {
        'day_count': n_calendar,
        'working_day_count': n_duty_days,
        'duty_hours': duty_h,
        'duty_note': duty_note,
        'work_hours': work_total_h,
        'work_base_hours': work_base_h,
        'friday_hours': friday_h,
        'hourly_overtime': 0.0,
        'weekly_overtime': weekly_h,
        'formula': formula,
    }


def calculate_weekly_overtime(days: List[Dict]) -> float:
    """جمع اضافه‌کار هفتگی؛ بلوک هفته روی اولین روز با rowspan."""
    weeks: Dict = {}
    for day in days:
        start = week_start_saturday(day['date'])
        weeks.setdefault(start, []).append(day)

    ordered_starts = sorted(weeks.keys())
    weekly_m = 0
    for start in ordered_starts:
        week_days = sorted(weeks[start], key=lambda d: d['date'])
        metrics = _week_metrics(week_days)
        weekly_m += _hours_to_minutes(metrics['weekly_overtime'])
        first = week_days[0]
        for d in week_days:
            d['week_overtime'] = metrics['weekly_overtime']
            d['week_rowspan'] = 0
            d['week_block'] = None
        first['week_rowspan'] = len(week_days)
        first['week_block'] = metrics
    return _minutes_to_hours(weekly_m)


def build_legal_ot_summary(days: List[Dict], base_summary: Dict) -> Dict:
    """خلاصهٔ پرداختی — overtime_total = جمع weekly_overtime."""
    for day in days:
        day['week_overtime'] = 0.0
        day['week_rowspan'] = 0
        day['week_block'] = None
        day['hourly_overtime'] = 0.0
        day['surplus'] = 0.0
        day['deficit'] = 0.0
        day['daily_excess_over_8'] = 0.0

    weekly = calculate_weekly_overtime(days)
    overtime_total = weekly

    friday_days = [
        d for d in days
        if d.get('is_friday') and d.get('person_status') == 'P'
    ]
    friday_work_hours = _minutes_to_hours(
        sum(_hours_to_minutes(d.get('work_hours') or 0) for d in friday_days)
    )
    friday_work_days = len(friday_days)

    # روزهایی که واقعاً کارکرد داشته‌اند
    total_work_days = sum(
        1 for d in days if _hours_to_minutes(d.get('work_hours') or 0) > 0
    )
    hourly_leave_minutes = sum(int(d.get('hourly_leave_minutes') or 0) for d in days)
    hourly_mission_minutes = sum(
        int(d.get('hourly_mission_minutes') or 0) for d in days
    )

    summary = dict(base_summary)
    duty_m = _hours_to_minutes(summary.get('duty_hours') or 0)
    work_m = _hours_to_minutes(summary.get('total_work_hours') or 0)
    monthly_deficit = _minutes_to_hours(max(0, duty_m - work_m))

    summary.update({
        'hourly_overtime': 0.0,
        'daily_overtime': 0.0,
        'weekly_overtime': weekly,
        'overtime_total': overtime_total,
        'friday_work_hours': friday_work_hours,
        'friday_work_days': friday_work_days,
        'total_work_days': total_work_days,
        'hourly_leave_minutes': hourly_leave_minutes,
        'hourly_leave_hours': _minutes_to_hours(hourly_leave_minutes),
        'hourly_mission_minutes': hourly_mission_minutes,
        'hourly_mission_hours': _minutes_to_hours(hourly_mission_minutes),
        'monthly_deficit': monthly_deficit,
        'total_deficit': monthly_deficit,
        'total_surplus': overtime_total,
        'overtime_coefficient': OVERTIME_COEFFICIENT,
        'friday_work_coefficient': FRIDAY_WORK_COEFFICIENT,
    })
    return summary


class LegalOvertimeMonthlyReportGenerator:
    """تولید گزارش ماهانه با اضافه‌کار قانونی."""

    def __init__(self):
        self._v2 = DetailedMonthlyReportGeneratorV2()

    def close(self):
        self._v2.close()

    def generate_report(self, user_id: str, year: int, month: int) -> Dict:
        report = self._v2.generate_detailed_report(user_id, year, month)
        if not report.get('success'):
            return report

        days = report.get('days') or []
        report['summary'] = build_legal_ot_summary(days, report.get('summary') or {})
        report['report_kind'] = 'legal_ot'
        report['report_title'] = 'گزارش اضافه‌کار قانونی'
        return report
