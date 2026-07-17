"""
ماژول انتقال داده‌ها از MySQL قدیمی به PostgreSQL جدید
"""
from datetime import datetime
from typing import List, Dict, Tuple, Optional
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

    def sync_incremental(self, dry_run: bool = False) -> Dict:
        """
        همگام‌سازی تدریجی هوشمند

        منطق:
        1. آخرین رکورد PostgreSQL را پیدا کن
        2. آن را در MySQL جستجو کن
        3. اگر پیدا شد، از رکورد بعدی به بعد sync کن
        4. اگر پیدا نشد، کاری نکن

        Args:
            dry_run: حالت شبیه‌سازی

        Returns:
            Dict: آمار عملیات
        """
        print("\n" + "=" * 60)
        print("  🔄 همگام‌سازی تدریجی هوشمند")
        print("=" * 60)

        if dry_run:
            print("  ⚠️  حالت Dry Run - داده‌ای ذخیره نخواهد شد")

        # مرحله 1: دریافت آخرین رکورد PostgreSQL
        print("\n📊 بررسی آخرین رکورد در PostgreSQL...")
        last_record = self.get_last_synced_record()

        if not last_record:
            print("⚠️  هیچ رکوردی در PostgreSQL وجود ندارد")
            print("💡 ابتدا از گزینه Migration کامل استفاده کنید")
            return self.stats

        print(f"✅ آخرین رکورد یافت شد:")
        print(f"   • کاربر      : {last_record['user_id']}")
        print(f"   • زمان       : {last_record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   • تاریخ شمسی : {last_record['date_jalali']}")

        # مرحله 2: اتصال به MySQL
        if not self.connect_mysql():
            return self.stats

        try:
            # مرحله 3: جستجوی رکورد در MySQL
            print(f"\n🔍 جستجوی رکورد در MySQL...")
            found = self.find_record_in_mysql(
                last_record['user_id'],
                last_record['timestamp']
            )

            if not found:
                print("❌ آخرین رکورد PostgreSQL در MySQL یافت نشد")
                print("💡 ممکن است داده‌ها دستکاری شده باشند")
                print("💡 از گزینه Migration کامل استفاده کنید")
                return self.stats

            print("✅ رکورد در MySQL یافت شد")

            # مرحله 4: دریافت رکوردهای بعدی
            print(f"\n📖 دریافت رکوردهای جدید از MySQL...")
            new_records = self.get_records_after_timestamp(
                # last_record['user_id'],
                last_record['timestamp']
            )

            total = len(new_records)
            self.stats['total_records'] = total

            if total == 0:
                print("✅ هیچ رکورد جدیدی یافت نشد - دیتابیس به‌روز است")
                return self.stats

            print(f"✅ تعداد {total} رکورد جدید یافت شد")

            if dry_run:
                print("\n🔍 در حال تحلیل رکوردها...")
                for i, record in enumerate(new_records, 1):
                    enter_count, exit_count = self._process_single_record_dry(record)
                    self.stats['enter_records'] += enter_count
                    self.stats['exit_records'] += exit_count

                    if i % 1000 == 0:
                        print(f"  تحلیل شد: {i}/{total}")

                self._print_stats()
                return self.stats

            # مرحله 5: انتقال رکوردهای جدید
            db: Session = SessionLocal()
            batch_size = 100

            try:
                print("\n💾 در حال انتقال داده‌ها...")

                for i, record in enumerate(new_records, 1):
                    enter_count, exit_count = self._process_single_record(db, record)
                    self.stats['enter_records'] += enter_count
                    self.stats['exit_records'] += exit_count

                    if i % batch_size == 0:
                        try:
                            db.commit()
                            print(f"  ✅ دسته‌ای ذخیره شد: {i}/{total}")
                        except Exception as e:
                            db.rollback()
                            print(f"  ⚠️  خطا در batch {i}: {e}")
                            self.stats['errors'] += 1

                db.commit()
                print(f"\n✅ همگام‌سازی کامل شد: {total}/{total}")

            except Exception as e:
                db.rollback()
                print(f"\n❌ خطا در انتقال: {e}")
                self.stats['errors'] += 1
            finally:
                db.close()

            self._print_stats()
            return self.stats

        finally:
            self.disconnect_mysql()

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

    def get_last_synced_record(self) -> Optional[Dict]:
        """
        دریافت آخرین رکورد sync شده در PostgreSQL

        Returns:
            Dict: شامل user_id و timestamp آخرین رکورد، یا None
        """
        db: Session = SessionLocal()
        try:
            last_record = db.query(Attendance).order_by(
                Attendance.timestamp.desc()
            ).first()

            if last_record:
                return {
                    'user_id': last_record.user_id,
                    'timestamp': last_record.timestamp,
                    'date_jalali': jdatetime.datetime.fromgregorian(
                        datetime=last_record.timestamp
                    ).strftime("%Y/%m/%d")
                }
            return None
        finally:
            db.close()

    def find_record_in_mysql(self, user_id: str, timestamp: datetime) -> bool:
        """
        بررسی وجود یک رکورد خاص در MySQL
        """
        # ✅ اصلاح: استفاده از self.mysql.connection
        if not self.mysql.connection:
            print("❌ ابتدا باید به MySQL متصل شوید")
            return False

        try:
            # تبدیل timestamp میلادی به تاریخ و زمان شمسی
            j_timestamp = jdatetime.datetime.fromgregorian(datetime=timestamp)
            date_str = j_timestamp.strftime("%Y/%m/%d")
            time_str = j_timestamp.strftime("%H:%M")

            with self.mysql.connection.cursor() as cursor:
                # جستجو در EnterDate/EnterTime
                cursor.execute(
                    """
                    SELECT COUNT(*) as cnt
                    FROM ioinfo
                    WHERE Perno = %s
                      AND (
                        (EnterDate = %s AND EnterTime = %s)
                            OR (ExitDate = %s AND ExitTime = %s)
                        )
                    """,
                    (int(user_id), date_str, time_str, date_str, time_str)
                )
                result = cursor.fetchone()
                return result['cnt'] > 0 if result else False

        except Exception as e:
            print(f"⚠️  خطا در جستجوی رکورد: {e}")
            return False

    def get_records_after_timestamp(self, timestamp: datetime) -> List[Dict]:
        """
        دریافت تمام رکوردهای MySQL بعد از یک timestamp خاص (از همه کاربران)

        Args:
            timestamp: زمان شروع (میلادی)

        Returns:
            List[Dict]: لیست رکوردها
        """
        if not self.mysql.connection:
            print("❌ ابتدا باید به MySQL متصل شوید")
            return []

        try:
            # تبدیل timestamp میلادی به تاریخ و زمان شمسی
            j_timestamp = jdatetime.datetime.fromgregorian(datetime=timestamp)
            date_str = j_timestamp.strftime("%Y/%m/%d")
            time_str = j_timestamp.strftime("%H:%M")

            with self.mysql.connection.cursor() as cursor:
                # ✅ اصلاح: حذف شرط Perno و دریافت همه رکوردها
                cursor.execute(
                    """
                    SELECT Perno, EnterDate, EnterTime, ExitDate, ExitTime
                    FROM ioinfo
                    WHERE EnterDate > %s
                       OR (EnterDate = %s AND EnterTime > %s)
                       OR ExitDate > %s
                       OR (ExitDate = %s AND ExitTime > %s)
                    ORDER BY EnterDate ASC, EnterTime ASC
                    """,
                    (date_str, date_str, time_str, date_str, date_str, time_str)
                )
                return cursor.fetchall()

        except Exception as e:
            print(f"⚠️  خطا در دریافت رکوردها: {e}")
            return []