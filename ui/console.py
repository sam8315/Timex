from typing import Dict
from datetime import datetime, timedelta,date
import jdatetime
from core.device_manager import DeviceManager


class ConsoleUI:
    """رابط کاربری کنسول"""

    def __init__(self, manager: DeviceManager):
        self.manager = manager
        self.connected = False

    def clear(self):
        """پاک کردن صفحه"""
        print("\033c", end="")

    def header(self, title: str):
        """نمایش هدر"""
        print("\n" + "=" * 60)
        print(f"  {title}")
        print("=" * 60)

    def show_menu(self):
        """نمایش منوی اصلی"""
        self.clear()
        self.header("سیستم مدیریت دستگاه حضور و غیاب ST-FACE 120")

        status = "🟢 متصل" if self.connected else "🔴 قطع"
        print(f"\n  وضعیت اتصال: {status}")
        print(f"  دستگاه: {self.manager.ip}:{self.manager.port}")

        print("\n┌─────────────────────────────────────────┐")
        print("│  1. اتصال به دستگاه                      │")
        print("│  2. قطع اتصال                            │")
        print("│  3. اطلاعات دستگاه                        │")
        print("│  4. لیست کاربران                         │")
        print("│  5. جستجوی کاربر بر اساس کد پرسنلی       │")
        print("│  6. جستجوی کاربر بر اساس نام             │")  # جدید
        print("│  7. جستجوی چندگانه کاربران               │")  # جدید
        print("│  8. رکوردهای تردد                        │")
        print("│  9. رکوردهای یک روز خاص                  │")
        print("│  10. پاک کردن رکوردها                    │")
        print("│      دیتابیس و Migration                 │")
        print("│  11. همگام‌سازی کاربران با دیتابیس        │")
        print("│  12. همگام‌سازی رکوردهای تردد با دیتابیس  │")  # 🆕 گزینه جدید
        print("│  13. انتقال کامل از MySQL (Migration)    │")
        print("│  14. انتقال تدریجی از MySQL (Sync)       │")
        print("│  15. تست اتصال به MySQL                  │")
        print("│                                          │")
        print("│              تنظیمات                     │")
        print("│  16. همگام‌سازی زمان                      │")
        print("│  17. ریستارت دستگاه                      │")
        print("│                                          │")
        print("│  🔍 تحلیل و گزارش                       │")
        print("│  18. بررسی ترددهای ناقص                       │")  # 🆕
        print("│  19. آمار کلی ترددها                          │")  # 🆕
        print("│  20. جزئیات تردد یک کاربر                     │")  # 🆕
        print("│  0. خروج                                 │")
        print("└─────────────────────────────────────────────────┘")

        return input("\n  انتخاب شما: ").strip()

    def run(self):
        """اجرای حلقه اصلی"""
        while True:
            choice = self.show_menu()

            if choice == '1':
                self._connect()
            elif choice == '2':
                self._disconnect()
            elif choice == '3':
                self._show_device_info()
            elif choice == '4':
                self._show_users()
            elif choice == '5':
                self._find_user_by_user_id()  # تغییر نام
            elif choice == '6':
                self._find_user_by_code()  # جدید
            elif choice == '7':
                self._search_users()  # جدید
            elif choice == '8':
                self._show_attendance()
            elif choice == '9':
                self._show_attendance_by_date()
            elif choice == '10':
                self._clear_attendance()
            elif choice == '11':
                self._sync_users_to_db()
            elif choice == '12':  # یا شماره‌ای که انتخاب کردید
                self._sync_attendance_to_db()
            elif choice == '13':
                self._migrate_from_mysql()  # 🆕
            elif choice == '14':
                self._sync_from_mysql()  # 🆕
            elif choice == '15':
                self._test_mysql_connection()  # 🆕
            elif choice == '16':
                self._sync_time()
            elif choice == '17':
                self._restart()
            elif choice == '18':
                self._show_incomplete_attendances()
            elif choice == '19':
                self._show_attendance_statistics()
            elif choice == '20':
                self._show_user_attendance_detail()
            elif choice == '0':
                self._disconnect()
                print("\n👋 خدانگهدار!")
                break
            else:
                print("\n❌ انتخاب نامعتبر")

            input("\n⏎ برای ادامه Enter بزنید...")
    # ============================================
    # متدهای عملیاتی
    # ============================================

    def _connect(self):
        if self.connected:
            print("\n⚠️  قبلاً متصل هستید")
            return

        print(f"\n🔌 در حال اتصال به {self.manager.ip}...")
        if self.manager.connect():
            self.connected = True
            print("✅ اتصال برقرار شد")
        else:
            print("❌ اتصال ناموفق بود")

    def _disconnect(self):
        if not self.connected:
            print("\n⚠️  اتصال برقرار نیست")
            return

        self.manager.disconnect()
        self.connected = False
        print("\n✅ اتصال قطع شد")

    def _show_device_info(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        self.header("اطلاعات دستگاه")
        info = self.manager.get_device_info()

        print(f"\n  🌐 آدرس IP       : {info.get('ip')}")
        print(f"  🔌 پورت          : {info.get('port')}")
        print(f"  🔢 شماره سریال   : {info.get('serial')}")
        print(f"  📱 مدل           : {info.get('platform')}")
        print(f"  🔧 فریم‌ور       : {info.get('firmware')}")
        print(f"  🕐 زمان دستگاه   : {info.get('time')}")

    def _show_users(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        self.header("لیست کاربران")
        users = self.manager.get_users()

        if not users:
            print("\n  هیچ کاربری یافت نشد")
            return

        print(f"\n  تعداد کاربران: {len(users)}\n")
        print(f"  {'UID':<8} {'USER ID':<8} {'نام':<12} {'Password':<8} {'Cart':<15} {'Group':<6} {'privilege':<6}")
        print("  " + "-" * 58)

        for user in users:
            print(f"  {user['uid']:<8}  {user['user_id']:<8} {user['name']:<12} {user['password']:<8} "
                  f"{user['card'] or '-':<15} {user['group_id'] or '-':<6} {user['privilege'] or '-':<6}")

    def _find_user(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        try:
            uid = int(input("\n  UID کاربر را وارد کنید: "))
            user = self.manager.find_user(uid)

            if user:
                self.header(f"اطلاعات کاربر {uid}")
                print(f"\n  نام        : {user['name']}")
                print(f"  UID        : {user['uid']}")
                print(f"  کارت       : {user['card'] or '-'}")
                print(f"  گروه       : {user['group_id'] or '-'}")
                print(f"  سطح دسترسی: {user['privilege']}")
            else:
                print(f"\n❌ کاربری با UID {uid} یافت نشد")
        except ValueError:
            print("\n❌ UID باید عدد باشد")

    def _show_attendance(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        self.header("رکوردهای تردد")
        records = self.manager.get_attendance()

        if not records:
            print("\n  هیچ رکوردی یافت نشد")
            return

        print(f"\n  تعداد رکوردها: {len(records)}\n")

        # نمایش 20 رکورد آخر
        display_count = min(20, len(records))
        print(f"  آخرین {display_count} رکورد:\n")
        print(f"  {'UID':<8} {'Time':<22} {'Time shamsi':<22} {'status(ramz=0,finger=1,cart=2)':<8} {'punch(enter=0,exit=1)':<8}")
        print("  " + "-" * 64)

        for record in records[-display_count:]:
            ts = record['timestamp']
            try:
                jts = jdatetime.datetime.fromgregorian(datetime=ts)
                jts_str = jts.strftime("%Y/%m/%d %H:%M:%S")
            except:
                jts_str = "-"

            print(f"  {record['user_id']:<8} {str(ts):<22} {jts_str:<22} {record['status']:<8} {record['punch']:<8}")

    def _show_attendance_by_date(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        try:
            date_str = input("\n  تاریخ را وارد کنید (مثال: 1405/04/17): ").strip()
            records = self.manager.get_attendance_by_date(date_str)

            if not records:
                print(f"\n  هیچ رکوردی برای تاریخ {date_str} یافت نشد")
                return

            self.header(f"رکوردهای تاریخ {date_str}")
            print(f"\n  تعداد رکوردها: {len(records)}\n")
            print(f"  {'UID':<8} {'Time':<20} {'Status':<8}")
            print("  " + "-" * 40)

            for record in records:
                ts_str = record['timestamp'].strftime("%H:%M:%S")
                print(f"  {record['user_id']:<8} {ts_str:<20} {record['status']:<8}")

        except Exception as e:
            print(f"\n❌ خطا: {e}")

    def _clear_attendance(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        confirm = input("\n⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
        if confirm.lower() in ['بله', 'yes', 'y']:
            if self.manager.clear_attendance():
                print("\n✅ رکوردها پاک شدند")
            else:
                print("\n❌ خطا در پاک کردن رکوردها")
        else:
            print("\n❌ عملیات لغو شد")

    def _sync_time(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        if self.manager.sync_time():
            print(f"\n✅ زمان دستگاه با سرور همگام شد")
            print(f"   زمان فعلی سرور: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _restart(self):
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        confirm = input("\n⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
        if confirm.lower() in ['بله', 'yes', 'y']:
            if self.manager.restart():
                print("\n✅ دستور ریستارت ارسال شد")
                self.connected = False
            else:
                print("\n❌ خطا در ریستارت")
        else:
            print("\n❌ عملیات لغو شد")


    def _find_user_by_user_id(self):
        """جستجو بر اساس UID"""
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        try:
            user_id = int(input("\n  UID کاربر را وارد کنید: "))
            user = self.manager.find_user(user_id)

            if user:
                self._display_user_info(user)
            else:
                print(f"\n❌ کاربری با UID {user_id} یافت نشد")
        except ValueError:
            print("\n❌ UID باید عدد باشد")


    def _find_user_by_code(self):
        """جستجو بر اساس کد پرسنلی"""
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        code = input("\n  کد پرسنلی را وارد کنید (مثال: NN-6925): ").strip()

        if not code:
            print("\n❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        user = self.manager.find_user_by_personnel_code(code)

        if user:
            self._display_user_info(user)
        else:
            print(f"\n❌ کاربری با کد پرسنلی '{code}' یافت نشد")


    def _search_users(self):
        """جستجوی چندگانه کاربران"""
        if not self.connected:
            print("\n❌ ابتدا متصل شوید")
            return

        query = input("\n  عبارت جستجو را وارد کنید: ").strip()

        if not query:
            print("\n❌ عبارت جستجو نمی‌تواند خالی باشد")
            return

        results = self.manager.search_users(query)

        if not results:
            print(f"\n❌ هیچ کاربری با عبارت '{query}' یافت نشد")
            return

        self.header(f"نتایج جستجو برای: {query}")
        print(f"\n  تعداد نتایج: {len(results)}\n")
        print(f"  {'UID':<8} {'کد پرسنلی':<25} {'کارت':<15} {'گروه':<6}")
        print("  " + "-" * 58)

        for user in results:
            print(f"  {user['uid']:<8} {user['name']:<25} "
                  f"{user['card'] or '-':<15} {user['group_id'] or '-':<6}")


    def _display_user_info(self, user: Dict):
        """نمایش اطلاعات کاربر"""
        self.header(f"اطلاعات کاربر")
        print(f"\n  کد پرسنلی : {user['name']}")
        print(f"  UID       : {user['uid']}")
        print(f"  کارت      : {user['card'] or '-'}")
        print(f"  گروه      : {user['group_id'] or '-'}")
        print(f"  سطح دسترسی: {user['privilege']}")

    def _migrate_from_mysql(self):
        """انتقال کامل داده‌ها از MySQL"""
        from database.migration import DataMigrator

        print("\n" + "=" * 60)
        print("  🔄 انتقال کامل داده‌ها از MySQL")
        print("=" * 60)
        print("\n⚠️  این عملیات ممکن است چند دقیقه طول بکشد")

        confirm = input("\nآیا مطمئن هستید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("\n❌ عملیات لغو شد")
            return

        dry_run_input = input("\nاجرا در حالت Dry Run (فقط شبیه‌سازی)؟ (بله/خیر): ").strip()
        dry_run = dry_run_input.lower() in ['بله', 'yes', 'y']

        migrator = DataMigrator()

        if not migrator.connect_mysql():
            return

        try:
            migrator.migrate_all(dry_run=dry_run)
        finally:
            migrator.disconnect_mysql()

    def _sync_from_mysql(self):
        """Sync تدریجی از MySQL (فقط رکوردهای جدید)"""
        from database.migration import DataMigrator

        print("\n" + "=" * 60)
        print("  🔄 همگام‌سازی تدریجی از MySQL")
        print("=" * 60)

        migrator = DataMigrator()

        # دریافت آخرین تاریخ sync شده
        last_date = migrator.get_last_synced_date()

        if not last_date:
            print("\n⚠️  هیچ رکوردی در PostgreSQL وجود ندارد")
            print("💡 ابتدا از گزینه 11 (Migration کامل) استفاده کنید")
            return

        print(f"\n📅 آخرین رکورد sync شده: {last_date}")

        from_date = input(f"\nانتقال از تاریخ (پیش‌فرض: {last_date}): ").strip()
        if not from_date:
            from_date = last_date

        if not migrator.connect_mysql():
            return

        try:
            migrator.migrate_from_date(from_date)
        finally:
            migrator.disconnect_mysql()

    def _test_mysql_connection(self):
        """تست اتصال به MySQL"""
        from database.mysql_connector import MySQLConnector

        print("\n🔌 در حال تست اتصال به MySQL...")

        mysql = MySQLConnector()

        if mysql.connect():
            print("✅ اتصال به MySQL برقرار شد")

            # نمایش اطلاعات
            count = mysql.get_record_count()
            print(f"📊 تعداد رکوردهای ioinfo: {count}")

            personnel = mysql.get_unique_personnel()
            print(f"👥 تعداد پرسنل منحصر به فرد: {len(personnel)}")

            # نمایش چند رکورد نمونه
            print("\n📝 5 رکورد نمونه:")
            records = mysql.get_ioinfo_records(limit=5)
            for r in records:
                print(f"  Perno={r['Perno']}, "
                      f"Enter={r['EnterDate']} {r['EnterTime']}, "
                      f"Exit={r['ExitDate'] or '-'} {r['ExitTime'] or '-'}")

            mysql.disconnect()
        else:
            print("❌ اتصال به MySQL ناموفق بود")

    def _sync_users_to_db(self):
        """همگام‌سازی کاربران دستگاه با دیتابیس"""
        if not self.connected:
            print("\n❌ ابتدا به دستگاه متصل شوید")
            return

        print("\n" + "=" * 60)
        print("  🔄 همگام‌سازی کاربران با دیتابیس")
        print("=" * 60)

        confirm = input("\nآیا مطمئن هستید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("\n❌ عملیات لغو شد")
            return

        self.manager.sync_users_to_db()

    def _sync_attendance_to_db(self):
        """همگام‌سازی رکوردهای تردد دستگاه با دیتابیس"""
        if not self.connected:
            print("\n❌ ابتدا به دستگاه متصل شوید (گزینه 1)")
            return

        print("\n" + "=" * 60)
        print("  🔄 همگام‌سازی رکوردهای تردد با دیتابیس")
        print("=" * 60)
        print("\n⚠️  این عملیات بسته به تعداد رکوردها ممکن است زمان‌بر باشد.")
        print("💡 رکوردهای تکراری به صورت خودکار نادیده گرفته می‌شوند.")

        confirm = input("\nآیا مطمئن هستید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("\n❌ عملیات لغو شد")
            return

        # فراخوانی متد مدیر دستگاه
        self.manager.sync_attendance_to_db()

    def _show_incomplete_attendances(self):
        """نمایش ترددهای ناقص"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 60)
        print("  🔍 بررسی ترددهای ناقص")
        print("=" * 60)

        # دریافت بازه زمانی
        print("\n📅 بازه زمانی را مشخص کنید:")
        from_date_str = input("  از تاریخ (شمسی - مثال: 1405/04/01) [پیش‌فرض: اول ماه]: ").strip()
        to_date_str = input("  تا تاریخ (شمسی - مثال: 1405/04/24) [پیش‌فرض: امروز]: ").strip()

        try:
            # تبدیل تاریخ شمسی به میلادی
            if from_date_str:
                j_from = jdatetime.datetime.strptime(from_date_str, "%Y/%m/%d").date()
                from_date = j_from.togregorian()
            else:
                today = date.today()
                from_date = date(today.year, today.month, 1)

            if to_date_str:
                j_to = jdatetime.datetime.strptime(to_date_str, "%Y/%m/%d").date()
                to_date = j_to.togregorian()
            else:
                to_date = date.today()

        except Exception as e:
            print(f"\n❌ خطا در تبدیل تاریخ: {e}")
            return

        analyzer = AttendanceAnalyzer()
        try:
            incomplete = analyzer.get_incomplete_attendances(from_date, to_date)

            if not incomplete:
                print("\n✅ هیچ تردد ناقصی در این بازه زمانی یافت نشد!")
                return

            print(f"\n⚠️  تعداد {len(incomplete)} تردد ناقص یافت شد:\n")
            print(f"  {'تاریخ':<12} {'کد پرسنلی':<12} {'نام':<20} {'وضعیت':<25} {'ورود':<6} {'خروج':<6}")
            print("  " + "-" * 85)

            for item in incomplete:
                # تبدیل تاریخ میلادی به شمسی برای نمایش
                j_date = jdatetime.date.fromgregorian(date=item['date'])
                date_str = j_date.strftime("%Y/%m/%d")

                print(f"  {date_str:<12} {item['user_id']:<12} {item['name']:<20} "
                      f"{item['type']:<25} {item['enter_count']:<6} {item['exit_count']:<6}")

            # خلاصه بر اساس نوع مشکل
            missing_enter = sum(1 for i in incomplete if i['issue'] == 'missing_enter')
            missing_exit = sum(1 for i in incomplete if i['issue'] == 'missing_exit')
            imbalance = sum(1 for i in incomplete if i['issue'] == 'imbalance')

            print("\n" + "-" * 85)
            print(f"  📊 خلاصه:")
            print(f"     • خروج بدون ورود   : {missing_enter}")
            print(f"     • ورود بدون خروج   : {missing_exit}")
            print(f"     • عدم تعادل       : {imbalance}")
            print("-" * 85)

        finally:
            analyzer.close()

    def _show_attendance_statistics(self):
        """نمایش آمار کلی ترددها"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 60)
        print("  📊 آمار کلی ترددها")
        print("=" * 60)

        analyzer = AttendanceAnalyzer()
        try:
            stats = analyzer.get_summary_statistics()

            j_from = jdatetime.date.fromgregorian(date=stats['from_date'])
            j_to = jdatetime.date.fromgregorian(date=stats['to_date'])

            print(f"\n  📅 بازه زمانی: {j_from.strftime('%Y/%m/%d')} تا {j_to.strftime('%Y/%m/%d')}")
            print("\n" + "-" * 60)
            print(f"  • کل رکوردهای تردد      : {stats['total_records']:,}")
            print(f"  • تعداد ورودها           : {stats['enter_count']:,}")
            print(f"  • تعداد خروج‌ها          : {stats['exit_count']:,}")
            print(f"  • کاربران فعال           : {stats['unique_users']}")
            print(f"  • ترددهای ناقص           : {stats['incomplete_count']}")

            if stats['enter_count'] > 0 or stats['exit_count'] > 0:
                ratio = stats['exit_count'] / stats['enter_count'] if stats['enter_count'] > 0 else 0
                print(f"  • نسبت خروج به ورود    : {ratio:.2%}")

            print("-" * 60)

        finally:
            analyzer.close()

    def _show_user_attendance_detail(self):
        """نمایش جزئیات تردد یک کاربر"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 60)
        print("  🔎 جزئیات تردد یک کاربر")
        print("=" * 60)

        user_id = input("\n  کد پرسنلی کاربر را وارد کنید: ").strip()
        if not user_id:
            print("❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        date_str = input("  تاریخ (شمسی - مثال: 1405/04/24) [پیش‌فرض: امروز]: ").strip()

        try:
            if date_str:
                j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
                target_date = j_date.togregorian()
            else:
                target_date = date.today()
        except Exception as e:
            print(f"\n❌ خطا در تبدیل تاریخ: {e}")
            return

        analyzer = AttendanceAnalyzer()
        try:
            detail = analyzer.get_user_attendance_detail(user_id, target_date)

            if 'error' in detail:
                print(f"\n❌ {detail['error']}")
                return

            j_date = jdatetime.date.fromgregorian(date=target_date)

            print(f"\n  👤 کاربر: {detail['user']['name']} (کد: {detail['user']['user_id']})")
            print(f"  📅 تاریخ: {j_date.strftime('%Y/%m/%d')}")
            print("\n" + "-" * 60)

            if detail['enter_count'] == 0 and detail['exit_count'] == 0:
                print("  ⚠️  هیچ ترددی برای این کاربر در این تاریخ ثبت نشده است")
            else:
                print(f"  🟢 تعداد ورودها: {detail['enter_count']}")
                for e in detail['enters']:
                    time_str = e['time'].strftime("%H:%M:%S")
                    print(f"      • {time_str} (روش: {self._get_status_name(e['status'])})")

                print(f"\n  🔴 تعداد خروج‌ها: {detail['exit_count']}")
                for x in detail['exits']:
                    time_str = x['time'].strftime("%H:%M:%S")
                    print(f"      • {time_str} (روش: {self._get_status_name(x['status'])})")

                print("\n" + "-" * 60)
                if detail['is_complete']:
                    print("  ✅ وضعیت: تردد کامل")
                else:
                    print("  ⚠️  وضعیت: تردد ناقص")

            print("-" * 60)

        finally:
            analyzer.close()

    def _get_status_name(self, status: int) -> str:
        """تبدیل کد status به نام خوانا"""
        status_map = {
            0: 'اثر انگشت',
            1: 'کارت',
            2: 'رمز',
            3: 'چهره',
            15: 'سایر'
        }
        return status_map.get(status, f'نامشخص ({status})')