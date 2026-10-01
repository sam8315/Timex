"""
گزارش ماهانه اضافه‌کار قانونی — تبصره ۱ ماده ۵۱ قانون کار.

اضافه‌کار پرداختی = max(0, کارکرد هفته − موظفی هفته)
- کارکرد هفته: همهٔ روزها از جمله جمعه
- موظفی هفته: جمع daily_duty روزها (Effective Required از Policy؛
  مرخصی/HL/مأموریت/HM/استراحت/تعطیل رسمی موظفی را کم یا صفر می‌کنند)
- جمعه‌کاری و تعطیل‌کاری سطل جدا با نرخ متفاوت؛ از مبنای اضافه‌کار هفتگی
کسر می‌شوند تا دوباره‌شماری نشود.
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
    """اضافه‌کار هفته = max(0, کارکرد − جمعه − تعطیل‌کاری − Σdaily_duty)."""
    n_calendar = len(week_days)
    n_duty_days = count_duty_bearing_days(week_days)
    threshold_m = weekly_required_minutes(week_days)

    work_total_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0) for d in week_days
    )
    friday_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0)
        for d in week_days
        if _is_friday_work_day(d)
    )
    holiday_work_m = sum(
        _hours_to_minutes(d.get('work_hours') or 0)
        for d in week_days
        if _is_holiday_work_day(d)
    )
    # مبنای اضافه‌کار عادی: بدون جمعه و تعطیل‌کاری (سطل‌های جدا)
    work_base_m = work_total_m - friday_m - holiday_work_m

    if threshold_m > 0 and work_base_m > threshold_m:
        week_ot_m = work_base_m - threshold_m
    else:
        week_ot_m = 0

    duty_h = _minutes_to_hours(threshold_m)
    work_total_h = _minutes_to_hours(work_total_m)
    work_base_h = _minutes_to_hours(work_base_m)
    friday_h = _minutes_to_hours(friday_m)
    holiday_work_h = _minutes_to_hours(holiday_work_m)
    weekly_h = _minutes_to_hours(week_ot_m)

    if n_duty_days > 0 and threshold_m == n_duty_days * WORKING_DAY_DUTY_MINUTES:
        if n_duty_days >= 6:
            duty_note = f'{n_duty_days}×۷:۲۰ = ۴۴'
        else:
            duty_note = f'{n_duty_days}×۷:۲۰'
    else:
        duty_note = f'Σ موظفی ({n_duty_days} روز)'

    parts = [_fmt_hhmm(work_total_h)]
    if friday_m > 0:
        parts.append(_fmt_hhmm(friday_h))
    if holiday_work_m > 0:
        parts.append(_fmt_hhmm(holiday_work_h))
    parts.append(_fmt_hhmm(duty_h))
    formula = f"max(0, {' − '.join(parts)}) = {_fmt_hhmm(weekly_h)}"

    return {
        'day_count': n_calendar,
        'working_day_count': n_duty_days,
        'duty_hours': duty_h,
        'duty_note': duty_note,
        'work_hours': work_total_h,
        'work_base_hours': work_base_h,
        'friday_hours': friday_h,
        'holiday_work_hours': holiday_work_h,
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

    friday_days = [d for d in days if _is_friday_work_day(d)]
    friday_work_hours = _minutes_to_hours(
        sum(_hours_to_minutes(d.get('work_hours') or 0) for d in friday_days)
    )
    friday_work_days = len(friday_days)

    holiday_work_days_list = [d for d in days if _is_holiday_work_day(d)]
    holiday_work_hours = _minutes_to_hours(
        sum(
            _hours_to_minutes(d.get('work_hours') or 0)
            for d in holiday_work_days_list
        )
    )
    holiday_work_days = len(holiday_work_days_list)

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
    late_v_m = sum(int(d.get('late_violation_minutes') or 0) for d in days)
    early_v_m = sum(int(d.get('early_leave_violation_minutes') or 0) for d in days)
    # کسری ماهانه = کمبود کارکرد نسبت به موظفی + تخلف تأخیر/تعجیل
    monthly_deficit = _minutes_to_hours(max(0, duty_m - work_m) + late_v_m + early_v_m)

    # حضور = هر روز با وضعیت P (جمعه/تعطیل‌کاری هم شمرده می‌شود)
    present_days = sum(1 for d in days if d.get('person_status') == 'P')
    leave_days = sum(1 for d in days if d.get('person_status') == 'L')
    absent_days = sum(1 for d in days if d.get('person_status') == 'A')
    rest_days = sum(1 for d in days if d.get('person_status') == 'R')
    holiday_days = sum(1 for d in days if d.get('person_status') == 'H')
    mission_days = sum(1 for d in days if d.get('person_status') == 'M')
    status_days_total = (
        present_days + leave_days + absent_days
        + rest_days + holiday_days + mission_days
    )

    overtime_holiday_total = _minutes_to_hours(
        _hours_to_minutes(overtime_total) + _hours_to_minutes(holiday_work_hours)
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

    summary.update({
        'hourly_overtime': 0.0,
        'daily_overtime': 0.0,
        'weekly_overtime': weekly,
        'overtime_total': overtime_total,
        'friday_work_hours': friday_work_hours,
        'friday_work_days': friday_work_days,
        'holiday_work_hours': holiday_work_hours,
        'holiday_work_days': holiday_work_days,
        'overtime_holiday_total': overtime_holiday_total,
        'total_morning': total_morning,
        'total_evening': total_evening,
        'total_night': total_night,
        'morning_percent': morning_percent,
        'evening_percent': evening_percent,
        'night_percent': night_percent,
        'total_work_days': total_work_days,
        'present_days': present_days,
        'leave_days': leave_days,
        'absent_days': absent_days,
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
        'total_late_violation': _minutes_to_hours(late_v_m),
        'total_early_leave_violation': _minutes_to_hours(early_v_m),
        'total_late_violation_minutes': late_v_m,
        'total_early_leave_violation_minutes': early_v_m,
        'total_surplus': overtime_total,
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

    def generate_report(self, user_id: str, year: int, month: int) -> Dict:
        report = self._v2.generate_detailed_report(user_id, year, month)
        if not report.get('success'):
            return report

        days = report.get('days') or []
        report['summary'] = build_legal_ot_summary(days, report.get('summary') or {})
        report['report_kind'] = 'legal_ot'
        report['report_title'] = 'گزارش اضافه‌کار قانونی'
        return report
