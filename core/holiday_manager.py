"""
ماژول مدیریت تعطیلات
- تشخیص خودکار جمعه‌ها
- افزودن تعطیلات دستی
"""
from datetime import date, timedelta
from typing import List, Dict, Optional
from sqlalchemy import and_, extract
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.holiday import Holiday


class HolidayManager:
    """مدیریت تعطیلات"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def is_friday(self, target_date: date) -> bool:
        """بررسی اینکه آیا یک تاریخ جمعه است"""
        return target_date.weekday() == 4  # 0=دوشنبه ... 4=جمعه

    def is_holiday(self, target_date: date) -> bool:
        """
        بررسی اینکه آیا یک تاریخ تعطیل است
        (جمعه یا تعطیل ثبت شده)
        """
        # جمعه همیشه تعطیل است
        if self.is_friday(target_date):
            return True

        # بررسی تعطیلات ثبت شده
        holiday = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).first()

        return holiday is not None

    def get_holiday_info(self, target_date: date) -> Dict:
        """دریافت اطلاعات تعطیلی یک تاریخ"""
        if self.is_friday(target_date):
            return {
                'is_holiday': True,
                'type': 'friday',
                'title': 'جمعه'
            }

        holiday = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).first()

        if holiday:
            return {
                'is_holiday': True,
                'type': 'custom',
                'title': holiday.title,
                'is_national': holiday.is_national
            }

        return {
            'is_holiday': False,
            'type': None,
            'title': None
        }

    def add_holiday(
        self,
        holiday_date: date,
        title: str,
        is_national: bool = True
    ) -> Dict:
        """افزودن تعطیلی"""
        # بررسی جمعه بودن
        if self.is_friday(holiday_date):
            return {
                'success': False,
                'message': '⚠️  این تاریخ جمعه است و به طور خودکار تعطیل محسوب می‌شود'
            }

        # بررسی تکراری بودن
        existing = self.db.query(Holiday).filter(
            Holiday.holiday_date == holiday_date
        ).first()

        if existing:
            return {
                'success': False,
                'message': f'⚠️  این تاریخ قبلاً به عنوان تعطیلی ثبت شده: {existing.title}'
            }

        try:
            holiday = Holiday(
                holiday_date=holiday_date,
                title=title,
                is_national=is_national
            )
            self.db.add(holiday)
            self.db.commit()

            j_date = jdatetime.date.fromgregorian(date=holiday_date)
            return {
                'success': True,
                'message': f'✅ تعطیلی "{title}" برای تاریخ {j_date.strftime("%Y/%m/%d")} ثبت شد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def delete_holiday(self, holiday_id: int) -> Dict:
        """حذف تعطیلی"""
        try:
            holiday = self.db.query(Holiday).filter(Holiday.id == holiday_id).first()
            if not holiday:
                return {'success': False, 'message': '❌ تعطیلی یافت نشد'}

            j_date = jdatetime.date.fromgregorian(date=holiday.holiday_date)
            title = holiday.title

            self.db.delete(holiday)
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ تعطیلی "{title}" ({j_date.strftime("%Y/%m/%d")}) حذف شد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_holidays_in_range(
        self,
        from_date: date,
        to_date: date
    ) -> List[Dict]:
        """دریافت تعطیلات در یک بازه زمانی (شامل جمعه‌ها)"""
        holidays = []
        current = from_date

        while current <= to_date:
            info = self.get_holiday_info(current)
            if info['is_holiday']:
                holidays.append({
                    'date': current,
                    'type': info['type'],
                    'title': info['title'],
                    'is_national': info.get('is_national', True)
                })
            current += timedelta(days=1)

        return sorted(holidays, key=lambda x: x['date'])

    def get_custom_holidays(self, year: Optional[int] = None) -> List[Holiday]:
        """دریافت تعطیلات ثبت شده (غیر جمعه)"""
        query = self.db.query(Holiday)

        if year:
            query = query.filter(extract('year', Holiday.holiday_date) == year)

        return query.order_by(Holiday.holiday_date).all()

    def count_working_days(self, from_date: date, to_date: date) -> Dict:
        """شمارش روزهای کاری و تعطیل در یک بازه"""
        total_days = 0
        working_days = 0
        holidays_count = 0
        fridays_count = 0

        current = from_date
        while current <= to_date:
            total_days += 1
            if self.is_friday(current):
                fridays_count += 1
            elif self.is_holiday(current):
                holidays_count += 1
            else:
                working_days += 1
            current += timedelta(days=1)

        return {
            'total_days': total_days,
            'working_days': working_days,
            'holidays': holidays_count,
            'fridays': fridays_count
        }