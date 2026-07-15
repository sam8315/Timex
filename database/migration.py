"""
ماژول انتقال داده‌ها از MySQL قدیمی به PostgreSQL جدید
"""
from datetime import datetime
from typing import List, Dict, Tuple
import jdatetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.mysql_connector import MySQLConnector
from database.engine import SessionLocal
from models.user import User
from models.attendance import Attendance
from sqlalchemy.dialects.postgresql import insert


class DataMigrator:
    """مدیریت انتقال داده‌ها"""

    def __init__(self):
        self.mysql = MySQLConnector()
        self.stats = {
            'total_records': 0,
            'enter_records': 0,
            'exit_records': 0,
            'skipped_records': 0,
            'new_users': 0,
            'errors': 0,
            'duplicates': 0  # 🆕 شمارش رکوردهای تکراری
        }

    def connect_mysql(self) -> bool:
        """اتصال به MySQL"""
        return self.mysql.connect()

    def disconnect_mysql(self):
        """قطع اتصال MySQL"""
        self.mysql.disconnect()

    def _convert_jalali_to_gregorian(
            self,
            date_str: str,
            time_str: str
    ) -> datetime:
        """
        تبدیل تاریخ و زمان شمسی به میلادی

        Args:
            date_str: تاریخ شمسی (مثال: 1405/04/17)
            time_str: زمان (مثال: 08:30)

        Returns:
            datetime: زمان میلادی
        """
        # ترکیب تاریخ و زمان
        datetime_str = f"{date_str} {time_str}"

        # تبدیل از شمسی به میلادی
        jdt = jdatetime.datetime.strptime(
            datetime_str,
            "%Y/%m/%d %H:%M"
        )
        return jdt.togregorian()

    def _ensure_user_exists(
            self,
            db: Session,
            perno: int
    ) -> bool:
        """
        اطمینان از وجود کاربر در دیتابیس
        اگر کاربر وجود نداشت، یک کاربر موقت می‌سازد
        """
        # تبدیل perno به String برای تطابق با user_id
        user_id_str = str(perno)

        user = db.query(User).filter(User.user_id == user_id_str).first()

        if not user:
            # ساخت کاربر موقت با اطلاعات ناقص
            user = User(
                user_id=user_id_str,
                name=f"Unknown-{user_id_str}",
                privilege=0
            )
            db.add(user)
            try:
                db.commit()
                self.stats['new_users'] += 1
            except IntegrityError:
                db.rollback()
                return False

        return True

    def _process_single_record(
            self,
            db: Session,
            record: Dict
    ) -> Tuple[int, int]:
        """
        پردازش یک رکورد ioinfo و تبدیل به رکوردهای attendance
        با آمار دقیق (تشخیص تکراری‌ها)
        """
        from sqlalchemy.dialects.postgresql import insert

        enter_count = 0
        exit_count = 0
        perno = record['Perno']
        user_id_str = str(perno)

        # اطمینان از وجود کاربر
        if not self._ensure_user_exists(db, perno):
            self.stats['skipped_records'] += 1
            return 0, 0

        # پردازش رکورد ورود
        if record.get('EnterDate') and record.get('EnterTime'):
            try:
                timestamp = self._convert_jalali_to_gregorian(
                    record['EnterDate'],
                    record['EnterTime']
                )

                # ✅ استفاده از insert هوشمند
                stmt = insert(Attendance).values(
                    user_id=user_id_str,
                    timestamp=timestamp,
                    status=0,
                    punch=0
                ).on_conflict_do_nothing(
                    index_elements=['user_id', 'timestamp']
                )

                result = db.execute(stmt)

                # ✅ بررسی واقعاً چند رکورد درج شد
                if result.rowcount > 0:
                    self.stats['enter_records'] += 1
                    enter_count = 1
                else:
                    # رکورد تکراری بود
                    self.stats['duplicates'] += 1  # 🆕 رکورد تکراری بود

            except Exception as e:
                print(f"⚠️  خطا در تبدیل تاریخ ورود (Perno={perno}): {e}")
                self.stats['errors'] += 1

        # پردازش رکورد خروج
        if record.get('ExitDate') and record.get('ExitTime'):
            try:
                timestamp = self._convert_jalali_to_gregorian(
                    record['ExitDate'],
                    record['ExitTime']
                )

                stmt = insert(Attendance).values(
                    user_id=user_id_str,
                    timestamp=timestamp,
                    status=1,
                    punch=1
                ).on_conflict_do_nothing(
                    index_elements=['user_id', 'timestamp']
                )

                result = db.execute(stmt)

                if result.rowcount > 0:
                    self.stats['exit_records'] += 1
                    exit_count = 1
                else:
                    # رکورد تکراری بود
                    self.stats['duplicates'] += 1  # 🆕 رکورد تکراری بود

            except Exception as e:
                print(f"⚠️  خطا در تبدیل تاریخ خروج (Perno={perno}): {e}")
                self.stats['errors'] += 1

        return enter_count, exit_count

    def _process_single_record_dry(self, record: Dict) -> Tuple[int, int]:
        """
        پردازش یک رکورد در حالت dry_run (بدون نیاز به دیتابیس)
        فقط تبدیل تاریخ را تست می‌کند

        Returns:
            Tuple[int, int]: (تعداد رکوردهای ورود، تعداد رکوردهای خروج)
        """
        enter_count = 0
        exit_count = 0

        # تست تبدیل تاریخ ورود
        if record.get('EnterDate') and record.get('EnterTime'):
            try:
                self._convert_jalali_to_gregorian(
                    record['EnterDate'],
                    record['EnterTime']
                )
                enter_count = 1
            except Exception as e:
                print(f"⚠️  خطا در تبدیل تاریخ ورود (Perno={record['Perno']}): {e}")
                self.stats['errors'] += 1

        # تست تبدیل تاریخ خروج
        if record.get('ExitDate') and record.get('ExitTime'):
            try:
                self._convert_jalali_to_gregorian(
                    record['ExitDate'],
                    record['ExitTime']
                )
                exit_count = 1
            except Exception as e:
                print(f"⚠️  خطا در تبدیل تاریخ خروج (Perno={record['Perno']}): {e}")
                self.stats['errors'] += 1

        return enter_count, exit_count

    def migrate_all(self, dry_run: bool = False) -> Dict:
        """
        انتقال کامل همه داده‌ها

        Args:
            dry_run: اگر True باشد، فقط شبیه‌سازی می‌کند و ذخیره نمی‌کند

        Returns:
            Dict: آمار عملیات
        """
        print("\n" + "=" * 60)
        print("  🔄 شروع انتقال داده‌ها از MySQL به PostgreSQL")
        print("=" * 60)

        if dry_run:
            print("  ⚠️  حالت Dry Run - داده‌ای ذخیره نخواهد شد")

        # دریافت رکوردها
        print("\n📖 در حال خواندن رکوردها از MySQL...")
        records = self.mysql.get_ioinfo_records()
        total = len(records)
        self.stats['total_records'] = total

        if total == 0:
            print("⚠️  هیچ رکوردی در MySQL یافت نشد")
            return self.stats

        print(f"✅ تعداد {total} رکورد یافت شد")

        if dry_run:
            print("\n🔍 در حال تحلیل رکوردها...")
            for i, record in enumerate(records, 1):
                enter_count, exit_count = self._process_single_record_dry(record)
                self.stats['enter_records'] += enter_count
                self.stats['exit_records'] += exit_count

                if i % 10000 == 0:
                    print(f"  تحلیل شد: {i}/{total}")

            self._print_stats()
            return self.stats

        # انتقال واقعی
        db: Session = SessionLocal()
        batch_size = 100

        try:
            print("\n💾 در حال انتقال داده‌ها...")

            for i, record in enumerate(records, 1):
                enter_count, exit_count = self._process_single_record(db, record)
                self.stats['enter_records'] += enter_count
                self.stats['exit_records'] += exit_count

                # Commit هر batch
                if i % batch_size == 0:
                    try:
                        db.commit()
                        if i % 5000 == 0:  # برای شلوغ نکردن کنسول، هر 5000 تا پیام بده
                            print(f"  ✅ ذخیره شد: {i}/{total}")
                    except Exception as e:
                        db.rollback()
                        print(f"  ⚠️  خطا در batch {i}: {e}")
                        self.stats['errors'] += 1

            # Commit نهایی رکوردهای باقی‌مانده
            db.commit()
            print(f"\n✅ انتقال کامل شد: {total}/{total}")

        except Exception as e:
            db.rollback()
            print(f"\n❌ خطا در انتقال: {e}")
            self.stats['errors'] += 1
        finally:
            db.close()

        self._print_stats()
        return self.stats

    def migrate_from_date(self, from_date: str, dry_run: bool = False) -> Dict:
        """
        انتقال داده‌ها از یک تاریخ خاص (برای Sync تدریجی)
        با آمار دقیق
        """
        print(f"\n🔄 انتقال داده‌ها از تاریخ {from_date} به بعد...")

        records = self.mysql.get_ioinfo_records(from_date=from_date)
        total = len(records)
        self.stats['total_records'] = total

        if total == 0:
            print("⚠️  هیچ رکورد جدیدی یافت نشد")
            return self.stats

        print(f"✅ تعداد {total} رکورد یافت شد")

        if dry_run:
            print("⚠️  حالت Dry Run - داده‌ای ذخیره نخواهد شد")
            return self.stats

        db: Session = SessionLocal()
        batch_size = 100

        try:
            print("\n💾 در حال انتقال داده‌ها...")

            for i, record in enumerate(records, 1):
                enter_count, exit_count = self._process_single_record(db, record)

                # ✅ این آمار فقط شمارش می‌کند، نه واقعیت
                # واقعیت در _process_single_record با on_conflict_do_nothing مدیریت می‌شود

                if i % batch_size == 0:
                    try:
                        db.commit()
                        print(f"  ✅ دسته‌ای ذخیره شد: {i}/{total}")
                    except Exception as e:
                        db.rollback()
                        print(f"  ⚠️  خطا در batch {i}: {e}")
                        self.stats['errors'] += 1

            # Commit نهایی
            db.commit()
            print(f"\n✅ انتقال کامل شد")

        except Exception as e:
            db.rollback()
            print(f"\n❌ خطا در انتقال: {e}")
            self.stats['errors'] += 1
        finally:
            db.close()

        self._print_stats()
        return self.stats

    def _print_stats(self):
        """نمایش آمار عملیات"""
        print("\n" + "-" * 60)
        print("  📊 آمار عملیات انتقال:")
        print("-" * 60)
        print(f"  • کل رکوردهای MySQL   : {self.stats['total_records']}")
        print(f"  • رکوردهای ورود ساخته : {self.stats['enter_records']}")
        print(f"  • رکوردهای خروج ساخته : {self.stats['exit_records']}")
        print(f"  • کاربران جدید ساخته  : {self.stats['new_users']}")
        print(f"  • رکوردهای رد شده     : {self.stats['skipped_records']}")
        print(f"  • رکوردهای تکراری رد شده : {self.stats['duplicates']}")
        print(f"  • خطاها               : {self.stats['errors']}")
        print("-" * 60)

    def get_last_synced_date(self) -> str:
        """
        دریافت آخرین تاریخ sync شده در PostgreSQL
        برای استفاده در Sync تدریجی
        """
        db: Session = SessionLocal()
        try:
            last_record = db.query(Attendance).order_by(
                Attendance.timestamp.desc()
            ).first()

            if last_record:
                # تبدیل به تاریخ شمسی
                jdt = jdatetime.datetime.fromgregorian(
                    datetime=last_record.timestamp
                )
                return jdt.strftime("%Y/%m/%d")
            return None
        finally:
            db.close()
