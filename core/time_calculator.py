"""
ماژول محاسبه ساعات کاری تفکیکی (صبح/عصر/شب)
"""
from datetime import datetime, timedelta


def calculate_shift_hours(start_time: datetime, end_time: datetime) -> dict:
    """
    محاسبه ساعات کاری تفکیکی بر اساس بازه‌های:
    - صبح: 06:00 تا 14:00
    - عصر: 14:00 تا 22:00
    - شب: 22:00 تا 06:00

    Returns:
        dict: شامل morning, evening, night, total
    """
    if not start_time or not end_time or start_time >= end_time:
        return {'morning': 0.0, 'evening': 0.0, 'night': 0.0, 'total': 0.0}

    morning_hours = 0.0
    evening_hours = 0.0
    night_hours = 0.0

    current = start_time

    while current < end_time:
        # تعیین بازه فعلی
        if current.hour < 6:
            # شب: 22:00 تا 06:00
            shift_start = (current - timedelta(days=1)).replace(hour=22, minute=0, second=0)
            shift_end = current.replace(hour=6, minute=0, second=0)
            shift_type = 'night'
        elif current.hour < 14:
            # صبح: 06:00 تا 14:00
            shift_start = current.replace(hour=6, minute=0, second=0)
            shift_end = current.replace(hour=14, minute=0, second=0)
            shift_type = 'morning'
        elif current.hour < 22:
            # عصر: 14:00 تا 22:00
            shift_start = current.replace(hour=14, minute=0, second=0)
            shift_end = current.replace(hour=22, minute=0, second=0)
            shift_type = 'evening'
        else:
            # شب: 22:00 تا 06:00
            shift_start = current.replace(hour=22, minute=0, second=0)
            shift_end = (current + timedelta(days=1)).replace(hour=6, minute=0, second=0)
            shift_type = 'night'

        # محاسبه اشتراک
        intersect_start = max(current, shift_start)
        intersect_end = min(end_time, shift_end)

        if intersect_start < intersect_end:
            delta = (intersect_end - intersect_start).total_seconds() / 3600.0

            if shift_type == 'morning':
                morning_hours += delta
            elif shift_type == 'evening':
                evening_hours += delta
            else:  # night
                night_hours += delta

        # حرکت به پایان این بازه
        current = shift_end

    total = morning_hours + evening_hours + night_hours

    return {
        'morning': round(morning_hours, 2),
        'evening': round(evening_hours, 2),
        'night': round(night_hours, 2),
        'total': round(total, 2)
    }