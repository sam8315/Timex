"""
ماژول محاسبه ساعات کاری تفکیکی (صبح/عصر/شب)
بازه‌ها:
  صبح: 06:00 تا 14:00
  عصر: 14:00 تا 22:00
  شب: 22:00 تا 06:00
"""
from datetime import datetime, timedelta


def calculate_shift_hours(start_time: datetime, end_time: datetime) -> dict:
    """
    محاسبه ساعات کاری تفکیکی
    """
    if not start_time or not end_time or start_time >= end_time:
        return {'morning': 0.0, 'evening': 0.0, 'night': 0.0, 'total': 0.0}

    morning_hours = 0.0
    evening_hours = 0.0
    night_hours = 0.0

    # ✅ تعریف بازه‌های روزانه
    # هر روز 3 بازه دارد: صبح(6-14)، عصر(14-22)، شب(22-6فردا)

    # محاسبه تعداد روزهای درگیر
    total_seconds = (end_time - start_time).total_seconds()

    # ✅ روش ساده‌تر: هر دقیقه را بررسی کن
    current = start_time
    step = timedelta(minutes=1)

    while current < end_time:
        hour = current.hour

        if 6 <= hour < 14:
            morning_hours += 1
        elif 14 <= hour < 22:
            evening_hours += 1
        else:  # 22-23 یا 0-5
            night_hours += 1

        current += step

    # تبدیل دقیقه به ساعت
    morning_hours = round(morning_hours / 60, 2)
    evening_hours = round(evening_hours / 60, 2)
    night_hours = round(night_hours / 60, 2)
    total = round(morning_hours + evening_hours + night_hours, 2)

    return {
        'morning': morning_hours,
        'evening': evening_hours,
        'night': night_hours,
        'total': total
    }