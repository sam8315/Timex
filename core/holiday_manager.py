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

    def _delete_holiday(self):
        """حذف تعطیلی"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 70)
        print("  🗑️  حذف تعطیلی")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال (شمسی) [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = HolidayManager()
        try:
            # ✅ تبدیل سال شمسی به بازه میلادی
            j_from = jdatetime.date(year, 1, 1)
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

            g_from = j_from.togregorian()
            g_to = j_to.togregorian()

            # ✅ دریافت تعطیلات ثبت شده در بازه میلادی
            holidays = manager.db.query(Holiday).filter(
                and_(
                    Holiday.holiday_date >= g_from,
                    Holiday.holiday_date <= g_to
                )
            ).order_by(Holiday.holiday_date).all()

            if not holidays:
                print(f"\n  ⚠️  هیچ تعطیلی ثبت شده‌ای در سال {year} وجود ندارد")
                print("  💡 توجه: جمعه‌ها به صورت خودکار تعطیل هستند و قابل حذف نیستند")
                return

            # نمایش لیست
            print(f"\n  📋 تعطیلات ثبت شده در سال {year} ({len(holidays)} مورد):")
            print("  " + "-" * 70)
            print(f"  {'#':<4} {'شناسه':<8} {'تاریخ شمسی':<12} {'روز هفته':<10} {'نوع':<8} {'عنوان':<25}")
            print("  " + "-" * 70)

            for i, h in enumerate(holidays, 1):
                j_date = jdatetime.date.fromgregorian(date=h.holiday_date)
                day_name = self._get_day_name(h.holiday_date)
                national = "ملی" if h.is_national else "محدود"
                print(f"  {i:<4} {h.id:<8} {j_date.strftime('%Y/%m/%d'):<12} {day_name:<10} {national:<8} {h.title:<25}")

            print("  " + "-" * 70)

            # انتخاب
            choice = input("\n  شماره تعطیلی برای حذف (یا 0 برای انصراف): ").strip()
            if choice == '0' or not choice:
                print("  ❌ عملیات لغو شد")
                return

            try:
                idx = int(choice) - 1
            except ValueError:
                print("  ❌ شماره نامعتبر")
                return

            if idx < 0 or idx >= len(holidays):
                print("  ❌ شماره خارج از محدوده")
                return

            selected = holidays[idx]
            j_selected = jdatetime.date.fromgregorian(date=selected.holiday_date)
            day_name = self._get_day_name(selected.holiday_date)

            # تایید نهایی
            print("\n" + "-" * 70)
            print("  ⚠️  آیا مطمئن هستید که می‌خواهید این تعطیلی را حذف کنید؟")
            print(f"     • شناسه   : {selected.id}")
            print(f"     • تاریخ   : {j_selected.strftime('%Y/%m/%d')} ({day_name})")
            print(f"     • عنوان   : {selected.title}")
            print(f"     • نوع     : {'ملی' if selected.is_national else 'محدود'}")
            print("-" * 70)

            confirm = input("  تایید حذف (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            result = manager.delete_holiday(selected.id)
            print(f"\n  {result['message']}")

        finally:
            manager.close()
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
        """
        دریافت تعطیلات ثبت شده (غیر جمعه)
        year: سال شمسی
        """
        if year:
            # ✅ تبدیل سال شمسی به بازه میلادی
            import jdatetime
            j_from = jdatetime.date(year, 1, 1)
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

            g_from = j_from.togregorian()
            g_to = j_to.togregorian()

            return self.db.query(Holiday).filter(
                and_(
                    Holiday.holiday_date >= g_from,
                    Holiday.holiday_date <= g_to
                )
            ).order_by(Holiday.holiday_date).all()

        return self.db.query(Holiday).order_by(Holiday.holiday_date).all()
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