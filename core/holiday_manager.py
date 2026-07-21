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

    def is_holiday(self, target_date: date, user_group_id: Optional[str] = None) -> bool:
        """
        بررسی اینکه آیا یک تاریخ تعطیل است

        Args:
            target_date: تاریخ مورد بررسی
            user_group_id: گروه کاربر (اختیاری)
        """
        # جمعه همیشه تعطیل است
        if self.is_friday(target_date):
            return True

        # بررسی تعطیلات ثبت شده
        holidays = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).all()

        for holiday in holidays:
            # اگر تعطیل ملی باشد (group_id = None)
            if holiday.group_id is None:
                return True
            # اگر تعطیل گروهی باشد و گروه کاربر مطابقت داشته باشد
            elif user_group_id and holiday.group_id == user_group_id:
                return True

        return False

    def get_holiday_info(self, target_date: date, user_group_id: Optional[str] = None) -> Dict:
        """دریافت اطلاعات تعطیلی یک تاریخ"""
        if self.is_friday(target_date):
            return {
                'is_holiday': True,
                'type': 'friday',
                'title': 'جمعه',
                'group_id': None
            }

        holidays = self.db.query(Holiday).filter(
            Holiday.holiday_date == target_date
        ).all()

        for holiday in holidays:
            # تعطیل ملی
            if holiday.group_id is None:
                return {
                    'is_holiday': True,
                    'type': 'custom',
                    'title': holiday.title,
                    'is_national': holiday.is_national,
                    'group_id': None
                }
            # تعطیل گروهی
            elif user_group_id and holiday.group_id == user_group_id:
                return {
                    'is_holiday': True,
                    'type': 'group',
                    'title': holiday.title,
                    'is_national': False,
                    'group_id': holiday.group_id
                }

        return {
            'is_holiday': False,
            'type': None,
            'title': None,
            'group_id': None
        }

    def add_holiday(
            self,
            holiday_date: date,
            title: str,
            is_national: bool = True,
            group_id: Optional[str] = None
    ) -> Dict:
        """
        افزودن تعطیلی

        Args:
            holiday_date: تاریخ تعطیلی
            title: عنوان
            is_national: آیا ملی است؟
            group_id: شناسه گروه (اگر تعطیل گروهی باشد)
        """
        # بررسی جمعه بودن
        if self.is_friday(holiday_date):
            return {
                'success': False,
                'message': '⚠️  این تاریخ جمعه است و به طور خودکار تعطیل محسوب می‌شود'
            }

        # بررسی تکراری بودن (همان تاریخ و همان گروه)
        if group_id:
            existing = self.db.query(Holiday).filter(
                and_(
                    Holiday.holiday_date == holiday_date,
                    Holiday.group_id == group_id
                )
            ).first()
        else:
            existing = self.db.query(Holiday).filter(
                and_(
                    Holiday.holiday_date == holiday_date,
                    Holiday.group_id == None
                )
            ).first()

        if existing:
            return {
                'success': False,
                'message': f'⚠️  این تعطیلی قبلاً ثبت شده: {existing.title}'
            }

        try:
            holiday = Holiday(
                holiday_date=holiday_date,
                title=title,
                is_national=is_national,
                group_id=group_id
            )
            self.db.add(holiday)
            self.db.commit()

            j_date = jdatetime.date.fromgregorian(date=holiday_date)
            group_display = "ملی" if group_id is None else f"گروه {group_id}"

            return {
                'success': True,
                'message': f'✅ تعطیلی "{title}" برای {j_date.strftime("%Y/%m/%d")} ({group_display}) ثبت شد'
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
            if self.is_friday(current):
                holidays.append({
                    'date': current,
                    'type': 'friday',
                    'title': 'جمعه',
                    'group_id': None
                })
            else:
                # دریافت تمام تعطیلات این روز
                day_holidays = self.db.query(Holiday).filter(
                    Holiday.holiday_date == current
                ).all()

                for h in day_holidays:
                    if h.group_id is None:
                        holidays.append({
                            'date': current,
                            'type': 'custom',
                            'title': h.title,
                            'is_national': h.is_national,
                            'group_id': None
                        })
                    else:
                        holidays.append({
                            'date': current,
                            'type': 'group',
                            'title': h.title,
                            'is_national': False,
                            'group_id': h.group_id
                        })

            current += timedelta(days=1)

        return sorted(holidays, key=lambda x: x['date'])

    def get_custom_holidays(self, year: Optional[int] = None, group_id: Optional[str] = None) -> List[Holiday]:
        """
        دریافت تعطیلات ثبت شده (غیر جمعه)

        Args:
            year: سال شمسی
            group_id: فیلتر بر اساس گروه (None = همه)
        """
        query = self.db.query(Holiday)

        if year:
            import jdatetime
            j_from = jdatetime.date(year, 1, 1)
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

            g_from = j_from.togregorian()
            g_to = j_to.togregorian()

            query = query.filter(
                and_(
                    Holiday.holiday_date >= g_from,
                    Holiday.holiday_date <= g_to
                )
            )

        if group_id is not None:
            query = query.filter(Holiday.group_id == group_id)

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