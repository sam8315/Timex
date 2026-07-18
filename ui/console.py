from typing import Dict
from datetime import datetime, timedelta,date
import jdatetime
from core.device_manager import DeviceManager
from core.attendance_analyzer import AttendanceAnalyzer


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
        print("│  ✏️  ویرایش ترددها                              │")
        print("│  21. افزودن رکورد تردد دستی                    │")  # 🆕
        print("│  22. حذف رکورد تردد                             │")  # 🆕
        print("│  23. تغییر وضعیت (ورود/خروج) رکورد             │")  # 🆕
        print("│  24. ♻️  بازیابی رکورد حذف شده                  │")  # 🆕
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
            elif choice == '21':
                self._add_attendance_record()
            elif choice == '22':
                self._delete_attendance_record()
            elif choice == '23':
                self._update_attendance_punch()
            elif choice == '24':
                pass
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
        display_count = min(200, len(records))
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
            print(f"  {'UID':<8} {'Time':<20} {'Punch':<8}")
            print("  " + "-" * 40)

            for record in records:
                ts_str = record['timestamp'].strftime("%H:%M:%S")
                print(f"  {record['user_id']:<8} {ts_str:<20} {record['punch']:<8}")

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
        """همگام‌سازی تدریجی هوشمند از MySQL"""
        from database.migration import DataMigrator

        print("\n" + "=" * 60)
        print("  🔄 همگام‌سازی تدریجی هوشمند از MySQL")
        print("=" * 60)

        dry_run_input = input("\nاجرا در حالت Dry Run (فقط شبیه‌سازی)؟ (بله/خیر): ").strip()
        dry_run = dry_run_input.lower() in ['بله', 'yes', 'y']

        migrator = DataMigrator()
        migrator.sync_incremental(dry_run=dry_run)

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

    def _show_user_attendance_detail(self):
        """نمایش جزئیات تردد یک کاربر در بازه زمانی با قابلیت ویرایش"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 95)
        print("  🔎 گزارش تردد کاربر در بازه زمانی")
        print("=" * 95)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        # دریافت بازه زمانی
        today_j = jdatetime.date.today()
        default_from = jdatetime.date(today_j.year, today_j.month, 1)

        from_str = input(f"  📅 از تاریخ (شمسی) [پیش‌فرض: {default_from.strftime('%Y/%m/%d')}]: ").strip()
        to_str = input(f"  📅 تا تاریخ (شمسی) [پیش‌فرض: {today_j.strftime('%Y/%m/%d')}]: ").strip()

        try:
            from_date = jdatetime.datetime.strptime(
                from_str if from_str else default_from.strftime("%Y/%m/%d"),
                "%Y/%m/%d"
            ).date().togregorian()

            to_date = jdatetime.datetime.strptime(
                to_str if to_str else today_j.strftime("%Y/%m/%d"),
                "%Y/%m/%d"
            ).date().togregorian()

        except Exception as e:
            print(f"\n  ❌ خطا در تبدیل تاریخ: {e}")
            return

        # حلقه اصلی
        while True:
            analyzer = AttendanceAnalyzer()
            try:
                result = analyzer.get_user_attendance_range(user_id, from_date, to_date)

                if 'error' in result:
                    print(f"\n  ❌ {result['error']}")
                    return

                days = result['days']
                summary = result['summary']

                # هدر گزارش
                print("\n" + "=" * 95)
                print(f"  👤 کاربر: {result['user']['name']} (کد: {result['user']['user_id']})")
                j_from = jdatetime.date.fromgregorian(date=result['from_date'])
                j_to = jdatetime.date.fromgregorian(date=result['to_date'])
                print(f"  📅 بازه: {j_from.strftime('%Y/%m/%d')} تا {j_to.strftime('%Y/%m/%d')}")

                if not days:
                    print("\n  ⚠️  هیچ ترددی در این بازه زمانی ثبت نشده است")
                else:
                    # جدول نتایج با ستون شب‌کاری
                    print("\n  ┌────────────┬──────────┬──────────┬──────┬──────┬────────┬──────────┬──────────────┐")
                    print("  │ تاریخ      │ ورود     │ خروج     │ ورود │ خروج │ کار    │ شب‌کاری  │ وضعیت        │")
                    print("  ├────────────┼──────────┼──────────┼──────┼──────┼────────┼──────────┼──────────────┤")

                    for day in days:
                        j_date = jdatetime.date.fromgregorian(date=day['date'])
                        date_str = j_date.strftime("%Y/%m/%d")

                        # فرمت‌بندی زمان با تشخیص روز بعد
                        def fmt_time(dt):
                            if not dt:
                                return "  ---   "
                            time_str = dt.strftime("%H:%M")
                            if dt.date() > day['date']:
                                return f"{time_str} (+1)"
                            return f"{time_str}    "

                        first_enter = fmt_time(day['first_enter'])
                        last_exit = fmt_time(day['last_exit'])

                        if day['work_hours']:
                            work_h = int(day['work_hours'])
                            work_m = int((day['work_hours'] - work_h) * 60)
                            work_str = f"{work_h:02d}:{work_m:02d}  "
                        else:
                            work_str = "  ---   "

                        if day['night_hours']:
                            night_h = int(day['night_hours'])
                            night_m = int((day['night_hours'] - night_h) * 60)
                            night_str = f"{night_h:02d}:{night_m:02d}  "
                        else:
                            night_str = "  --    "

                        # تعیین وضعیت
                        if day['has_sequence_error']:
                            error_types = [e.get('error_type', '') for e in day['sequence_errors']]
                            if 'exit_before_enter' in error_types:
                                status = "❌ خروج قبل ورود"
                            elif 'consecutive' in error_types:
                                status = "⚠️ ترتیب اشتباه"
                            else:
                                status = "⚠️ خطای ترتیب"
                        elif day['is_complete']:
                            status = "✅ کامل"
                        elif day['enter_count'] > 0 and day['exit_count'] == 0:
                            status = "⚠️ بدون خروج"
                        elif day['enter_count'] == 0 and day['exit_count'] > 0:
                            status = "❌ بدون ورود"
                        else:
                            status = "🔄 نامتعادل"

                        print(f"  │ {date_str:<10} │ {first_enter:<8} │ {last_exit:<8} │ "
                              f"{day['enter_count']:<4} │ {day['exit_count']:<4} │ {work_str:<6} │ {night_str:<8} │ {status:<12} │")

                        # نمایش جزئیات رکوردها
                        if len(day['all_records']) > 2 or day['has_sequence_error']:
                            print(f"  │            │ جزئیات رکوردها:                                                     │")
                            for i, rec in enumerate(day['all_records'], 1):
                                time_str = rec['timestamp'].strftime("%H:%M")
                                if rec['timestamp'].date() > day['date']:
                                    time_str += " (+1)"
                                punch_icon = "🟢" if rec['punch'] == 0 else "🔴"
                                source_icon = "📱" if rec.get('source') == 'D' else ("📦" if rec.get('source') == 'L' else "✋")
                                print(f"  │            │   {i}. {punch_icon} {time_str} {rec['punch_name']:<10} {source_icon:<3}                  │")

                    print("  └────────────┴──────────┴──────────┴──────┴──────┴────────┴──────────┴──────────────┘")

                    # خلاصه آماری
                    print("\n  " + "-" * 91)
                    print(f"  📊 خلاصه:")
                    print(f"     • روزهای ثبت شده     : {summary['total_days']}")
                    print(f"     • روزهای کامل        : {summary['complete_days']} ✅")
                    print(f"     • روزهای ناقص/خطادار : {summary['incomplete_days'] + summary['sequence_error_days']} ⚠️")

                    total_h = int(summary['total_work_hours'])
                    total_m = int((summary['total_work_hours'] - total_h) * 60)
                    print(f"     • مجموع ساعات کاری   : {total_h} ساعت و {total_m} دقیقه")

                    night_h = int(summary['total_night_hours'])
                    night_m = int((summary['total_night_hours'] - night_h) * 60)
                    print(f"     • مجموع ساعات شب‌کاری : {night_h} ساعت و {night_m} دقیقه 🌙")
                    print("  " + "-" * 91)

                    # نمایش جزئیات خطاهای ترتیب
                    days_with_errors = [d for d in days if d['has_sequence_error']]
                    if days_with_errors:
                        print("\n  ⚠️  روزهایی با خطای ترتیب ورود/خروج:")
                        for day in days_with_errors:
                            j_date = jdatetime.date.fromgregorian(date=day['date'])
                            print(f"\n     📅 {j_date.strftime('%Y/%m/%d')}:")
                            for error in day['sequence_errors']:
                                time_str = error['timestamp'].strftime("%H:%M:%S")
                                print(f"        • {time_str} - {error['message']}")

                # منوی ویرایش
                print("\n  ┌─────────────────────────────────────────┐")
                print("  │  ✏️  عملیات ویرایش                       │")
                print("  │  1. ➕ افزودن رکورد جدید                 │")
                print("  │  2. 🗑️  حذف رکورد                        │")
                print("  │  3. 🔄 تغییر وضعیت (ورود/خروج)          │")
                print("  │  0. 🔙 بازگشت به منوی اصلی              │")
                print("  └─────────────────────────────────────────┘")

                edit_choice = input("\n  انتخاب شما: ").strip()

                if edit_choice == '0':
                    print("\n  🔙 بازگشت به منوی اصلی")
                    break
                elif edit_choice == '1':
                    self._add_record_inline(user_id, from_date, to_date)
                elif edit_choice == '2':
                    self._delete_record_inline(user_id, from_date, to_date)
                elif edit_choice == '3':
                    self._update_punch_inline(user_id, from_date, to_date)
                else:
                    print("\n  ❌ انتخاب نامعتبر")

            finally:
                analyzer.close()


    def _add_record_inline(self, user_id: str, from_date: date, to_date: date):
        """افزودن رکورد در زمینه گزارش کاربر"""
        print("\n" + "-" * 70)
        print("  ➕ افزودن رکورد جدید")
        print("-" * 70)

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()
        time_str = input("  🕐 ساعت (مثال: 08:30): ").strip()

        print("\n  نوع تردد:")
        print("    0. ورود (Check-in)")
        print("    1. خروج (Check-out)")
        punch_str = input("  انتخاب [0/1]: ").strip()

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            hour, minute = map(int, time_str.split(':'))
            timestamp = datetime(g_date.year, g_date.month, g_date.day, hour, minute)

            punch = int(punch_str)
            if punch not in [0, 1]:
                print("  ❌ نوع تردد باید 0 یا 1 باشد")
                return

            punch_name = "ورود" if punch == 0 else "خروج"
            j_date_display = jdatetime.date.fromgregorian(date=g_date)

            print("\n" + "-" * 70)
            print(f"  📋 پیش‌نمایش:")
            print(f"     • کاربر      : {user_id}")
            print(f"     • تاریخ      : {j_date_display.strftime('%Y/%m/%d')}")
            print(f"     • ساعت       : {timestamp.strftime('%H:%M')}")
            print(f"     • نوع        : {punch_name}")
            print("-" * 70)

            confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            analyzer = AttendanceAnalyzer()
            try:
                result = analyzer.add_attendance_record(user_id, timestamp, punch)
                print(f"\n  {result['message']}")
            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ فرمت تاریخ یا ساعت نامعتبر است: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")

    def _delete_record_inline(self, user_id: str, from_date: date, to_date: date):
        """حذف رکورد در زمینه گزارش کاربر"""
        print("\n" + "-" * 70)
        print("  🗑️  حذف رکورد")
        print("-" * 70)

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            analyzer = AttendanceAnalyzer()
            try:
                records = analyzer.get_attendance_records_by_date(user_id, g_date)

                if not records:
                    print(f"\n  ⚠️  هیچ رکوردی برای این کاربر در این تاریخ یافت نشد")
                    return

                j_date_display = jdatetime.date.fromgregorian(date=g_date)
                print(f"\n  📋 رکوردهای کاربر {user_id} در تاریخ {j_date_display.strftime('%Y/%m/%d')}:")
                print("  " + "-" * 60)
                print(f"  {'#':<4} {'شناسه':<8} {'زمان':<12} {'نوع':<10}")
                print("  " + "-" * 60)

                for i, r in enumerate(records, 1):
                    time_str = r['timestamp'].strftime("%H:%M:%S")
                    print(f"  {i:<4} {r['id']:<8} {time_str:<12} {r['punch_name']:<10}")

                print("  " + "-" * 60)

                choice = input("\n  شماره رکورد برای حذف (یا 0 برای انصراف): ").strip()
                if choice == '0' or not choice:
                    print("  ❌ عملیات لغو شد")
                    return

                idx = int(choice) - 1
                if idx < 0 or idx >= len(records):
                    print("  ❌ شماره نامعتبر")
                    return

                selected = records[idx]

                print("\n" + "-" * 60)
                print(f"  ⚠️  آیا مطمئن هستید که می‌خواهید این رکورد را حذف کنید؟")
                print(f"     • شناسه   : {selected['id']}")
                print(f"     • زمان    : {selected['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     • نوع     : {selected['punch_name']}")
                print("-" * 60)

                confirm = input("  تایید حذف (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = analyzer.delete_attendance_record(selected['id'])
                print(f"\n  {result['message']}")

            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ خطا: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")

    def _update_punch_inline(self, user_id: str, from_date: date, to_date: date):
        """تغییر وضعیت در زمینه گزارش کاربر"""
        print("\n" + "-" * 70)
        print("  🔄 تغییر وضعیت (ورود/خروج)")
        print("-" * 70)

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            analyzer = AttendanceAnalyzer()
            try:
                records = analyzer.get_attendance_records_by_date(user_id, g_date)

                if not records:
                    print(f"\n  ⚠️  هیچ رکوردی برای این کاربر در این تاریخ یافت نشد")
                    return

                j_date_display = jdatetime.date.fromgregorian(date=g_date)
                print(f"\n  📋 رکوردهای کاربر {user_id} در تاریخ {j_date_display.strftime('%Y/%m/%d')}:")
                print("  " + "-" * 60)
                print(f"  {'#':<4} {'شناسه':<8} {'زمان':<12} {'نوع فعلی':<10}")
                print("  " + "-" * 60)

                for i, r in enumerate(records, 1):
                    time_str = r['timestamp'].strftime("%H:%M:%S")
                    print(f"  {i:<4} {r['id']:<8} {time_str:<12} {r['punch_name']:<10}")

                print("  " + "-" * 60)

                choice = input("\n  شماره رکورد برای تغییر (یا 0 برای انصراف): ").strip()
                if choice == '0' or not choice:
                    print("  ❌ عملیات لغو شد")
                    return

                idx = int(choice) - 1
                if idx < 0 or idx >= len(records):
                    print("  ❌ شماره نامعتبر")
                    return

                selected = records[idx]

                current_name = selected['punch_name']
                new_punch = 1 if selected['punch'] == 0 else 0
                new_name = "خروج" if new_punch == 1 else "ورود"

                print("\n" + "-" * 60)
                print(f"  🔄 تغییر وضعیت:")
                print(f"     • شناسه      : {selected['id']}")
                print(f"     • زمان       : {selected['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     • وضعیت فعلی : {current_name}")
                print(f"     • وضعیت جدید : {new_name}")
                print("-" * 60)

                confirm = input("  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = analyzer.update_attendance_punch(selected['id'], new_punch)
                print(f"\n  {result['message']}")

            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ خطا: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")

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

    def _add_attendance_record(self):
        """افزودن دستی رکورد تردد"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 70)
        print("  ➕ افزودن رکورد تردد دستی")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()
        time_str = input("  🕐 ساعت (مثال: 08:30): ").strip()

        print("\n  نوع تردد:")
        print("    0. ورود (Check-in)")
        print("    1. خروج (Check-out)")
        punch_str = input("  انتخاب [0/1]: ").strip()

        try:
            # تبدیل تاریخ شمسی و ساخت datetime
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            # ترکیب تاریخ و ساعت
            hour, minute = map(int, time_str.split(':'))
            timestamp = datetime(g_date.year, g_date.month, g_date.day, hour, minute)

            punch = int(punch_str)
            if punch not in [0, 1]:
                print("  ❌ نوع تردد باید 0 یا 1 باشد")
                return

            # نمایش پیش‌نمایش
            punch_name = "ورود" if punch == 0 else "خروج"
            j_date_display = jdatetime.date.fromgregorian(date=g_date)

            print("\n" + "-" * 70)
            print(f"  📋 پیش‌نمایش:")
            print(f"     • کاربر      : {user_id}")
            print(f"     • تاریخ      : {j_date_display.strftime('%Y/%m/%d')}")
            print(f"     • ساعت       : {timestamp.strftime('%H:%M')}")
            print(f"     • نوع        : {punch_name}")
            print("-" * 70)

            confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            analyzer = AttendanceAnalyzer()
            try:
                result = analyzer.add_attendance_record(user_id, timestamp, punch)
                print(f"\n  {result['message']}")
            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ فرمت تاریخ یا ساعت نامعتبر است: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")

    def _delete_attendance_record(self):
        """حذف یک رکورد تردد"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 70)
        print("  🗑️  حذف رکورد تردد")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            analyzer = AttendanceAnalyzer()
            try:
                records = analyzer.get_attendance_records_by_date(user_id, g_date)

                if not records:
                    print(f"\n  ⚠️  هیچ رکوردی برای این کاربر در این تاریخ یافت نشد")
                    return

                # نمایش لیست رکوردها
                j_date_display = jdatetime.date.fromgregorian(date=g_date)
                print(f"\n  📋 رکوردهای کاربر {user_id} در تاریخ {j_date_display.strftime('%Y/%m/%d')}:")
                print("  " + "-" * 60)
                print(f"  {'#':<4} {'شناسه':<8} {'زمان':<12} {'نوع':<10}")
                print("  " + "-" * 60)

                for i, r in enumerate(records, 1):
                    time_str = r['timestamp'].strftime("%H:%M:%S")
                    print(f"  {i:<4} {r['id']:<8} {time_str:<12} {r['punch_name']:<10}")

                print("  " + "-" * 60)

                # انتخاب رکورد برای حذف
                choice = input("\n  شماره رکورد برای حذف (یا 0 برای انصراف): ").strip()
                if choice == '0' or not choice:
                    print("  ❌ عملیات لغو شد")
                    return

                idx = int(choice) - 1
                if idx < 0 or idx >= len(records):
                    print("  ❌ شماره نامعتبر")
                    return

                selected = records[idx]

                # تایید نهایی
                print("\n" + "-" * 60)
                print(f"  ⚠️  آیا مطمئن هستید که می‌خواهید این رکورد را حذف کنید؟")
                print(f"     • شناسه   : {selected['id']}")
                print(f"     • زمان    : {selected['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     • نوع     : {selected['punch_name']}")
                print("-" * 60)

                confirm = input("  تایید حذف (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = analyzer.delete_attendance_record(selected['id'])
                print(f"\n  {result['message']}")

            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ خطا: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")

    def _update_attendance_punch(self):
        """تغییر وضعیت (ورود/خروج) یک رکورد"""
        from core.attendance_analyzer import AttendanceAnalyzer

        print("\n" + "=" * 70)
        print("  🔄 تغییر وضعیت (ورود/خروج) رکورد")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/24): ").strip()

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()

            analyzer = AttendanceAnalyzer()
            try:
                records = analyzer.get_attendance_records_by_date(user_id, g_date)

                if not records:
                    print(f"\n  ⚠️  هیچ رکوردی برای این کاربر در این تاریخ یافت نشد")
                    return

                # نمایش لیست رکوردها
                j_date_display = jdatetime.date.fromgregorian(date=g_date)
                print(f"\n  📋 رکوردهای کاربر {user_id} در تاریخ {j_date_display.strftime('%Y/%m/%d')}:")
                print("  " + "-" * 60)
                print(f"  {'#':<4} {'شناسه':<8} {'زمان':<12} {'نوع فعلی':<10}")
                print("  " + "-" * 60)

                for i, r in enumerate(records, 1):
                    time_str = r['timestamp'].strftime("%H:%M:%S")
                    print(f"  {i:<4} {r['id']:<8} {time_str:<12} {r['punch_name']:<10}")

                print("  " + "-" * 60)

                # انتخاب رکورد
                choice = input("\n  شماره رکورد برای تغییر (یا 0 برای انصراف): ").strip()
                if choice == '0' or not choice:
                    print("  ❌ عملیات لغو شد")
                    return

                idx = int(choice) - 1
                if idx < 0 or idx >= len(records):
                    print("  ❌ شماره نامعتبر")
                    return

                selected = records[idx]

                # انتخاب نوع جدید
                current_name = selected['punch_name']
                new_punch = 1 if selected['punch'] == 0 else 0
                new_name = "خروج" if new_punch == 1 else "ورود"

                print("\n" + "-" * 60)
                print(f"  🔄 تغییر وضعیت:")
                print(f"     • شناسه      : {selected['id']}")
                print(f"     • زمان       : {selected['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"     • وضعیت فعلی : {current_name}")
                print(f"     • وضعیت جدید : {new_name}")
                print("-" * 60)

                confirm = input("  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = analyzer.update_attendance_punch(selected['id'], new_punch)
                print(f"\n  {result['message']}")

            finally:
                analyzer.close()

        except ValueError as e:
            print(f"\n  ❌ خطا: {e}")
        except Exception as e:
            print(f"\n  ❌ خطا: {e}")