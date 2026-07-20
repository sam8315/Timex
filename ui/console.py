from typing import Dict
from datetime import datetime, timedelta,date
import jdatetime
from core.device_manager import DeviceManager
from core.attendance_analyzer import AttendanceAnalyzer
from core.employee_manager import EmployeeManager
from models.user import User
from models.contract import Contract
from models.leave_request import LeaveRequest


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
        """نمایش منوی اصلی (ساده و گروه‌بندی شده)"""
        self.clear()
        self.header("سیستم مدیریت حضور و غیاب")

        status = "🟢 متصل" if self.connected else "🔴 قطع"
        print(f"\n  وضعیت: {status} | دستگاه: {self.manager.ip}:{self.manager.port}")

        print("\n┌─────────────────────────────────────────┐")
        print("│  🔌 مدیریت دستگاه                       │")
        print("│  1. اتصال/قطع/اطلاعات/تنظیمات دستگاه    │")
        print("│                                         │")
        print("│  👥 کاربران و رکوردها                   │")
        print("│  2. مدیریت کاربران دستگاه               │")
        print("│  3. مدیریت رکوردهای تردد                │")
        print("│                                         │")
        print("│  🗄️  دیتابیس                            │")
        print("│  4. دیتابیس و Migration                 │")
        print("│                                         │")
        print("│  🔍 تحلیل و ویرایش                      │")
        print("│  5. تحلیل و ویرایش ترددها               │")
        print("│                                         │")
        print("│  📑 مدیریت مرخصی                        │")
        print("│  6. قراردادها                           │")
        print("│  7. تعطیلات، شارژ و درخواست مرخصی       │")
        print("│                                         │")
        print("│  📅 گزارش‌ها                             │")
        print("│  8. گزارش‌ها و وضعیت روزانه             │")
        print("│  9. خروجی اکسل                          │")
        print("│                                         │")
        print("│  👥 سایر                                │")
        print("│  10. اطلاعات کارمندان                   │")
        print("│                                         │")
        print("│  0. خروج                                │")
        print("└─────────────────────────────────────────┘")

        return input("\n  انتخاب شما: ").strip()

    def run(self):
        """اجرای حلقه اصلی"""
        while True:
            choice = self.show_menu()

            if choice == '1':
                self._device_menu()
            elif choice == '2':
                self._users_menu()
            elif choice == '3':
                self._attendance_menu()
            elif choice == '4':
                self._database_menu()
            elif choice == '5':
                self._analysis_menu()
            elif choice == '6':
                self._contracts_menu()
            elif choice == '7':
                self._leave_menu()
            elif choice == '8':
                self._reports_menu()
            elif choice == '9':
                self._excel_menu()
            elif choice == '10':
                self._employee_menu()
            elif choice == '0':
                self._disconnect()
                print("\n👋 خدانگهدار!")
                break
            else:
                print("\n❌ انتخاب نامعتبر")

            input("\n⏎ برای ادامه Enter بزنید...")

    # ============================================
    # زیرمنوها
    # ============================================

    def _device_menu(self):
        """زیرمنوی مدیریت دستگاه"""
        while True:
            self.clear()
            self.header("🔌 مدیریت دستگاه")
            print("\n  1. اتصال به دستگاه")
            print("  2. قطع اتصال")
            print("  3. اطلاعات دستگاه")
            print("  4. همگام‌سازی زمان")
            print("  5. ریستارت دستگاه")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._connect()
            elif choice == '2': self._disconnect()
            elif choice == '3': self._show_device_info()
            elif choice == '4': self._sync_time()
            elif choice == '5': self._restart()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _users_menu(self):
        """زیرمنوی کاربران دستگاه"""
        while True:
            self.clear()
            self.header("👥 کاربران دستگاه")
            print("\n  1. لیست کاربران")
            print("  2. جستجو بر اساس UID")
            print("  3. جستجو بر اساس کد پرسنلی")
            print("  4. جستجوی چندگانه")
            print("  5. همگام‌سازی کاربران با دیتابیس")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._show_users()
            elif choice == '2': self._find_user_by_user_id()
            elif choice == '3': self._find_user_by_code()
            elif choice == '4': self._search_users()
            elif choice == '5': self._sync_users_to_db()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _attendance_menu(self):
        """زیرمنوی رکوردهای تردد"""
        while True:
            self.clear()
            self.header("📊 رکوردهای تردد")
            print("\n  1. رکوردهای تردد")
            print("  2. رکوردهای یک روز خاص")
            print("  3. پاک کردن رکوردها")
            print("  4. همگام‌سازی رکوردها با دیتابیس")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._show_attendance()
            elif choice == '2': self._show_attendance_by_date()
            elif choice == '3': self._clear_attendance()
            elif choice == '4': self._sync_attendance_to_db()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _database_menu(self):
        """زیرمنوی دیتابیس"""
        while True:
            self.clear()
            self.header("🗄️  دیتابیس و Migration")
            print("\n  1. انتقال کامل از MySQL")
            print("  2. همگام‌سازی تدریجی از MySQL")
            print("  3. تست اتصال به MySQL")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._migrate_from_mysql()
            elif choice == '2': self._sync_from_mysql()
            elif choice == '3': self._test_mysql_connection()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _analysis_menu(self):
        """زیرمنوی تحلیل و ویرایش"""
        while True:
            self.clear()
            self.header("🔍 تحلیل و ویرایش ترددها")
            print("\n  📊 تحلیل:")
            print("  1. بررسی ترددهای ناقص")
            print("  2. آمار کلی ترددها")
            print("  3. جزئیات تردد یک کاربر (با ویرایش)")
            print("\n  ✏️  ویرایش مستقیم:")
            print("  4. افزودن رکورد دستی")
            print("  5. حذف رکورد")
            print("  6. تغییر وضعیت (ورود/خروج)")
            print("  7. بازیابی رکورد حذف شده")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._show_incomplete_attendances()
            elif choice == '2': self._show_attendance_statistics()
            elif choice == '3': self._show_user_attendance_detail()
            elif choice == '4': self._add_attendance_record()
            elif choice == '5': self._delete_attendance_record()
            elif choice == '6': self._update_attendance_punch()
            elif choice == '7': pass  # بازیابی
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _contracts_menu(self):
        """زیرمنوی قراردادها"""
        while True:
            self.clear()
            self.header("📑 مدیریت قراردادها")
            print("\n  1. افزودن قرارداد جدید")
            print("  2. مشاهده قراردادهای یک کاربر")
            print("  3. مشاهده تمام قراردادها")
            print("  4. ویرایش قرارداد")
            print("  5. قراردادهای نزدیک به پایان")
            print("  6. شارژ مرخصی استحقاقی سالانه")
            print("  7. آمار قراردادها")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._add_contract()
            elif choice == '2': self._show_user_contracts()
            elif choice == '3': self._show_all_contracts()
            elif choice == '4': self._update_contract()
            elif choice == '5': self._show_expiring_contracts()
            elif choice == '6': self._initialize_yearly_leave()
            elif choice == '7': self._show_contracts_summary()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")
    def _leave_menu(self):
        """زیرمنوی تعطیلات و مرخصی"""
        while True:
            self.clear()
            self.header("🏖️  تعطیلات، شارژ و درخواست مرخصی")
            print("\n  🏖️  تعطیلات:")
            print("  1. افزودن تعطیلی")
            print("  2. لیست تعطیلات سال")
            print("  3. حذف تعطیلی")
            print("  4. بررسی تعطیلی یک تاریخ")
            print("\n  💰 شارژ مرخصی:")
            print("  5. شارژ استعلاجی/تشویقی/بدون حقوق")
            print("  6. انتقال مانده از سال قبل")
            print("  7. مشاهده مانده مرخصی")
            print("  8. تاریخچه تراکنش‌ها")
            print("\n  📝 درخواست مرخصی:")
            print("  9. ثبت درخواست جدید")
            print("  10. لیست درخواست‌های در انتظار")
            print("  11. تایید/رد درخواست")
            print("  12. درخواست‌های یک کاربر")
            print("  13. آمار درخواست‌ها")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._add_holiday()
            elif choice == '2': self._show_year_holidays()
            elif choice == '3': self._delete_holiday()
            elif choice == '4': self._check_holiday()
            elif choice == '5': self._credit_leave()
            elif choice == '6': self._carryover_leave()
            elif choice == '7': self._show_leave_balance()
            elif choice == '8': self._show_leave_transactions()
            elif choice == '9': self._create_leave_request()
            elif choice == '10': self._show_pending_requests()
            elif choice == '11': self._approve_reject_request()
            elif choice == '12': self._show_user_requests()
            elif choice == '13': self._show_request_statistics()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _reports_menu(self):
        """زیرمنوی گزارش‌ها"""
        while True:
            self.clear()
            self.header("📅 گزارش‌ها و وضعیت روزانه")
            print("\n  📅 وضعیت روزانه:")
            print("  1. تعیین دستی وضعیت")
            print("  2. گزارش وضعیت یک روز")
            print("  3. گزارش ماهانه یک کاربر")
            print("  4. گزارش ماهانه همه کاربران")
            print("\n  📊 گزارش‌های تحلیلی:")
            print("  5. گزارش غیبت‌ها")
            print("  6. گزارش مرخصی‌ها")
            print("  7. 📊 گزارش تحلیلی ماهانه (جدید) 🆕")  # 🆕
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._set_manual_status()
            elif choice == '2': self._show_daily_report()
            elif choice == '3': self._show_user_monthly_report()
            elif choice == '4': self._show_all_users_monthly_report()
            elif choice == '5': self._show_absent_report()
            elif choice == '6': self._show_leave_report()
            elif choice == '7': self._show_analytical_monthly_report()  # 🆕
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _excel_menu(self):
        """زیرمنوی خروجی اکسل"""
        while True:
            self.clear()
            self.header("📤 خروجی اکسل")
            print("\n  1. گزارش ماهانه")
            print("  2. گزارش غیبت‌ها")
            print("  3. گزارش مرخصی‌ها")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._export_monthly_to_excel()
            elif choice == '2': self._export_absent_to_excel()
            elif choice == '3': self._export_leave_to_excel()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _employee_menu(self):
        """زیرمنوی اطلاعات کارمندان"""
        while True:
            self.clear()
            self.header("👥 اطلاعات کارمندان")
            print("\n  1. افزودن اطلاعات کارمند")
            print("  2. ویرایش اطلاعات کارمند")
            print("  3. مشاهده اطلاعات کارمند")
            print("  4. لیست کارمندان")
            print("  5. جستجو در اطلاعات")
            print("  6. آمار کارمندان")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._add_employee_info()
            elif choice == '2': self._update_employee_info()
            elif choice == '3': self._show_employee_info()
            elif choice == '4': self._list_all_employees()
            elif choice == '5': self._search_employees()
            elif choice == '6': self._show_employee_statistics()
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")
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

    def _add_contract(self):
        """افزودن قرارداد جدید"""
        from core.contract_manager import ContractManager

        print("\n" + "=" * 70)
        print("  📝 افزودن قرارداد جدید")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        # ✅ دریافت نام کاربر قبل از ادامه
        emp_manager = EmployeeManager()
        try:
            full_name = emp_manager.get_full_name(user_id)

            # بررسی وجود کاربر در جدول users
            user = emp_manager.db.query(User).filter(User.user_id == user_id).first()
            if not user:
                print(f"\n  ❌ کاربر با کد {user_id} یافت نشد")
                return
        finally:
            emp_manager.close()

        # انواع قرارداد
        print("\n  📋 انواع قرارداد:")
        print("    1. رسمی")
        print("    2. وظیفه")
        print("    3. خریدخدمت")
        print("    4. قراردادی")
        print("    5. پزشک")
        print("    6. سایر (دستی)")
        type_choice = input("  انتخاب [1-6]: ").strip()

        type_map = {
            '1': 'رسمی', '2': 'وظیفه', '3': 'خریدخدمت',
            '4': 'قراردادی', '5': 'پزشک'
        }
        contract_type = type_map.get(type_choice, input("  نام قرارداد: ").strip())

        if not contract_type:
            print("  ❌ نوع قرارداد نمی‌تواند خالی باشد")
            return

        # تاریخ شروع
        today_j = jdatetime.date.today()
        first_day_j = jdatetime.date(jdatetime.date.today().year, 1, 1)
        start_str = input(f"  📅 تاریخ شروع (شمسی) [پیش‌فرض: {first_day_j.strftime('%Y/%m/%d')}]: ").strip()
        try:
            if start_str:
                start_date = jdatetime.datetime.strptime(start_str, "%Y/%m/%d").date().togregorian()
            else:
                start_date = first_day_j.togregorian()
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        # تاریخ پایان (آخرین روز سال جاری)
        year = today_j.year
        next_year_start = jdatetime.date(year + 1, 1, 1)
        last_day_j = next_year_start - timedelta(days=1)  # آخرین روز سال جاری (۲۹ یا ۳۰ اسفند)

        # نمایش پیش‌فرض به کاربر
        default_end_str = last_day_j.strftime('%Y/%m/%d')
        end_str = input(f"  📅 تاریخ پایان (شمسی) [پیش‌فرض: {default_end_str}]: ").strip()
        try:
            if end_str:
                end_date = jdatetime.datetime.strptime(end_str, "%Y/%m/%d").date().togregorian()
            else:
                end_date = last_day_j.togregorian()  # استفاده از پیش‌فرض (آخر سال)
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        # مقادیر پیش‌فرض بر اساس نوع قرارداد
        defaults = {
            'رسمی': (35, 0, 0, 0),
            'وظیفه': (36, 0, 0, 0),
            'خریدخدمت': (30, 0, 0, 0),
            'قراردادی': (30, 0, 0, 0),
            'پزشک': (0, 0, 0, 0),
        }

        default_values = defaults.get(contract_type, (0, 0, 0, 0))

        print(f"\n  💡 مقادیر پیش‌فرض برای قرارداد {contract_type}:")
        print(f"     • مرخصی استحقاقی سالانه: {default_values[0]} روز")
        print(f"     • مرخصی استعلاجی: {default_values[1]} روز")
        print(f"     • مرخصی تشویقی: {default_values[2]} روز")
        print(f"     • مرخصی بدون حقوق: {default_values[3]} روز")

        annual = input(f"  مرخصی استحقاقی [{default_values[0]}]: ").strip()
        annual = int(annual) if annual else default_values[0]

        sick = input(f"  مرخصی استعلاجی [{default_values[1]}]: ").strip()
        sick = int(sick) if sick else default_values[1]

        reward = input(f"  مرخصی تشویقی [{default_values[2]}]: ").strip()
        reward = int(reward) if reward else default_values[2]

        unpaid = input(f"  مرخصی بدون حقوق [{default_values[3]}]: ").strip()
        unpaid = int(unpaid) if unpaid else default_values[3]

        description = input("  📝 توضیحات (اختیاری): ").strip()

        # پیش‌نمایش
        j_start = jdatetime.date.fromgregorian(date=start_date)
        j_end = jdatetime.date.fromgregorian(date=end_date) if end_date else "نامحدود"

        print("\n" + "-" * 70)
        print("  📋 پیش‌نمایش قرارداد:")
        print(f"     • کد پرسنلی       : {user_id}")
        print(f"     • 👤 نام کاربر    : {full_name}")  # ✅ نمایش نام کاربر
        print(f"     • نوع قرارداد     : {contract_type}")
        print(f"     • تاریخ شروع      : {j_start.strftime('%Y/%m/%d')}")
        print(f"     • تاریخ پایان     : {j_end if isinstance(j_end, str) else j_end.strftime('%Y/%m/%d')}")
        print(f"     • استحقاقی سالانه : {annual} روز")
        print(f"     • استعلاجی        : {sick} روز")
        print(f"     • تشویقی          : {reward} روز")
        print(f"     • بدون حقوق       : {unpaid} روز")
        if description:
            print(f"     • توضیحات         : {description}")
        print("-" * 70)

        confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("  ❌ عملیات لغو شد")
            return

        manager = ContractManager()
        try:
            result = manager.add_contract(
                user_id=user_id,
                contract_type=contract_type,
                start_date=start_date,
                end_date=end_date,
                annual_leave=annual,
                sick_leave=sick,
                reward_leave=reward,
                unpaid_leave=unpaid,
                description=description
            )
            print(f"\n  {result['message']}")
        finally:
            manager.close()

    def _show_user_contracts(self):
        """نمایش قراردادهای یک کاربر"""
        from core.contract_manager import ContractManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 80)
        print("  📑 قراردادهای کاربر")
        print("=" * 80)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        manager = ContractManager()
        emp_manager = EmployeeManager()
        try:
            contracts = manager.get_user_contracts(user_id)

            if not contracts:
                print(f"\n  ⚠️  هیچ قراردادی برای کاربر {user_id} یافت نشد")
                return

            # ✅ دریافت نام کامل
            full_name = emp_manager.get_full_name(user_id)
            print(f"\n  👤 کاربر: {full_name} (کد: {user_id})")

            print("\n  ┌──────┬────────────────┬────────────┬────────────┬──────┬──────┬───────┬──────┬──────────┐")
            print("  │ شماره │   نوع قرارداد  │   شروع    │   پایان    │ استحق│ استعل│ تشویق │ بدون │  وضعیت   │")
            print("  ├──────┼────────────────┼────────────┼────────────┼──────┼──────┼───────┼──────┼──────────┤")

            for c in contracts:
                j_start = jdatetime.date.fromgregorian(date=c.start_date)
                j_end = jdatetime.date.fromgregorian(date=c.end_date) if c.end_date else "نامحدود"

                end_str = j_end if isinstance(j_end, str) else j_end.strftime("%Y/%m/%d")

                # بررسی فعال بودن
                is_active = manager.get_active_contract(user_id, date.today()) and \
                            manager.get_active_contract(user_id, date.today()).id == c.id

                status = "✅ فعال" if is_active else "⏸️ غیرفعال"

                print(f"  │ {c.id:<4} │ {c.contract_type:<14} │ "
                      f"{j_start.strftime('%Y/%m/%d')} │ {end_str:<10} │ "
                      f"{c.annual_leave_days:<4} │ {c.sick_leave_days:<4} │ "
                      f"{c.reward_leave_days:<4} │ {c.unpaid_leave_days:<4} │ {status:<8} │")

            print("  └──────┴────────────────┴────────────┴────────────┴──────┴──────┴───────┴──────┴──────────┘")

        finally:
            manager.close()
            emp_manager.close()

    def _initialize_yearly_leave(self):
        """شارژ مرخصی استحقاقی سالانه"""
        from core.contract_manager import ContractManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  💰 شارژ مرخصی استحقاقی سالانه")
        print("=" * 70)

        print("\n  📋 نوع شارژ:")
        print("    1. یک کاربر خاص")
        print("    2. همه کاربران")
        choice = input("  انتخاب [1/2]: ").strip()

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = ContractManager()
        emp_manager = EmployeeManager()
        try:
            if choice == '1':
                user_id = input("  📛 کد پرسنلی کاربر: ").strip()
                if not user_id:
                    print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
                    return

                # ✅ محاسبه مرخصی با در نظر گرفتن تمام قراردادها
                calc = manager.calculate_yearly_leave(user_id, year)

                if not calc['success']:
                    print(f"\n  {calc['message']}")
                    return

                full_name = emp_manager.get_full_name(user_id)

                # نمایش پیش‌نمایش دقیق
                print("\n" + "-" * 70)
                print(f"  👤 کاربر: {full_name} (کد: {user_id})")
                print(f"  📅 سال شمسی: {year}")
                print(f"  📊 تعداد قراردادهای فعال در سال: {calc['contracts_count']}")

                if calc['contracts_count'] > 1:
                    print("\n  📋 جزئیات محاسبه:")
                    print("  " + "-" * 55)
                    print(f"  {'نوع قرارداد':<15} {'استحقاقی':<10} {'استعلاجی':<10} {'تشویقی':<10}")
                    print("  " + "-" * 55)

                    for c in calc['contracts']:
                        print(f"  {c['contract_type']:<15} {c['annual']:<10} {c['sick']:<10} {c['reward']:<10}")

                    print("  " + "-" * 55)
                    print(
                        f"  {'مجموع':<15} {calc['total_annual']:<10} {calc['total_sick']:<10} {calc['total_reward']:<10}")
                    print("  " + "-" * 55)
                else:
                    print(f"\n  📋 قرارداد: {calc['contracts'][0]['contract_type']}")
                    print(f"     • استحقاقی سالانه : {calc['total_annual']} روز")
                    print(f"     • استعلاجی        : {calc['total_sick']} روز")
                    print(f"     • تشویقی          : {calc['total_reward']} روز")
                    print(f"     • بدون حقوق       : {calc['total_unpaid']} روز")

                print("-" * 70)

                confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = manager.initialize_yearly_balances(user_id, year)

                # ✅ اگر قبلاً شارژ شده، از کاربر بپرس
                if not result['success'] and result.get('already_charged'):
                    print(f"\n  {result['message']}")
                    print(f"  💡 مقدار جدید محاسبه شده: {result['new_amount']} روز")
                    print(f"  💡 تفاوت: {result['new_amount'] - result['current_balance']} روز")

                    reset_confirm = input("\n  ⚠️  آیا می‌خواهید بازنشانی و شارژ مجدد کنید؟ (بله/خیر): ").strip()
                    if reset_confirm.lower() in ['بله', 'yes', 'y']:
                        result = manager.initialize_yearly_balances(user_id, year, force_reset=True)
                        print(f"\n  {result['message']}")
                    else:
                        print("  ❌ عملیات لغو شد")
                else:
                    print(f"\n  {result['message']}")


            elif choice == '2':

                # ✅ پرسش اول: آیا بازنشانی انجام شود؟

                print("\n  📋 حالت شارژ:")

                print("    1. فقط کاربرانی که هنوز شارژ نشده‌اند")

                print("    2. بازنشانی همه کاربران (شارژ قبلی حذف و مجدد شارژ می‌شود)")

                mode = input("  انتخاب [1/2] [پیش‌فرض: 1]: ").strip() or '1'

                force_reset = (mode == '2')

                if force_reset:

                    confirm_msg = f"\n  ⚠️  هشدار: شارژ قبلی همه کاربران حذف و با مقادیر جدید جایگزین می‌شود!"

                    confirm_msg += f"\n  ⚠️  آیا مطمئن هستید؟ (بله/خیر): "

                else:

                    confirm_msg = f"\n  ⚠️  شارژ مرخصی کاربران شارژ نشده برای سال شمسی {year}؟ (بله/خیر): "

                confirm = input(confirm_msg).strip()

                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")

                    return

                print("\n  ⏳ در حال پردازش...")

                stats = manager.initialize_all_users_for_year(year, force_reset=force_reset)

                print(f"\n  📊 نتیجه:")

                print(f"     • کل کاربران           : {stats['total']}")

                print(f"     • شارژ موفق (جدید)     : {stats['success'] - stats['reset']} ✅")

                if stats['reset'] > 0:
                    print(f"     • بازنشانی شده         : {stats['reset']} 🔄")

                print(f"     • قبلاً شارژ شده (رد)  : {stats['skipped']} ⚠️")

                print(f"     • خطا (بدون قرارداد)   : {stats['failed']} ❌")

            else:
                print("  ❌ انتخاب نامعتبر")

        finally:
            manager.close()
            emp_manager.close()

    def _show_contracts_summary(self):
        """نمایش آمار قراردادها"""
        from core.contract_manager import ContractManager

        print("\n" + "=" * 70)
        print("  📊 آمار قراردادها")
        print("=" * 70)

        manager = ContractManager()
        try:
            summary = manager.get_contract_summary()

            print(f"\n  📋 وضعیت قراردادها:")
            print(f"     • کل قراردادها          : {summary['total_contracts']}")
            print(f"     • قراردادهای فعال       : {summary['active_contracts']} ✅")
            print(f"     • کاربران دارای قرارداد : {summary['users_with_contract']}")
            print(f"     • کاربران بدون قرارداد  : {summary['users_without_contract']} ⚠️")

            if summary['users_without_contract'] > 0:
                print("\n  ⚠️  کاربران بدون قرارداد:")
                users_without = manager.db.query(User).filter(
                    ~User.user_id.in_(manager.db.query(Contract.user_id))
                ).all()

                for u in users_without[:10]:  # فقط ۱۰ نفر اول
                    print(f"     • {u.user_id} - {u.name}")

                if len(users_without) > 10:
                    print(f"     ... و {len(users_without) - 10} نفر دیگر")

        finally:
            manager.close()

    # ============================================
    # مدیریت تعطیلات
    # ============================================

    def _add_holiday(self):
        """افزودن تعطیلی"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 70)
        print("  🏖️  افزودن تعطیلی")
        print("=" * 70)

        date_str = input("\n  📅 تاریخ (شمسی - مثال: 1405/05/15): ").strip()
        if not date_str:
            print("  ❌ تاریخ نمی‌تواند خالی باشد")
            return

        try:
            # ✅ تبدیل صحیح: jdatetime → gregorian
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()  # این خط حیاتی است!

            # ✅ بررسی تبدیل
            print(f"  🔍 تاریخ شمسی: {j_date.strftime('%Y/%m/%d')}")
            print(f"  🔍 تاریخ میلادی: {g_date}")

        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        # بررسی جمعه بودن
        if g_date.weekday() == 4:
            print("  ⚠️  این تاریخ جمعه است و به طور خودکار تعطیل محسوب می‌شود")
            return

        title = input("  📝 عنوان تعطیلی: ").strip()
        if not title:
            print("  ❌ عنوان نمی‌تواند خالی باشد")
            return

        national = input("  تعطیل ملی است؟ (بله/خیر) [پیش‌فرض: بله]: ").strip()
        is_national = national.lower() not in ['خیر', 'no', 'n']

        # پیش‌نمایش
        day_name = self._get_day_name(g_date)
        print("\n" + "-" * 70)
        print("  📋 پیش‌نمایش:")
        print(f"     • تاریخ شمسی : {j_date.strftime('%Y/%m/%d')} ({day_name})")
        print(f"     • تاریخ میلادی: {g_date}")
        print(f"     • عنوان      : {title}")
        print(f"     • نوع        : {'ملی' if is_national else 'محدود'}")
        print("-" * 70)

        confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("  ❌ عملیات لغو شد")
            return

        manager = HolidayManager()
        try:
            # ✅ ارسال g_date (میلادی) نه j_date (شمسی)
            result = manager.add_holiday(g_date, title, is_national)
            print(f"\n  {result['message']}")
        finally:
            manager.close()

    def _show_year_holidays(self):
        """نمایش تعطیلات یک سال"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 70)
        print("  📅 لیست تعطیلات سال")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال (شمسی) [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = HolidayManager()
        try:
            # ✅ اصلاح: تبدیل سال شمسی به میلادی
            j_from = jdatetime.date(year, 1, 1)
            # روز آخر سال شمسی: 29 اسفند (یا 30 در سال کبیسه)
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

            from_date = j_from.togregorian()
            to_date = j_to.togregorian()

            print(f"\n  🔍 جستجو از {from_date} تا {to_date} (میلادی)")
            print(f"  🔍 معادل شمسی: {j_from.strftime('%Y/%m/%d')} تا {j_to.strftime('%Y/%m/%d')}")

            holidays = manager.get_holidays_in_range(from_date, to_date)

            if not holidays:
                print(f"\n  ⚠️  هیچ تعطیلی در سال {year} یافت نشد (فقط جمعه‌ها)")
                return

            print(f"\n  📊 تعداد کل تعطیلات: {len(holidays)}")
            print(f"     • جمعه‌ها          : {sum(1 for h in holidays if h['type'] == 'friday')}")
            print(f"     • تعطیلات ثبت شده : {sum(1 for h in holidays if h['type'] == 'custom')}")

            print("\n  ┌────────────┬─────────┬──────────────────────────────────────┐")
            print("  │ تاریخ      │ روز     │ عنوان                                │")
            print("  ├────────────┼─────────┼──────────────────────────────────────┤")

            for h in holidays:
                j_date = jdatetime.date.fromgregorian(date=h['date'])
                day_name = self._get_day_name(h['date'])
                icon = "🟡" if h['type'] == 'friday' else "🔴"

                print(f"  │ {j_date.strftime('%Y/%m/%d')} │ {day_name:<7} │ {icon} {h['title']:<35} │")

            print("  └────────────┴─────────┴──────────────────────────────────────┘")

            # آمار روزهای کاری
            stats = manager.count_working_days(from_date, to_date)
            print(f"\n  📈 آمار سال {year}:")
            print(f"     • کل روزها       : {stats['total_days']}")
            print(f"     • روزهای کاری    : {stats['working_days']} ✅")
            print(f"     • جمعه‌ها         : {stats['fridays']} 🟡")
            print(f"     • سایر تعطیلات   : {stats['holidays']} 🔴")

        finally:
            manager.close()

    def _delete_holiday(self):
        """حذف تعطیلی"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 70)
        print("  🗑️  حذف تعطیلی")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = HolidayManager()
        try:
            # ✅ دریافت تعطیلات با سال شمسی
            holidays = manager.get_custom_holidays(year)

            if not holidays:
                print(f"\n  ⚠️  هیچ تعطیلی ثبت شده‌ای در سال شمسی {year} وجود ندارد")
                print("  💡 توجه: جمعه‌ها به صورت خودکار تعطیل هستند و قابل حذف نیستند")
                return

            # نمایش لیست
            print(f"\n  📋 تعطیلات ثبت شده در سال شمسی {year} ({len(holidays)} مورد):")
            print("  " + "-" * 75)
            print(f"  {'#':<4} {'ID':<6} {'تاریخ شمسی':<12} {'روز':<10} {'نوع':<6} {'عنوان':<30}")
            print("  " + "-" * 75)

            for i, h in enumerate(holidays, 1):
                j_date = jdatetime.date.fromgregorian(date=h.holiday_date)
                day_name = self._get_day_name(h.holiday_date)
                national = "ملی" if h.is_national else "غیرملی"
                print(
                    f"  {i:<4} {h.id:<6} {j_date.strftime('%Y/%m/%d'):<12} {day_name:<10} {national:<6} {h.title:<30}")

            print("  " + "-" * 75)

            # انتخاب
            choice = input("\n  شماره برای حذف (0 = انصراف): ").strip()
            if choice == '0' or not choice:
                print("  ❌ لغو شد")
                return

            try:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(holidays):
                    print("  ❌ شماره نامعتبر")
                    return
            except ValueError:
                print("  ❌ ورودی نامعتبر")
                return

            selected = holidays[idx]
            j_selected = jdatetime.date.fromgregorian(date=selected.holiday_date)

            # تایید
            print(f"\n  ⚠️  حذف تعطیلی: {selected.title}")
            print(f"     تاریخ: {j_selected.strftime('%Y/%m/%d')} ({self._get_day_name(selected.holiday_date)})")

            confirm = input("  تایید (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ لغو شد")
                return

            result = manager.delete_holiday(selected.id)
            print(f"\n  {result['message']}")

        finally:
            manager.close()
    def _check_holiday(self):
        """بررسی تعطیلی یک تاریخ"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 70)
        print("  🔍 بررسی تعطیلی یک تاریخ")
        print("=" * 70)

        date_str = input("\n  📅 تاریخ (شمسی): ").strip()
        if not date_str:
            print("  ❌ تاریخ نمی‌تواند خالی باشد")
            return

        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        manager = HolidayManager()
        try:
            info = manager.get_holiday_info(g_date)
            day_name = self._get_day_name(g_date)

            print("\n" + "-" * 70)
            print(f"  📅 تاریخ: {j_date.strftime('%Y/%m/%d')} ({day_name})")
            print("-" * 70)

            if info['is_holiday']:
                if info['type'] == 'friday':
                    print("  🟡 این روز تعطیل است (جمعه)")
                else:
                    national = "ملی" if info.get('is_national') else "محدود"
                    print(f"  🔴 این روز تعطیل است: {info['title']} ({national})")
            else:
                print("  ✅ این روز کاری است")

            print("-" * 70)

        finally:
            manager.close()

    def _get_day_name(self, d: date) -> str:
        """دریافت نام روز هفته به فارسی"""
        # 0=دوشنبه، 1=سه‌شنبه، ... 4=جمعه، 5=شنبه، 6=یکشنبه
        names = {
            0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
            3: 'پنجشنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه'
        }
        return names.get(d.weekday(), '')

    # ============================================
    # شارژ مرخصی
    # ============================================

    def _credit_leave(self):
        """شارژ مرخصی توسط مدیر"""
        from core.leave_manager import LeaveManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  💰 شارژ مرخصی توسط مدیر")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        # ✅ اضافه شدن گزینه ذخیره سال قبل
        print("\n  📋 نوع مرخصی:")
        print("    1. استعلاجی (SL)")
        print("    2. تشویقی (RL)")
        print("    3. بدون حقوق (UL)")
        print("    4. ذخیره سال قبل (CW)")
        type_choice = input("  انتخاب [1-4]: ").strip()

        type_map = {'1': 'SL', '2': 'RL', '3': 'UL', '4': 'CW'}
        leave_type = type_map.get(type_choice)

        if not leave_type:
            print("  ❌ انتخاب نامعتبر")
            return

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        amount_str = input("  🔢 تعداد روز: ").strip()
        try:
            amount = int(amount_str)
            if amount <= 0:
                print("  ❌ تعداد باید مثبت باشد")
                return
        except ValueError:
            print("  ❌ تعداد نامعتبر")
            return

        description = input("  📝 توضیحات (مثلاً: ذخیره از سال 1404): ").strip()

        manager = LeaveManager()
        emp_manager = EmployeeManager()
        try:
            # نمایش مانده فعلی
            current_balance = manager.get_balance(user_id, year, leave_type)
            type_name = manager.get_leave_type_name(leave_type)
            full_name = emp_manager.get_full_name(user_id)

            print("\n" + "-" * 70)
            print("  📋 پیش‌نمایش:")
            print(f"     • کاربر         : {full_name} ({user_id})")
            print(f"     • نوع مرخصی     : {type_name}")
            print(f"     • سال شمسی      : {year}")
            print(f"     • تعداد         : {amount} روز")
            print(f"     • مانده فعلی    : {current_balance} روز")
            print(f"     • مانده جدید    : {current_balance + amount} روز")
            if description:
                print(f"     • توضیحات       : {description}")
            print("-" * 70)

            confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            result = manager.credit_leave(
                user_id=user_id,
                year=year,
                leave_type=leave_type,
                amount=amount,
                transaction_type='CREDIT',
                description=description
            )
            print(f"\n  {result['message']}")

        finally:
            manager.close()
            emp_manager.close()
    def _carryover_leave(self):
        """انتقال مانده از سال قبل"""
        from core.leave_manager import LeaveManager

        print("\n" + "=" * 70)
        print("  🔄 انتقال مانده مرخصی از سال قبل")
        print("=" * 70)

        today_j = jdatetime.date.today()
        to_year_str = input(f"\n  📅 سال مقصد [پیش‌فرض: {today_j.year}]: ").strip()
        to_year = int(to_year_str) if to_year_str else today_j.year
        from_year = to_year - 1

        print("\n  📋 نوع انتقال:")
        print("    1. یک کاربر خاص")
        print("    2. همه کاربران")
        choice = input("  انتخاب [1/2]: ").strip()

        manager = LeaveManager()
        try:
            if choice == '1':
                user_id = input("  📛 کد پرسنلی کاربر: ").strip()
                if not user_id:
                    print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
                    return

                # نمایش مانده سال قبل
                al_balance = manager.get_balance(user_id, from_year, 'AL')
                cw_balance = manager.get_balance(user_id, from_year, 'CW')
                total = al_balance + cw_balance

                print(f"\n  📊 مانده سال {from_year}:")
                print(f"     • استحقاقی باقی‌مانده : {al_balance} روز")
                print(f"     • ذخیره قبلی         : {cw_balance} روز")
                print(f"     • مجموع قابل انتقال  : {total} روز")

                if total <= 0:
                    print("\n  ⚠️  مانده‌ای برای انتقال وجود ندارد")
                    return

                confirm = input(f"\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                stats = manager.carryover_to_new_year(from_year, to_year, user_id)
                print(f"\n  ✅ انتقال انجام شد: {total} روز به سال {to_year}")

            elif choice == '2':
                confirm = input(f"\n  ⚠️  انتقال مانده همه کاربران از {from_year} به {to_year}؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                stats = manager.carryover_to_new_year(from_year, to_year)
                print(f"\n  📊 نتیجه:")
                print(f"     • کل کاربران      : {stats['total']}")
                print(f"     • انتقال موفق     : {stats['success']} ✅")
                print(f"     • بدون مانده      : {stats['no_balance']} ⚠️")
                print(f"     • خطا             : {stats['failed']} ❌")

            else:
                print("  ❌ انتخاب نامعتبر")

        finally:
            manager.close()

    def _show_leave_balance(self):
        """نمایش مانده مرخصی یک کاربر با چک صحت داده‌ها"""
        from core.leave_manager import LeaveManager
        from core.employee_manager import EmployeeManager
        from sqlalchemy import and_, func
        from models.leave_transaction import LeaveTransaction

        print("\n" + "=" * 80)
        print("  💼 مانده مرخصی کاربر")
        print("=" * 80)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = LeaveManager()
        emp_manager = EmployeeManager()
        try:
            user = manager.db.query(User).filter(User.user_id == user_id).first()
            if not user:
                print(f"\n  ❌ کاربر {user_id} یافت نشد")
                return

            full_name = emp_manager.get_full_name(user_id)

            # ✅ دریافت مانده فعلی از leave_balances
            balances = manager.get_all_balances(user_id, year)
            summary = manager.get_summary_for_user(user_id, year)

            # ✅ محاسبه "کل" و "مصرف" از تراکنش‌ها برای هر نوع مرخصی
            leave_types = ['AL', 'SL', 'RL', 'UL', 'CW']
            calculated_data = {}

            for leave_type in leave_types:
                # مجموع تراکنش‌های مثبت (شارژ)
                total_credit = manager.db.query(
                    func.coalesce(func.sum(LeaveTransaction.amount), 0)
                ).filter(
                    and_(
                        LeaveTransaction.user_id == user_id,
                        LeaveTransaction.year == year,
                        LeaveTransaction.leave_type == leave_type,
                        LeaveTransaction.amount > 0
                    )
                ).scalar()

                # مجموع تراکنش‌های منفی (برداشت)
                total_debit = manager.db.query(
                    func.coalesce(func.sum(LeaveTransaction.amount), 0)
                ).filter(
                    and_(
                        LeaveTransaction.user_id == user_id,
                        LeaveTransaction.year == year,
                        LeaveTransaction.leave_type == leave_type,
                        LeaveTransaction.amount < 0
                    )
                ).scalar()

                # تبدیل به عدد مثبت
                total_debit = abs(total_debit)

                # محاسبه مانده از تراکنش‌ها
                calculated_balance = total_credit - total_debit

                # دریافت balance واقعی از جدول
                actual_balance = balances.get(leave_type, {}).get('balance', 0)

                calculated_data[leave_type] = {
                    'total_credit': total_credit,
                    'total_debit': total_debit,
                    'calculated_balance': calculated_balance,
                    'actual_balance': actual_balance,
                    'is_valid': calculated_balance == actual_balance
                }

            print(f"\n  👤 کاربر: {full_name} (کد: {user_id})")
            print(f"  📅 سال شمسی: {year}")

            # ✅ جدول با چک صحت
            print("\n  ┌─────────────────────┬──────────────┬──────────────┬──────────────┬────────┐")
            print("  │ نوع مرخصی           │ کل (شارژ)    │ استفاده شده │ مانده        │ وضعیت  │")
            print("  ├─────────────────────┼──────────────┼──────────────┼──────────────┼────────┤")

            negative_balances = []
            invalid_balances = []
            total_charged_sum = 0
            total_used_sum = 0
            total_remaining_sum = 0

            for code, data in balances.items():
                calc = calculated_data.get(code, {
                    'total_credit': 0,
                    'total_debit': 0,
                    'calculated_balance': 0,
                    'actual_balance': data['balance'],
                    'is_valid': True
                })

                charged = calc['total_credit']
                used = calc['total_debit']
                remaining = calc['actual_balance']  # استفاده از balance واقعی
                is_valid = calc['is_valid']

                # ✅ رنگ‌بندی مانده
                if remaining < 0:
                    remaining_str = f"{remaining} ❌⚠️"
                    negative_balances.append({
                        'code': code,
                        'name': data['name'],
                        'remaining': remaining
                    })
                elif remaining == 0 and charged > 0:
                    remaining_str = f"{remaining} ⚠️"
                elif remaining == 0 and charged == 0 and used == 0:
                    remaining_str = f"{remaining} —"
                else:
                    remaining_str = f"{remaining} ✅"

                # ✅ وضعیت صحت
                status = "✅" if is_valid else "❌ نامعتبر"

                if not is_valid:
                    invalid_balances.append({
                        'code': code,
                        'name': data['name'],
                        'calculated': calc['calculated_balance'],
                        'actual': calc['actual_balance']
                    })

                print(f"  │ {data['name']:<19} │ {charged:<12} │ {used:<12} │ {remaining_str:<12} │ {status:<6} │")

                total_charged_sum += charged
                total_used_sum += used
                total_remaining_sum += remaining

            print("  └─────────────────────┴──────────────┴──────────────┴──────────────┴────────┘")

            # ✅ هشدار برای عدم تطابق
            if invalid_balances:
                print("\n  " + "=" * 76)
                print("  ❌ هشدار: عدم تطابق در داده‌ها شناسایی شد!")
                print("  " + "=" * 76)
                for inv in invalid_balances:
                    print(f"     • {inv['name']}:")
                    print(f"       - محاسبه شده از تراکنش‌ها: {inv['calculated']} روز")
                    print(f"       - موجود در جدول balance   : {inv['actual']} روز")
                    print(f"       - تفاوت                    : {inv['calculated'] - inv['actual']} روز")
                print("\n  💡 راه‌حل:")
                print("     • اسکریپت 'fix_migrated_leaves.py' را اجرا کنید")
                print("     • یا داده‌ها را دستی اصلاح کنید")
                print("  " + "=" * 76)

            # ✅ هشدار برای مانده‌های منفی
            if negative_balances:
                print("\n  " + "=" * 76)
                print("  ⚠️  هشدار: مانده منفی شناسایی شد!")
                print("  " + "=" * 76)
                for nb in negative_balances:
                    print(f"     • {nb['name']}: {nb['remaining']} روز (بیشتر از مجاز مصرف شده)")
                print("\n  💡 راه‌حل:")
                print("     • از گزینه 'شارژ مرخصی توسط مدیر' (گزینه 7 → 5) استفاده کنید")
                print("  " + "=" * 76)

            # خلاصه
            print(f"\n  📊 تعداد درخواست‌های تایید شده: {summary['approved_requests_count']}")
            print(f"  📊 مجموع کل (شارژ): {total_charged_sum} روز")
            print(f"  📊 مجموع استفاده شده: {total_used_sum} روز")

            if total_remaining_sum < 0:
                print(f"  📊 مجموع مانده: {total_remaining_sum} روز ❌")
            else:
                print(f"  📊 مجموع مانده: {total_remaining_sum} روز ✅")

            if invalid_balances:
                print(f"\n  ❌ تعداد عدم تطابق: {len(invalid_balances)}")
            else:
                print(f"\n  ✅ تمام داده‌ها معتبر هستند")

        finally:
            manager.close()
            emp_manager.close()



    def _show_leave_transactions(self):
        """نمایش تاریخچه تراکنش‌های مرخصی"""
        from core.leave_manager import LeaveManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 90)
        print("  📜 تاریخچه تراکنش‌های مرخصی")
        print("=" * 90)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = LeaveManager()
        emp_manager = EmployeeManager()
        try:
            transactions = manager.get_transactions(user_id, year)

            full_name = emp_manager.get_full_name(user_id)

            if not transactions:
                print(f"\n  ⚠️  هیچ تراکنشی در سال شمسی {year} یافت نشد")
                return

            print(f"\n  👤 کاربر: {full_name} (کد: {user_id})")
            print(f"  📅 سال شمسی: {year}")
            print(f"  📊 تعداد تراکنش‌ها: {len(transactions)}")

            # ✅ مرتب‌سازی از قدیم به جدید برای محاسبه مانده تجمعی
            sorted_transactions = sorted(transactions, key=lambda t: t.created_at)

            # محاسبه مانده تجمعی برای هر نوع مرخصی
            running_balance = {}

            print("\n  ┌────────────┬────────────┬──────┬──────────┬────────────┬──────────────────────┐")
            print("  │ تاریخ      │ نوع مرخصی  │ مقدار│ نوع عمل  │ مانده بعد  │ توضیحات              │")
            print("  ├────────────┼────────────┼──────┼──────────┼────────────┼──────────────────────┤")

            for t in sorted_transactions:
                j_date = jdatetime.date.fromgregorian(date=t.created_at.date())
                type_name = manager.get_leave_type_name(t.leave_type)
                operation = {
                    'CREDIT': '➕ شارژ',
                    'DEBIT': '➖ برداشت',
                    'CARRYOVER': '🔄 انتقال',
                    'INITIAL': '💰 اولیه'
                }.get(t.transaction_type, t.transaction_type)

                desc = (t.description or '')[:20]

                sign = "+" if t.amount > 0 else ""
                amount_str = f"{sign}{t.amount}"

                # ✅ محاسبه مانده تجمعی
                if t.leave_type not in running_balance:
                    running_balance[t.leave_type] = 0
                running_balance[t.leave_type] += t.amount

                balance_after = running_balance[t.leave_type]

                # رنگ‌بندی بر اساس مانده
                if balance_after < 0:
                    balance_str = f"{balance_after} ❌"
                elif balance_after == 0:
                    balance_str = f"{balance_after} ⚠️"
                else:
                    balance_str = f"{balance_after} ✅"

                print(
                    f"  │ {j_date.strftime('%Y/%m/%d')} │ {type_name:<10} │ {amount_str:<4} │ {operation:<8} │ {balance_str:<10} │ {desc:<20} │")

            print("  └────────────┴────────────┴──────┴──────────┴────────────┴──────────────────────┘")

            # ✅ نمایش مانده نهایی
            print("\n  📊 مانده نهایی:")
            for leave_type, balance in running_balance.items():
                type_name = manager.get_leave_type_name(leave_type)
                status = "✅" if balance >= 0 else "❌"
                print(f"     • {type_name:<15} : {balance} روز {status}")

        finally:
            manager.close()
            emp_manager.close()    # ============================================
    # درخواست مرخصی
    # ============================================

    def _create_leave_request(self):
        """ثبت درخواست مرخصی جدید"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 70)
        print("  📝 ثبت درخواست مرخصی")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        print("\n  📋 نوع مرخصی:")
        print("    1. استحقاقی (AL)")
        print("    2. استعلاجی (SL)")
        print("    3. تشویقی (RL)")
        print("    4. بدون حقوق (UL)")
        type_choice = input("  انتخاب [1-4]: ").strip()

        type_map = {'1': 'AL', '2': 'SL', '3': 'RL', '4': 'UL'}
        leave_type = type_map.get(type_choice)

        if not leave_type:
            print("  ❌ انتخاب نامعتبر")
            return

        from_str = input("  📅 از تاریخ (شمسی - مثال: 1405/05/10): ").strip()
        to_str = input("  📅 تا تاریخ (شمسی - مثال: 1405/05/12): ").strip()

        try:
            j_from = jdatetime.datetime.strptime(from_str, "%Y/%m/%d").date()
            j_to = jdatetime.datetime.strptime(to_str, "%Y/%m/%d").date()
            g_from = j_from.togregorian()
            g_to = j_to.togregorian()
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        reason = input("  📝 دلیل مرخصی (اختیاری): ").strip()

        manager = LeaveRequestManager()
        try:
            # محاسبه تعداد روزهای کاری
            days_count = manager.calculate_working_days(g_from, g_to)
            leave_type_name = manager.leave_manager.get_leave_type_name(leave_type)

            print("\n" + "-" * 70)
            print("  📋 پیش‌نمایش درخواست:")
            print(f"     • کاربر         : {user_id}")
            print(f"     • نوع مرخصی     : {leave_type_name}")
            print(f"     • از تاریخ      : {j_from.strftime('%Y/%m/%d')}")
            print(f"     • تا تاریخ      : {j_to.strftime('%Y/%m/%d')}")
            print(f"     • تعداد روز کاری: {days_count} روز")
            if reason:
                print(f"     • دلیل          : {reason}")
            print("-" * 70)

            confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            result = manager.create_request(
                user_id=user_id,
                leave_type=leave_type,
                from_date=g_from,
                to_date=g_to,
                reason=reason
            )
            print(f"\n  {result['message']}")

        finally:
            manager.close()

    def _show_pending_requests(self):
        """نمایش درخواست‌های در انتظار تایید"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 70)
        print("  ⏳ درخواست‌های در انتظار تایید")
        print("=" * 70)

        manager = LeaveRequestManager()
        try:
            requests = manager.get_pending_requests()

            if not requests:
                print("\n  ✅ هیچ درخواست در انتظاری وجود ندارد")
                return

            print(f"\n  📊 تعداد درخواست‌ها: {len(requests)}")

            print("\n  ┌──────┬────────┬────────────┬────────────┬──────┬────────────┬──────────────────────┐")
            print("  │ ID   │ کاربر  │ از         │ تا         │ روز  │ نوع        │ دلیل                 │")
            print("  ├──────┼────────┼────────────┼────────────┼──────┼────────────┼──────────────────────┤")

            for req in requests:
                user = manager.db.query(User).filter(User.user_id == req.user_id).first()
                user_name = user.name if user else req.user_id

                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)

                type_name = manager.leave_manager.get_leave_type_name(req.leave_type)
                reason = (req.reason or '')[:20]

                print(f"  │ {req.id:<4} │ {user_name[:6]:<6} │ {j_from.strftime('%Y/%m/%d')} │ "
                      f"{j_to.strftime('%Y/%m/%d')} │ {req.days_count:<4} │ {type_name:<10} │ {reason:<20} │")

            print("  └──────┴────────┴────────────┴────────────┴──────┴────────────┴──────────────────────┘")

        finally:
            manager.close()

    def _approve_reject_request(self):
        """تایید یا رد درخواست مرخصی"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 70)
        print("  ✅ تایید / ❌ رد درخواست مرخصی")
        print("=" * 70)

        request_id_str = input("\n  🔢 شناسه درخواست: ").strip()
        if not request_id_str:
            print("  ❌ شناسه نمی‌تواند خالی باشد")
            return

        try:
            request_id = int(request_id_str)
        except ValueError:
            print("  ❌ شناسه نامعتبر")
            return

        manager = LeaveRequestManager()
        try:
            # دریافت اطلاعات درخواست
            request = manager.db.query(LeaveRequest).filter(LeaveRequest.id == request_id).first()
            if not request:
                print("  ❌ درخواست یافت نشد")
                return

            user = manager.db.query(User).filter(User.user_id == request.user_id).first()
            user_name = user.name if user else request.user_id

            j_from = jdatetime.date.fromgregorian(date=request.from_date)
            j_to = jdatetime.date.fromgregorian(date=request.to_date)
            type_name = manager.leave_manager.get_leave_type_name(request.leave_type)
            status_name = manager.STATUS_NAMES.get(request.status, request.status)

            print("\n" + "-" * 70)
            print("  📋 اطلاعات درخواست:")
            print(f"     • شناسه      : {request.id}")
            print(f"     • کاربر      : {user_name} ({request.user_id})")
            print(f"     • نوع مرخصی  : {type_name}")
            print(f"     • از تاریخ   : {j_from.strftime('%Y/%m/%d')}")
            print(f"     • تا تاریخ   : {j_to.strftime('%Y/%m/%d')}")
            print(f"     • تعداد روز  : {request.days_count}")
            print(f"     • وضعیت فعلی : {status_name}")
            if request.reason:
                print(f"     • دلیل       : {request.reason}")
            print("-" * 70)

            print("\n  🎯 عملیات:")
            print("    1. ✅ تایید")
            print("    2. ❌ رد")
            print("    0. انصراف")
            action = input("  انتخاب [0-2]: ").strip()

            if action == '0':
                print("  ❌ عملیات لغو شد")
                return
            elif action == '1':
                confirm = input("\n  ⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ عملیات لغو شد")
                    return

                result = manager.approve_request(request_id)
                print(f"\n  {result['message']}")

            elif action == '2':
                reason = input("  📝 دلیل رد (اختیاری): ").strip()
                result = manager.reject_request(request_id, reason)
                print(f"\n  {result['message']}")

            else:
                print("  ❌ انتخاب نامعتبر")

        finally:
            manager.close()

    def _show_user_requests(self):
        """نمایش درخواست‌های یک کاربر"""
        from core.leave_request_manager import LeaveRequestManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  📜 درخواست‌های مرخصی کاربر")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = LeaveRequestManager()
        emp_manager = EmployeeManager()
        try:
            requests = manager.get_user_requests(user_id, year)

            # ✅ دریافت نام کامل
            full_name = emp_manager.get_full_name(user_id)

            if not requests:
                print(f"\n  ⚠️  هیچ درخواستی برای کاربر {full_name} در سال شمسی {year} یافت نشد")
                return

            print(f"\n  👤 کاربر: {full_name} (کد: {user_id})")
            print(f"  📅 سال شمسی: {year}")
            print(f"  📊 تعداد درخواست‌ها: {len(requests)}")

            print("\n  ┌──────┬────────────┬────────────┬──────┬────────────┬────────┐")
            print("  │ ID   │ از         │ تا         │ روز  │ نوع        │ وضعیت  │")
            print("  ├──────┼────────────┼────────────┼──────┼────────────┼────────┤")

            for req in requests:
                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)
                type_name = manager.leave_manager.get_leave_type_name(req.leave_type)
                status_name = manager.STATUS_NAMES.get(req.status, req.status)

                # آیکون وضعیت
                status_icon = "⏳" if req.status == 'P' else ("✅" if req.status == 'A' else "❌")

                print(f"  │ {req.id:<4} │ {j_from.strftime('%Y/%m/%d')} │ {j_to.strftime('%Y/%m/%d')} │ "
                      f"{req.days_count:<4} │ {type_name:<10} │ {status_icon} {status_name:<5} │")

            print("  └──────┴────────────┴────────────┴──────┴────────────┴────────┘")

            # ✅ نمایش مجموع روزهای مصرف شده
            total_days = sum(req.days_count for req in requests if req.status == 'A')
            if total_days > 0:
                print(f"\n  📊 مجموع روزهای مصرف شده (تایید شده): {total_days} روز")

        finally:
            manager.close()
            emp_manager.close()
    def _show_request_statistics(self):
        """نمایش آمار درخواست‌های مرخصی"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 70)
        print("  📊 آمار درخواست‌های مرخصی")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = LeaveRequestManager()
        try:
            stats = manager.get_request_statistics(year)

            print(f"\n  📅 سال: {year}")
            print("\n" + "-" * 70)
            print(f"  📈 آمار کلی:")
            print(f"     • کل درخواست‌ها    : {stats['total']}")
            print(f"     • در انتظار تایید  : {stats['pending']} ⏳")
            print(f"     • تایید شده        : {stats['approved']} ✅")
            print(f"     • رد شده           : {stats['rejected']} ❌")

            if stats['by_type']:
                print("\n  📋 آمار بر اساس نوع مرخصی (تایید شده‌ها):")
                print("  " + "-" * 66)
                print(f"  {'نوع مرخصی':<20} {'تعداد درخواست':<15} {'مجموع روز':<15}")
                print("  " + "-" * 66)

                for leave_type, data in stats['by_type'].items():
                    type_name = manager.leave_manager.get_leave_type_name(leave_type)
                    print(f"  {type_name:<20} {data['count']:<15} {data['days']:<15}")

                print("  " + "-" * 66)

        finally:
            manager.close()

    # ============================================
    # وضعیت روزانه
    # ============================================

    def _set_manual_status(self):
        """تعیین دستی وضعیت روزانه"""
        from core.daily_status_manager import DailyStatusManager

        print("\n" + "=" * 70)
        print("  📝 تعیین دستی وضعیت روزانه")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        date_str = input("  📅 تاریخ (شمسی): ").strip()
        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        print("\n  📋 نوع وضعیت:")
        print("    1. 💼 ماموریت (M)")
        print("    2. ⏰ حضور کم/تاخیر (LP)")
        print("    3. 🎓 ویژه - کلاس/اردو (S)")
        print("    4. ❌ غیبت (A)")
        print("    5. ✅ حاضر (P)")
        choice = input("  انتخاب [1-5]: ").strip()

        status_map = {
            '1': ('M', 'ماموریت'),
            '2': ('LP', 'حضور کم'),
            '3': ('S', 'ویژه'),
            '4': ('A', 'غیبت'),
            '5': ('P', 'حاضر')
        }

        if choice not in status_map:
            print("  ❌ انتخاب نامعتبر")
            return

        status_code, status_name = status_map[choice]
        description = input("  📝 توضیحات (اختیاری): ").strip()

        manager = DailyStatusManager()
        try:
            # نمایش وضعیت فعلی
            current = manager.detect_status(user_id, g_date)
            print(f"\n  📊 وضعیت فعلی: {manager.get_status_name(current['status'])}")
            print(f"     (منبع: {'خودکار' if current['source'] == 'auto' else 'دستی'})")

            confirm = input(f"\n  ⚠️  آیا می‌خواهید وضعیت را به '{status_name}' تغییر دهید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            result = manager.set_manual_status(user_id, g_date, status_code, description)
            print(f"\n  {result['message']}")

        finally:
            manager.close()

    def _show_daily_report(self):
        """گزارش وضعیت یک روز"""
        from core.daily_status_manager import DailyStatusManager

        print("\n" + "=" * 130)
        print("  📅 گزارش وضعیت روزانه")
        print("=" * 130)

        date_str = input("\n  📅 تاریخ (شمسی) [پیش‌فرض: امروز]: ").strip()
        try:
            if date_str:
                j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
                g_date = j_date.togregorian()
            else:
                g_date = date.today()
                j_date = jdatetime.date.fromgregorian(date=g_date)
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        print("\n  📋 فیلتر بر اساس گروه:")
        print("    0. همه گروه‌ها")
        print("    1. رسمی")
        print("    2. وظیفه")
        print("    3. خریدخدمت")
        print("    4. قراردادی")
        print("    5. پزشک")
        group_choice = input("  انتخاب [0-5]: ").strip()
        group_id = int(group_choice) if group_choice != '0' else None

        manager = DailyStatusManager()
        try:
            report = manager.get_daily_report(g_date, group_id)

            print(f"\n  📅 تاریخ: {j_date.strftime('%Y/%m/%d')} ({self._get_day_name(g_date)})")
            print(f"  👥 تعداد کاربران: {len(report)}")

            # شمارش وضعیت‌ها
            status_counts = {}
            for r in report:
                code = r['status']
                status_counts[code] = status_counts.get(code, 0) + 1

            print("\n  📊 خلاصه وضعیت:")
            for code, count in sorted(status_counts.items()):
                print(f"     • {manager.get_status_name(code):<15} : {count}")

            # آمار قرارداد
            with_contract = sum(1 for r in report if r['contract']['has_contract'])
            without_contract = len(report) - with_contract
            print(f"\n  📑 قرارداد:")
            print(f"     • دارای قرارداد فعال : {with_contract} ✅")
            print(f"     • بدون قرارداد       : {without_contract} ❌")

            # آمار تردد
            worked = sum(1 for r in report if r['work_hours'] > 0)
            total_work = sum(r['work_hours'] for r in report)
            total_night = sum(r['night_hours'] for r in report)
            print(f"\n  ⏱️  کارکرد:")
            print(f"     • کاربران حاضر     : {worked}")
            print(
                f"     • مجموع ساعات کاری : {int(total_work)} ساعت و {int((total_work - int(total_work)) * 60)} دقیقه")
            print(
                f"     • مجموع شب‌کاری     : {int(total_night)} ساعت و {int((total_night - int(total_night)) * 60)} دقیقه 🌙")

            # جدول اصلی
            print(
                "\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬────────────┬────────┬────────┬──────────────┐")
            print(
                "  │ ردیف │ کد     │ نام و نام خانوادگی   │ گروه       │ قرارداد    │ وضعیت      │ ورود   │ خروج   │ ساعت کاری    │")
            print(
                "  ├──────┼────────┼──────────────────────┼────────────┼────────────┼────────────┼────────┼────────┼──────────────┤")

            for i, r in enumerate(report, 1):
                full_name = r['full_name'][:20]

                group_map = {
                    '0': 'بدون گروه',
                    '1': 'رسمی',
                    '2': 'وظیفه',
                    '3': 'خریدخدمت',
                    '4': 'قراردادی',
                    '5': 'پزشک'
                }
                group_name = group_map.get(r['group_id'], r['group_id'] or '-')
                group_name = group_name[:10]

                contract_display = r['contract']['type'][:10] if r['contract']['has_contract'] else '❌ ندارد'

                # وضعیت کلی (ترکیب وضعیت روز + وضعیت تردد)
                status_display = r['status_name'][:10]
                if r['attendance_status'] != '—':
                    status_display = f"{status_display[:6]}|{r['attendance_status'][:3]}"

                # زمان ورود و خروج
                first_enter = r['first_enter'].strftime('%H:%M') if r['first_enter'] else '  --  '
                last_exit = r['last_exit'].strftime('%H:%M') if r['last_exit'] else '  --  '

                # ساعت کاری
                if r['work_hours'] > 0:
                    work_h = int(r['work_hours'])
                    work_m = int((r['work_hours'] - work_h) * 60)
                    work_str = f"{work_h:02d}:{work_m:02d}"
                    if r['night_hours'] > 0:
                        night_h = int(r['night_hours'])
                        night_m = int((r['night_hours'] - night_h) * 60)
                        work_str += f" 🌙{night_h:02d}:{night_m:02d}"
                else:
                    work_str = '  --    '

                print(
                    f"  │ {i:<4} │ {r['user_id']:<6} │ {full_name:<20} │ {group_name:<10} │ {contract_display:<10} │ {status_display:<10} │ {first_enter:<6} │ {last_exit:<6} │ {work_str:<12} │")

            print(
                "  └──────┴────────┴──────────────────────┴────────────┴────────────┴────────────┴────────┴────────┴──────────────┘")

        finally:
            manager.close()

    def _show_user_monthly_report(self):
        """گزارش ماهانه یک کاربر - روز به روز"""
        from core.daily_status_manager import DailyStatusManager
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 130)
        print("  📊 گزارش ماهانه یک کاربر (روز به روز)")
        print("=" * 130)

        user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        today_j = jdatetime.date.today()
        year_str = input(f"  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        manager = DailyStatusManager()
        emp_manager = EmployeeManager()
        try:
            report = manager.get_daily_details_for_month(user_id, year, month)
            full_name = emp_manager.get_full_name(user_id)

            print(f"\n  👤 کاربر: {full_name} (کد: {user_id})")
            print(f"  📅 ماه: {report['month_name']} {year}")
            print(
                f"  📆 بازه: {jdatetime.date.fromgregorian(date=report['from_date']).strftime('%Y/%m/%d')} تا {jdatetime.date.fromgregorian(date=report['to_date']).strftime('%Y/%m/%d')}")

            days = report['days']
            summary = report['summary']

            # ✅ جدول روز به روز
            print("\n  ┌────┬────────────┬──────────┬──────────────┬────────┬────────┬────────┬──────────────┐")
            print("  │ #  │ تاریخ      │ روز      │ وضعیت        │ ورود   │ خروج   │ کار    │ شب‌کاری       │")
            print("  ├────┼────────────┼──────────┼──────────────┼────────┼────────┼────────┼──────────────┤")

            for day in days:
                # فرمت ساعت کاری
                if day['work_hours'] > 0:
                    work_h = int(day['work_hours'])
                    work_m = int((day['work_hours'] - work_h) * 60)
                    work_str = f"{work_h:02d}:{work_m:02d}"
                else:
                    work_str = '  --  '

                # فرمت شب‌کاری
                if day['night_hours'] > 0:
                    night_h = int(day['night_hours'])
                    night_m = int((day['night_hours'] - night_h) * 60)
                    night_str = f"🌙{night_h:02d}:{night_m:02d}"
                else:
                    night_str = '  --    '

                # فرمت ورود/خروج
                first_enter = day['first_enter'].strftime('%H:%M') if day['first_enter'] else '  --  '
                last_exit = day['last_exit'].strftime('%H:%M') if day['last_exit'] else '  --  '

                # وضعیت (کوتاه شده)
                status_name = day['status_name']
                status_short = status_name.split(' ', 1)[1] if ' ' in status_name else status_name
                status_short = status_short[:12]

                # آیکون جمعه
                friday_icon = "🟡" if day['is_friday'] else "  "

                print(
                    f"  │ {day['day_of_month']:<2} │ {day['jalali_date']} │ {friday_icon}{day['day_name']:<6} │ {status_short:<12} │ {first_enter} │ {last_exit} │ {work_str} │ {night_str:<12} │")

            print("  └────┴────────────┴──────────┴──────────────┴────────┴────────┴────────┴──────────────┘")

            # ✅ خلاصه آماری
            print("\n  " + "-" * 126)
            print("  📊 خلاصه ماهانه:")
            print("  " + "-" * 126)
            print(f"     • کل روزهای ماه      : {summary['total_days']}")
            print(f"     • روزهای کاری        : {summary['working_days']}")
            print(f"     • روزهای حاضر        : {summary['present_days']} ✅")

            print("\n  📋 تفکیک وضعیت‌ها:")
            for code, count in sorted(summary['status_counts'].items()):
                status_name = manager.get_status_name(code)
                print(f"     • {status_name:<20} : {count} روز")

            work_h = int(summary['total_work_hours'])
            work_m = int((summary['total_work_hours'] - work_h) * 60)
            night_h = int(summary['total_night_hours'])
            night_m = int((summary['total_night_hours'] - night_h) * 60)

            print(f"\n  ⏱️  ساعات:")
            print(f"     • مجموع ساعات کاری   : {work_h} ساعت و {work_m} دقیقه")
            print(f"     • مجموع ساعات شب‌کاری : {night_h} ساعت و {night_m} دقیقه 🌙")

            if summary['working_days'] > 0:
                avg_work = summary['total_work_hours'] / summary['working_days']
                avg_h = int(avg_work)
                avg_m = int((avg_work - avg_h) * 60)
                print(f"     • میانگین روزانه     : {avg_h} ساعت و {avg_m} دقیقه")

            print("  " + "-" * 126)

        finally:
            manager.close()
            emp_manager.close()
    def _show_all_users_monthly_report(self):
        """گزارش ماهانه همه کاربران"""
        from core.report_generator import ReportGenerator

        print("\n" + "=" * 120)
        print("  📊 گزارش ماهانه همه کاربران")
        print("=" * 120)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = ReportGenerator()
        try:
            reports = generator.generate_monthly_report_for_all(year, month)

            print(f"\n  📅 ماه: {self._get_jalali_month_name(month)} {year}")
            print(f"  👥 تعداد کاربران: {len(reports)}")

            print("\n  ┌──────┬────────┬────────────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────────┐")
            print("  │ ردیف │ کد     │ نام        │حاضر│غایب│تعطیل│استحق│استعل│تشویق│بدون ح│مامور│حضورک│ ساعت   │")
            print("  ├──────┼────────┼────────────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────────┤")

            for i, r in enumerate(reports, 1):
                work_str = f"{int(r['work_hours'])}:{int((r['work_hours'] % 1) * 60):02d}"
                print(f"  │ {i:<4} │ {r['user_id']:<6} │ {r['name'][:10]:<10} │ "
                      f"{r['present_days']:<2} │ {r['absent_days']:<2} │ {r['holiday_days']:<3} │ "
                      f"{r['annual_leave']:<2} │ {r['sick_leave']:<3} │ {r['reward_leave']:<3} │ "
                      f"{r['unpaid_leave']:<3} │ {r['mission_days']:<2} │ {r['late_days']:<2} │ {work_str:<6} │")

            print("  └──────┴────────┴────────────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────────┘")

        finally:
            generator.close()

    def _show_absent_report(self):
        """گزارش غیبت‌ها"""
        from core.report_generator import ReportGenerator

        print("\n" + "=" * 70)
        print("  ❌ گزارش غیبت‌ها")
        print("=" * 70)

        today_j = jdatetime.date.today()
        from_str = input(f"\n  📅 از تاریخ (شمسی) [پیش‌فرض: {today_j.strftime('%Y/%m/01')}]: ").strip()
        to_str = input(f"  📅 تا تاریخ (شمسی) [پیش‌فرض: {today_j.strftime('%Y/%m/%d')}]: ").strip()

        try:
            if from_str:
                j_from = jdatetime.datetime.strptime(from_str, "%Y/%m/%d").date()
                g_from = j_from.togregorian()
            else:
                g_from = date(today_j.year, today_j.month, 1)

            if to_str:
                j_to = jdatetime.datetime.strptime(to_str, "%Y/%m/%d").date()
                g_to = j_to.togregorian()
            else:
                g_to = today_j.togregorian()
        except Exception as e:
            print(f"  ❌ خطا در تبدیل تاریخ: {e}")
            return

        generator = ReportGenerator()
        try:
            reports = generator.generate_absent_report(g_from, g_to)

            if not reports:
                print("\n  ✅ هیچ غیبتی در این بازه ثبت نشده است")
                return

            print(f"\n  📊 تعداد افراد غایب: {len(reports)}")

            print("\n  ┌──────┬────────┬────────────┬──────────┬──────────────────────────────────────┐")
            print("  │ ردیف │ کد     │ نام        │ تعداد    │ تاریخ‌های غیبت                        │")
            print("  ├──────┼────────┼────────────┼──────────┼──────────────────────────────────────┤")

            for i, r in enumerate(reports, 1):
                dates_str = ', '.join([
                    jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')
                    for d in r['absent_dates'][:5]
                ])
                if len(r['absent_dates']) > 5:
                    dates_str += f" ... (+{len(r['absent_dates']) - 5})"

                print(f"  │ {i:<4} │ {r['user_id']:<6} │ {r['name'][:10]:<10} │ {r['absent_count']:<8} │ {dates_str:<36} │")

            print("  └──────┴────────┴────────────┴──────────┴──────────────────────────────────────┘")

        finally:
            generator.close()

    def _show_leave_report(self):
        """گزارش مرخصی‌ها"""
        from core.report_generator import ReportGenerator

        print("\n" + "=" * 90)
        print("  🏖️  گزارش مرخصی‌ها")
        print("=" * 90)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [خالی = کل سال]: ").strip()
        month = int(month_str) if month_str else None

        generator = ReportGenerator()
        try:
            reports = generator.generate_leave_report(year, month)

            if not reports:
                print("\n  ⚠️  هیچ مرخصی تایید شده‌ای یافت نشد")
                return

            print(f"\n  📊 تعداد کاربران دارای مرخصی: {len(reports)}")

            print("\n  ┌──────┬────────┬────────────┬────────┬────────┬────────┬────────┬──────┬──────┐")
            print("  │ ردیف │ کد     │ نام        │ استحقاق│ استعلال│ تشویقی │ بدون ح │ مجموع│ تعداد│")
            print("  ├──────┼────────┼────────────┼────────┼────────┼────────┼────────┼──────┼──────┤")

            for i, r in enumerate(reports, 1):
                print(f"  │ {i:<4} │ {r['user_id']:<6} │ {r['name'][:10]:<10} │ "
                      f"{r['annual_leave']:<6} │ {r['sick_leave']:<6} │ {r['reward_leave']:<6} │ "
                      f"{r['unpaid_leave']:<6} │ {r['total_days']:<4} │ {r['total_requests']:<4} │")

            print("  └──────┴────────┴────────────┴────────┴────────┴────────┴────────┴──────┴──────┘")

        finally:
            generator.close()

    # ============================================
    # خروجی اکسل
    # ============================================

    def _export_monthly_to_excel(self):
        """خروجی گزارش ماهانه به اکسل"""
        from core.report_generator import ReportGenerator
        from core.excel_exporter import ExcelExporter

        print("\n" + "=" * 70)
        print("  📤 خروجی گزارش ماهانه به اکسل")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = ReportGenerator()
        try:
            print("\n  ⏳ در حال تولید گزارش...")
            reports = generator.generate_monthly_report_for_all(year, month)

            exporter = ExcelExporter()
            filename = exporter.export_monthly_report(reports, year, month)

            print(f"\n  ✅ فایل اکسل با موفقیت ایجاد شد:")
            print(f"     📁 {filename}")
            print(f"     📊 تعداد ردیف‌ها: {len(reports)}")

        finally:
            generator.close()

    def _export_absent_to_excel(self):
        """خروجی گزارش غیبت‌ها به اکسل"""
        from core.report_generator import ReportGenerator
        from core.excel_exporter import ExcelExporter

        print("\n" + "=" * 70)
        print("  📤 خروجی گزارش غیبت‌ها به اکسل")
        print("=" * 70)

        today_j = jdatetime.date.today()
        from_str = input(f"\n  📅 از تاریخ (شمسی) [پیش‌فرض: اول ماه]: ").strip()
        to_str = input(f"  📅 تا تاریخ (شمسی) [پیش‌فرض: امروز]: ").strip()

        try:
            if from_str:
                j_from = jdatetime.datetime.strptime(from_str, "%Y/%m/%d").date()
                g_from = j_from.togregorian()
            else:
                g_from = date(today_j.year, today_j.month, 1)

            if to_str:
                j_to = jdatetime.datetime.strptime(to_str, "%Y/%m/%d").date()
                g_to = j_to.togregorian()
            else:
                g_to = today_j.togregorian()
        except Exception as e:
            print(f"  ❌ خطا: {e}")
            return

        generator = ReportGenerator()
        try:
            print("\n  ⏳ در حال تولید گزارش...")
            reports = generator.generate_absent_report(g_from, g_to)

            exporter = ExcelExporter()
            filename = exporter.export_absent_report(reports, g_from, g_to)

            print(f"\n  ✅ فایل اکسل ایجاد شد:")
            print(f"     📁 {filename}")

        finally:
            generator.close()

    def _export_leave_to_excel(self):
        """خروجی گزارش مرخصی‌ها به اکسل"""
        from core.report_generator import ReportGenerator
        from core.excel_exporter import ExcelExporter

        print("\n" + "=" * 70)
        print("  📤 خروجی گزارش مرخصی‌ها به اکسل")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [خالی = کل سال]: ").strip()
        month = int(month_str) if month_str else None

        generator = ReportGenerator()
        try:
            print("\n  ⏳ در حال تولید گزارش...")
            reports = generator.generate_leave_report(year, month)

            exporter = ExcelExporter()
            filename = exporter.export_leave_report(reports, year, month)

            print(f"\n  ✅ فایل اکسل ایجاد شد:")
            print(f"     📁 {filename}")

        finally:
            generator.close()

    def _get_jalali_month_name(self, month: int) -> str:
        """دریافت نام ماه شمسی"""
        names = {
            1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد',
            4: 'تیر', 5: 'مرداد', 6: 'شهریور',
            7: 'مهر', 8: 'آبان', 9: 'آذر',
            10: 'دی', 11: 'بهمن', 12: 'اسفند'
        }
        return names.get(month, '')

    # ============================================
    # مدیریت اطلاعات کارمندان
    # ============================================

    def _add_employee_info(self):
        """افزودن اطلاعات تکمیلی کارمند"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  👤 افزودن اطلاعات تکمیلی کارمند")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        first_name = input("  👤 نام: ").strip()
        last_name = input("  👤 نام خانوادگی: ").strip()

        if not first_name or not last_name:
            print("  ❌ نام و نام خانوادگی الزامی است")
            return

        national_code = input("  🆔 کد ملی (اختیاری): ").strip() or None
        father_name = input("  👨 نام پدر (اختیاری): ").strip() or None

        # تاریخ تولد
        birth_str = input("  🎂 تاریخ تولد (شمسی - مثال: 1370/05/15) [اختیاری]: ").strip()
        birth_date = None
        if birth_str:
            try:
                j_birth = jdatetime.datetime.strptime(birth_str, "%Y/%m/%d").date()
                birth_date = j_birth.togregorian()
            except:
                print("  ⚠️  تاریخ تولد نامعتبر - نادیده گرفته شد")

        # جنسیت
        print("\n  ⚧ جنسیت:")
        print("    1. مرد")
        print("    2. زن")
        gender_choice = input("  انتخاب [1/2] [اختیاری]: ").strip()
        gender = 'M' if gender_choice == '1' else ('F' if gender_choice == '2' else None)

        # وضعیت تاهل
        print("\n  💍 وضعیت تاهل:")
        print("    1. مجرد")
        print("    2. متاهل")
        marital_choice = input("  انتخاب [1/2] [اختیاری]: ").strip()
        marital_status = 'S' if marital_choice == '1' else ('M' if marital_choice == '2' else None)

        email = input("  📧 ایمیل (اختیاری): ").strip() or None

        # تاریخ استخدام
        hire_str = input("  📅 تاریخ استخدام (شمسی) [اختیاری]: ").strip()
        hire_date = None
        if hire_str:
            try:
                j_hire = jdatetime.datetime.strptime(hire_str, "%Y/%m/%d").date()
                hire_date = j_hire.togregorian()
            except:
                print("  ⚠️  تاریخ استخدام نامعتبر - نادیده گرفته شد")

        department = input("  🏢 دپارتمان (اختیاری): ").strip() or None
        position = input("  💼 سمت (اختیاری): ").strip() or None
        notes = input("  📝 یادداشت (اختیاری): ").strip() or None

        # پیش‌نمایش
        print("\n" + "-" * 70)
        print("  📋 پیش‌نمایش:")
        print(f"     • کد پرسنلی    : {user_id}")
        print(f"     • نام کامل     : {first_name} {last_name}")
        if national_code:
            print(f"     • کد ملی       : {national_code}")
        if father_name:
            print(f"     • نام پدر      : {father_name}")
        if birth_date:
            j_birth = jdatetime.date.fromgregorian(date=birth_date)
            print(f"     • تاریخ تولد   : {j_birth.strftime('%Y/%m/%d')}")
        if gender:
            print(f"     • جنسیت        : {'مرد' if gender == 'M' else 'زن'}")
        if marital_status:
            print(f"     • وضعیت تاهل   : {'مجرد' if marital_status == 'S' else 'متاهل'}")
        if email:
            print(f"     • ایمیل        : {email}")
        if hire_date:
            j_hire = jdatetime.date.fromgregorian(date=hire_date)
            print(f"     • تاریخ استخدام: {j_hire.strftime('%Y/%m/%d')}")
        if department:
            print(f"     • دپارتمان     : {department}")
        if position:
            print(f"     • سمت          : {position}")
        print("-" * 70)

        confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("  ❌ عملیات لغو شد")
            return

        manager = EmployeeManager()
        try:
            result = manager.add_employee(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                national_code=national_code,
                father_name=father_name,
                birth_date=birth_date,
                gender=gender,
                marital_status=marital_status,
                email=email,
                hire_date=hire_date,
                department=department,
                position=position,
                notes=notes
            )
            print(f"\n  {result['message']}")
        finally:
            manager.close()

    def _show_employee_info(self):
        """نمایش اطلاعات کارمند"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  👤 اطلاعات تکمیلی کارمند")
        print("=" * 70)

        user_id = input("\n  📛 کد پرسنلی: ").strip()
        if not user_id:
            print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
            return

        manager = EmployeeManager()
        try:
            employee = manager.get_employee(user_id)

            if not employee:
                print(f"\n  ⚠️  اطلاعاتی برای کاربر {user_id} ثبت نشده است")
                return

            user = manager.db.query(User).filter(User.user_id == user_id).first()

            print(f"\n  👤 اطلاعات کاربر:")
            print(f"     • کد پرسنلی    : {user_id}")
            print(f"     • نام سیستمی   : {user.name if user else '-'}")
            print(f"     • گروه         : {user.group_id if user else '-'}")

            print(f"\n  📋 اطلاعات تکمیلی:")
            print(f"     • نام کامل     : {employee.full_name}")
            if employee.national_code:
                print(f"     • کد ملی       : {employee.national_code}")
            if employee.father_name:
                print(f"     • نام پدر      : {employee.father_name}")
            if employee.birth_date:
                j_birth = jdatetime.date.fromgregorian(date=employee.birth_date)
                print(f"     • تاریخ تولد   : {j_birth.strftime('%Y/%m/%d')}")
            if employee.gender:
                print(f"     • جنسیت        : {employee.gender_name}")
            if employee.marital_status:
                print(f"     • وضعیت تاهل   : {employee.marital_status_name}")
            if employee.email:
                print(f"     • ایمیل        : {employee.email}")
            if employee.hire_date:
                j_hire = jdatetime.date.fromgregorian(date=employee.hire_date)
                print(f"     • تاریخ استخدام: {j_hire.strftime('%Y/%m/%d')}")
            if employee.department:
                print(f"     • دپارتمان     : {employee.department}")
            if employee.position:
                print(f"     • سمت          : {employee.position}")
            if employee.notes:
                print(f"     • یادداشت      : {employee.notes}")

        finally:
            manager.close()

    def _list_all_employees(self):
        """لیست تمام کارمندان"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 100)
        print("  👥 لیست کارمندان")
        print("=" * 100)

        manager = EmployeeManager()
        try:
            employees = manager.get_all_employees()

            if not employees:
                print("\n  ⚠️  هیچ کارمندی ثبت نشده است")
                return

            print(f"\n  📊 تعداد کارمندان: {len(employees)}")

            print("\n  ┌──────┬────────┬──────────────────┬────────────┬────────────┬────────────┐")
            print("  │ ردیف │ کد     │ نام کامل         │ دپارتمان   │ سمت        │ جنسیت      │")
            print("  ├──────┼────────┼──────────────────┼────────────┼────────────┼────────────┤")

            for i, emp in enumerate(employees, 1):
                print(f"  │ {i:<4} │ {emp.user_id:<6} │ {emp.full_name[:16]:<16} │ "
                      f"{emp.department or '-':<10} │ {emp.position or '-':<10} │ "
                      f"{emp.gender_name:<10} │")

            print("  └──────┴────────┴──────────────────┴────────────┴────────────┴────────────┘")

        finally:
            manager.close()

    def _search_employees(self):
        """جستجو در اطلاعات کارمندان"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  🔍 جستجو در اطلاعات کارمندان")
        print("=" * 70)

        query = input("\n  🔎 عبارت جستجو: ").strip()
        if not query:
            print("  ❌ عبارت جستجو نمی‌تواند خالی باشد")
            return

        print("\n  📋 جستجو در:")
        print("    1. همه فیلدها")
        print("    2. نام")
        print("    3. کد ملی")
        print("    4. دپارتمان")
        print("    5. سمت")
        choice = input("  انتخاب [1-5] [پیش‌فرض: 1]: ").strip() or '1'

        field_map = {'1': 'all', '2': 'name', '3': 'national_code', '4': 'department', '5': 'position'}
        field = field_map.get(choice, 'all')

        manager = EmployeeManager()
        try:
            results = manager.search_employees(query, field)

            if not results:
                print(f"\n  ⚠️  نتیجه‌ای یافت نشد")
                return

            print(f"\n  📊 تعداد نتایج: {len(results)}")

            print("\n  ┌──────┬────────┬──────────────────┬────────────┬────────────┐")
            print("  │ ردیف │ کد     │ نام کامل         │ دپارتمان   │ سمت        │")
            print("  ├──────┼────────┼──────────────────┼────────────┼────────────┤")

            for i, emp in enumerate(results, 1):
                print(f"  │ {i:<4} │ {emp.user_id:<6} │ {emp.full_name[:16]:<16} │ "
                      f"{emp.department or '-':<10} │ {emp.position or '-':<10} │")

            print("  └──────┴────────┴──────────────────┴────────────┴────────────┘")

        finally:
            manager.close()

    def _show_employee_statistics(self):
        """نمایش آمار کارمندان"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  📊 آمار کارمندان")
        print("=" * 70)

        manager = EmployeeManager()
        try:
            stats = manager.get_statistics()

            print(f"\n  👥 آمار کلی:")
            print(f"     • کل کارمندان           : {stats['total']}")
            print(f"     • دارای کد ملی          : {stats['with_national_code']}")
            print(f"     • دارای ایمیل           : {stats['with_email']}")
            print(f"     • تعداد دپارتمان‌ها      : {stats['departments']}")

            print(f"\n  ⚧ آمار جنسیت:")
            print(f"     • مرد                   : {stats['males']}")
            print(f"     • زن                    : {stats['females']}")

            print(f"\n  💍 آمار تاهل:")
            print(f"     • مجرد                  : {stats['single']}")
            print(f"     • متاهل                 : {stats['married']}")

        finally:
            manager.close()

    def _show_all_contracts(self):
        """نمایش تمام قراردادها"""
        from core.contract_manager import ContractManager

        print("\n" + "=" * 100)
        print("  📑 تمام قراردادها")
        print("=" * 100)

        manager = ContractManager()
        try:
            contracts = manager.get_all_contracts()

            if not contracts:
                print("\n  ⚠️  هیچ قراردادی ثبت نشده است")
                return

            print(f"\n  📊 تعداد قراردادها: {len(contracts)}")

            # شمارش قراردادها
            active_count = sum(1 for c in contracts if c['is_active'])
            print(f"     • فعال   : {active_count} ✅")
            print(f"     • غیرفعال: {len(contracts) - active_count} ⏸️")

            print("\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬────────┬────────┐")
            print("  │ ID   │ کد     │ نام و نام خانوادگی   │ نوع        │ شروع       │ پایان  │ وضعیت  │")
            print("  ├──────┼────────┼──────────────────────┼────────────┼────────────┼────────┼────────┤")

            for c in contracts:
                contract = c['contract']
                j_start = jdatetime.date.fromgregorian(date=contract.start_date)
                j_end = jdatetime.date.fromgregorian(date=contract.end_date) if contract.end_date else "نامحدود"
                end_str = j_end if isinstance(j_end, str) else j_end.strftime("%Y/%m/%d")

                status = "✅ فعال" if c['is_active'] else "⏸️ غیرفعال"

                print(f"  │ {contract.id:<4} │ {c['user_id']:<6} │ {c['full_name'][:20]:<20} │ "
                      f"{contract.contract_type:<10} │ {j_start.strftime('%Y/%m/%d')} │ {end_str:<6} │ {status:<6} │")

            print("  └──────┴────────┴──────────────────────┴────────────┴────────────┴────────┴────────┘")

        finally:
            manager.close()

    def _update_contract(self):
        """ویرایش قرارداد"""
        from core.contract_manager import ContractManager

        print("\n" + "=" * 70)
        print("  ✏️  ویرایش قرارداد")
        print("=" * 70)

        contract_id_str = input("\n  🔢 شناسه قرارداد: ").strip()
        if not contract_id_str:
            print("  ❌ شناسه نمی‌تواند خالی باشد")
            return

        try:
            contract_id = int(contract_id_str)
        except ValueError:
            print("  ❌ شناسه نامعتبر")
            return

        manager = ContractManager()
        try:
            contract = manager.db.query(Contract).filter(Contract.id == contract_id).first()
            if not contract:
                print("  ❌ قرارداد یافت نشد")
                return

            # نمایش اطلاعات فعلی
            j_start = jdatetime.date.fromgregorian(date=contract.start_date)
            j_end = jdatetime.date.fromgregorian(date=contract.end_date) if contract.end_date else None

            print("\n" + "-" * 70)
            print("  📋 اطلاعات فعلی:")
            print(f"     • شناسه           : {contract.id}")
            print(f"     • کد پرسنلی       : {contract.user_id}")
            print(f"     • نوع قرارداد     : {contract.contract_type}")
            print(f"     • تاریخ شروع      : {j_start.strftime('%Y/%m/%d')}")
            print(f"     • تاریخ پایان     : {j_end.strftime('%Y/%m/%d') if j_end else 'نامحدود'}")
            print(f"     • استحقاقی سالانه : {contract.annual_leave_days} روز")
            print(f"     • استعلاجی        : {contract.sick_leave_days} روز")
            print(f"     • تشویقی          : {contract.reward_leave_days} روز")
            print(f"     • بدون حقوق       : {contract.unpaid_leave_days} روز")
            print("-" * 70)

            print("\n  💡 برای تغییر ندهید، فقط Enter بزنید")

            # دریافت مقادیر جدید
            contract_type = input(f"  نوع قرارداد [{contract.contract_type}]: ").strip()
            if not contract_type:
                contract_type = contract.contract_type

            end_str = input("  تاریخ پایان (شمسی) [خالی = نامحدود]: ").strip()
            if end_str:
                try:
                    j_end_new = jdatetime.datetime.strptime(end_str, "%Y/%m/%d").date()
                    end_date = j_end_new.togregorian()
                except:
                    print("  ⚠️  تاریخ نامعتبر - بدون تغییر")
                    end_date = contract.end_date
            else:
                end_date = contract.end_date

            annual = input(f"  استحقاقی [{contract.annual_leave_days}]: ").strip()
            annual = int(annual) if annual else contract.annual_leave_days

            sick = input(f"  استعلاجی [{contract.sick_leave_days}]: ").strip()
            sick = int(sick) if sick else contract.sick_leave_days

            reward = input(f"  تشویقی [{contract.reward_leave_days}]: ").strip()
            reward = int(reward) if reward else contract.reward_leave_days

            unpaid = input(f"  بدون حقوق [{contract.unpaid_leave_days}]: ").strip()
            unpaid = int(unpaid) if unpaid else contract.unpaid_leave_days

            description = input(f"  توضیحات [{contract.description or ''}]: ").strip()
            if not description:
                description = contract.description

            # پیش‌نمایش
            print("\n" + "-" * 70)
            print("  📋 پیش‌نمایش تغییرات:")
            print(f"     • نوع قرارداد     : {contract_type}")
            print(
                f"     • تاریخ پایان     : {jdatetime.date.fromgregorian(date=end_date).strftime('%Y/%m/%d') if end_date else 'نامحدود'}")
            print(f"     • استحقاقی سالانه : {annual} روز")
            print(f"     • استعلاجی        : {sick} روز")
            print(f"     • تشویقی          : {reward} روز")
            print(f"     • بدون حقوق       : {unpaid} روز")
            print("-" * 70)

            confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            result = manager.update_contract(
                contract_id,
                contract_type=contract_type,
                end_date=end_date,
                annual_leave_days=annual,
                sick_leave_days=sick,
                reward_leave_days=reward,
                unpaid_leave_days=unpaid,
                description=description
            )
            print(f"\n  {result['message']}")

        finally:
            manager.close()

    def _show_expiring_contracts(self):
        """نمایش قراردادهای نزدیک به پایان"""
        from core.contract_manager import ContractManager

        print("\n" + "=" * 90)
        print("  ⚠️  قراردادهای نزدیک به پایان")
        print("=" * 90)

        days_str = input("\n  🔢 تعداد روز برای هشدار [پیش‌فرض: 30]: ").strip()
        days_threshold = int(days_str) if days_str else 30

        manager = ContractManager()
        try:
            contracts = manager.get_expiring_contracts(days_threshold)

            if not contracts:
                print(f"\n  ✅ هیچ قراردادی در {days_threshold} روز آینده منقضی نمی‌شود")
                return

            print(f"\n  📊 تعداد قراردادهای نزدیک به پایان: {len(contracts)}")

            print("\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬──────────┐")
            print("  │ ID   │ کد     │ نام و نام خانوادگی   │ نوع        │ پایان      │ روز باقی │")
            print("  ├──────┼────────┼──────────────────────┼────────────┼────────────┼──────────┤")

            for c in contracts:
                contract = c['contract']
                j_end = jdatetime.date.fromgregorian(date=c['end_date'])

                # رنگ بر اساس روزهای باقی‌مانده
                if c['days_remaining'] <= 7:
                    icon = "🔴"
                elif c['days_remaining'] <= 15:
                    icon = "🟡"
                else:
                    icon = "🟢"

                print(f"  │ {contract.id:<4} │ {c['user_id']:<6} │ {c['full_name'][:20]:<20} │ "
                      f"{contract.contract_type:<10} │ {j_end.strftime('%Y/%m/%d')} │ {icon} {c['days_remaining']:<7} │")

            print("  └──────┴────────┴──────────────────────┴────────────┴────────────┴──────────┘")

            print(f"\n  💡 راهنما: 🔴 کمتر از 7 روز | 🟡 کمتر از 15 روز | 🟢 بیشتر از 15 روز")

        finally:
            manager.close()

    def _show_analytical_monthly_report(self):
        """نمایش گزارش تحلیلی ماهانه"""
        from core.analytical_report import AnalyticalReportGenerator

        print("\n" + "=" * 150)
        print("  📊 گزارش تحلیلی ماهانه")
        print("=" * 150)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = AnalyticalReportGenerator()
        try:
            report = generator.generate_monthly_report(year, month)
            month_info = report['month_info']

            print(f"\n  📅 ماه: {report['month_name']} {year}")
            print(
                f"  📆 بازه: {jdatetime.date.fromgregorian(date=month_info['start_date']).strftime('%Y/%m/%d')} تا {jdatetime.date.fromgregorian(date=month_info['end_date']).strftime('%Y/%m/%d')}")
            print(
                f"  📊 کل روزها: {month_info['total_days']} | جمعه‌ها: {month_info['fridays']} | تعطیلات: {month_info['holidays']} | روزهای کاری: {month_info['working_days']}")

            # نمایش به تفکیک گروه
            for group_name, users in report['groups'].items():
                print(f"\n{'=' * 150}")
                print(f"  👥 گروه: {group_name} ({len(users)} کاربر)")
                print(f"{'=' * 150}")

                # جدول
                print(
                    "\n  ┌────┬────────┬──────────────────────┬──────┬──────┬──────┬──────┬──────────┬────────┬────────┬────────┬──────────┬──────────┐")
                print(
                    "  │ #  │ کد     │ نام کامل             │ حاضر │ غایب │ مرخصی│ روز  │ ساعت     │ صبح    │ عصر    │ شب     │ کل       │ کسری/+   │")
                print(
                    "  ├────┼────────┼──────────────────────┼──────┼──────┼──────┼──────┼──────────┼────────┼────────┼────────┼──────────┼──────────┤")

                for i, u in enumerate(users, 1):
                    # فرمت ساعات
                    def fmt_hours(h):
                        """فرمت‌بندی ساعات (پشتیبانی از اعداد منفی)"""
                        if h == 0:
                            return "  --    "
                        # ✅ استفاده از abs برای محاسبه دقیقه
                        sign = "-" if h < 0 else ""
                        abs_h = abs(h)
                        hours = int(abs_h)
                        minutes = int(round((abs_h - hours) * 60))
                        # ✅ اصلاح سرریز دقیقه
                        if minutes >= 60:
                            hours += 1
                            minutes = 0
                        return f"{sign}{hours:02d}:{minutes:02d}"

                    # فرمت کسری/اضافی
                    diff = u['difference']
                    if diff > 0.5:
                        diff_str = f"+{fmt_hours(diff)} ✅"
                    elif diff < -0.5:
                        diff_str = f"{fmt_hours(diff)} ❌"
                    else:
                        diff_str = f" 00:00 ✅"
                    # فرمت کسری/اضافی
                    diff = u['difference']
                    if diff > 0:
                        diff_str = f"+{fmt_hours(diff)} ✅"
                    elif diff < 0:
                        diff_str = f"{fmt_hours(diff)} ❌"
                    else:
                        diff_str = f"{fmt_hours(diff)} ✅"

                    print(f"  │ {i:<2} │ {u['user_id']:<6} │ {u['full_name'][:20]:<20} │ "
                          f"{u['present_days']:<4} │ {u['absent_days']:<4} │ {u['leave_days']:<4} │ "
                          f"{u['required_days']:<4} │ {fmt_hours(u['required_hours'])} │ "
                          f"{fmt_hours(u['morning_hours'])} │ {fmt_hours(u['evening_hours'])} │ "
                          f"{fmt_hours(u['night_hours'])} │ {fmt_hours(u['total_hours'])} │ {diff_str:<8} │")

                print(
                    "  └────┴────────┴──────────────────────┴──────┴──────┴──────┴──────┴──────────┴────────┴────────┴────────┴──────────┴──────────┘")

                # خلاصه گروه
                avg_work = sum(u['total_hours'] for u in users) / len(users) if users else 0
                avg_diff = sum(u['difference'] for u in users) / len(users) if users else 0

                max_positive = max(users, key=lambda x: x['difference'])
                max_negative = min(users, key=lambda x: x['difference'])

                print(f"\n  📊 خلاصه گروه {group_name}:")
                print(f"     • میانگین ساعات کاری: {int(avg_work)}:{int((avg_work - int(avg_work)) * 60):02d}")
                print(f"     • میانگین کسری/اضافی: {int(avg_diff)}:{int((avg_diff - int(avg_diff)) * 60):02d}")
                print(
                    f"     • بیشترین اضافی: {max_positive['full_name']} (+{int(max_positive['difference'])}:{int((max_positive['difference'] - int(max_positive['difference'])) * 60):02d})")
                print(
                    f"     • بیشترین کسری: {max_negative['full_name']} ({int(max_negative['difference'])}:{int((max_negative['difference'] - int(max_negative['difference'])) * 60):02d})")

        finally:
            generator.close()

    def _export_analytical_to_excel(self):
        """خروجی گزارش تحلیلی به اکسل"""
        from core.analytical_report import AnalyticalReportGenerator
        from core.excel_analytical_export import AnalyticalExcelExporter

        print("\n" + "=" * 70)
        print("  📤 خروجی گزارش تحلیلی به اکسل")
        print("=" * 70)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = AnalyticalReportGenerator()
        try:
            print("\n  ⏳ در حال تولید گزارش...")
            report = generator.generate_monthly_report(year, month)

            exporter = AnalyticalExcelExporter()
            filename = exporter.export_analytical_report(report)

            print(f"\n  ✅ فایل اکسل با موفقیت ایجاد شد:")
            print(f"     📁 {filename}")
            print(f"     📊 تعداد گروه‌ها: {len(report['groups'])}")
            print(f"     📊 تعداد کاربران: {sum(len(u) for u in report['groups'].values())}")

        finally:
            generator.close()