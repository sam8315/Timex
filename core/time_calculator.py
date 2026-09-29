"""
ماژول محاسبه ساعات کاری تفکیکی (صبح/عصر/شب)
بازه‌ها:
  صبح: 06:00 تا 14:00
  عصر: 14:00 تا 22:00
  شب: 22:00 تا 06:00
"""
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional


def calculate_shift_hours(start_time: datetime, end_time: datetime) -> dict:
    """
    محاسبه ساعات کاری تفکیکی برای *یک* بازهٔ پیوسته ورود→خروج.
    """
    if not start_time or not end_time or start_time >= end_time:
        return {'morning': 0.0, 'evening': 0.0, 'night': 0.0, 'total': 0.0}

    morning_minutes = 0
    evening_minutes = 0
    night_minutes = 0

    current = start_time
    step = timedelta(minutes=1)

    while current < end_time:
        hour = current.hour

        if 6 <= hour < 14:
            morning_minutes += 1
        elif 14 <= hour < 22:
            evening_minutes += 1
        else:  # 22-23 یا 0-5
            night_minutes += 1

        current += step

    morning_hours = round(morning_minutes / 60, 2)
    evening_hours = round(evening_minutes / 60, 2)
    night_hours = round(night_minutes / 60, 2)
    total = round(morning_hours + evening_hours + night_hours, 2)

    return {
        'morning': morning_hours,
        'evening': evening_hours,
        'night': night_hours,
        'total': total
    }


def sum_shift_hours_from_pairs(
    pairs: Optional[Iterable[Mapping]] = None,
) -> dict:
    """
    تفکیک صبح/عصر/شب روی *همه* جفت‌های ورود/خروج.

    نباید از first_enter→last_exit یک‌جا حساب شود؛ فاصلهٔ بین جفت‌ها
    (مثلاً ناهار بین دو بازه در جمعه) کار محسوب نمی‌شود.
    """
    morning_minutes = 0
    evening_minutes = 0
    night_minutes = 0
    step = timedelta(minutes=1)

    for pair in pairs or []:
        start_time = pair.get('enter') if isinstance(pair, Mapping) else None
        end_time = pair.get('exit') if isinstance(pair, Mapping) else None
        if not start_time or not end_time or start_time >= end_time:
            continue

        current = start_time
        while current < end_time:
            hour = current.hour
            if 6 <= hour < 14:
                morning_minutes += 1
            elif 14 <= hour < 22:
                evening_minutes += 1
            else:
                night_minutes += 1
            current += step

    morning_hours = round(morning_minutes / 60, 2)
    evening_hours = round(evening_minutes / 60, 2)
    night_hours = round(night_minutes / 60, 2)
    return {
        'morning': morning_hours,
        'evening': evening_hours,
        'night': night_hours,
        'total': round(morning_hours + evening_hours + night_hours, 2),
    }
