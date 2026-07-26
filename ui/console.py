from typing import Dict, List
from datetime import datetime, timedelta,date
import jdatetime
from core.device_manager import DeviceManager
from core.attendance_analyzer import AttendanceAnalyzer
from core.employee_manager import EmployeeManager
from models import Employee
from models.user import User
from models.contract import Contract
from models.leave_request import LeaveRequest
from sqlalchemy import and_, or_


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
            print("  14. تایید همه درخواست‌های در انتظار (یکجا) 🆕")  # 🆕
            print("  15. حذف درخواست (مدیر) 🆕")  # 🆕
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
            elif choice == '11': self._approve_leave_requests()
            elif choice == '12': self._show_user_requests()
            elif choice == '13': self._show_request_statistics()
            elif choice == '14': self._approve_all_pending_leaves()  # 🆕
            elif choice == '15': self._admin_delete_leave_request()  # 🆕
            elif choice == '0': break
            else: print("\n❌ انتخاب نامعتبر")
            input("\n⏎ Enter...")

    def _reports_menu(self):
        """زیرمنوی گزارش‌ها"""
        while True:
            self.clear()
            self.header("گزارش‌ها و وضعیت روزانه")
            print("\n  وضعیت روزانه:")
            print("  1. تعیین دستی وضعیت")
            print("  2. گزارش وضعیت یک روز")
            print("  3. گزارش ماهانه یک کاربر")
            print("  4. گزارش ماهانه همه کاربران")
            print("\n  گزارش‌های تحلیلی:")
            print("  5. گزارش غیبت‌ها")
            print("  6. گزارش مرخصی‌ها")
            print("  7. گزارش تحلیلی ماهانه")
            print("  8. گزارش تفصیلی یک کارمند (V1)")
            print("  9. گزارش تفصیلی همه کارمندان (V1)")
            print("  10. گزارش تفصیلی یک کارمند (V2 - جدید) 🆕")
            print("  11. گزارش تفصیلی همه کارمندان (V2 - جدید) 🆕")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._set_manual_status()
            elif choice == '2': self._show_daily_report()
            elif choice == '3': self._show_user_monthly_report()
            elif choice == '4': self._show_all_users_monthly_report()
            elif choice == '5': self._show_absent_report()
            elif choice == '6': self._show_leave_report()
            elif choice == '7': self._show_analytical_monthly_report()
            elif choice == '8': self._show_detailed_monthly_report()
            elif choice == '9': self._show_all_employees_detailed_report()
            elif choice == '10': self._show_detailed_monthly_report_v2()  # 🆕
            elif choice == '11': self._show_all_employees_detailed_report_v2()  # 🆕
            elif choice == '0': break
            else: print("\n انتخاب نامعتبر")
            input("\n Enter...")

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
            print("  4. لیست کارمندان فعال")
            print("  5. لیست کارمندان غیرفعال")
            print("  6. تغییر وضعیت کارمند (فعال/غیرفعال)")
            print("  7. جستجو در اطلاعات")
            print("  8. آمار کارمندان")
            print("  0. بازگشت")

            choice = input("\n  انتخاب: ").strip()
            if choice == '1': self._add_employee_info()
            elif choice == '2': self._update_employee_info()
            elif choice == '3': self._show_employee_info()
            elif choice == '4': self._list_active_employees()
            elif choice == '5': self._list_inactive_employees()
            elif choice == '6': self._set_employee_status()
            elif choice == '7': self._search_employees()
            elif choice == '8': self._show_employee_statistics()
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
                  f"{user['card']:<15} {user['group_id']:<6} {user['privilege']:<6}")

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

        print("\n" + "=" * 70)
        print("  🔄 همگام‌سازی رکوردهای تردد با دیتابیس")
        print("=" * 70)
        print("\n⚠️  این عملیات شامل مراحل زیر است:")
        print("   1. اتصال به دستگاه (اگر قطع باشد)")
        print("   2. بررسی آخرین رکورد در دیتابیس")
        print("   3. خواندن رکوردها از دستگاه")
        print("   4. DRY RUN (بدون تغییر)")
        print("   5. اجرای واقعی (با تایید شما)")
        print("   6. قطع اتصال با دستگاه")

        confirm = input("\n  آیا می‌خواهید ادامه دهید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("\n  ❌ عملیات لغو شد")
            return

        # فراخوانی متد مدیر دستگاه با dry_run_first=True
        result = self.manager.sync_attendance_to_db(dry_run_first=True)

        if 'error' in result:
            print(f"\n  ❌ {result['error']}")

    def _show_incomplete_attendances(self):
        """نمایش ترددهای ناقص - به تفکیک گروه و بدون تردد شبانه"""
        from core.attendance_analyzer import AttendanceAnalyzer
        from core.employee_manager import EmployeeManager
        from models.employee import Employee
        from models.attendance import Attendance  # ✅ اضافه شد
        from sqlalchemy import and_, func  # ✅ اضافه شد

        print("\n" + "=" * 150)
        print("  🔍 بررسی ترددهای ناقص")
        print("=" * 150)

        # دریافت بازه زمانی
        print("\n📅 بازه زمانی را مشخص کنید:")
        from_date_str = input("  از تاریخ (شمسی - مثال: 1405/04/01) [پیش‌فرض: اول ماه]: ").strip()
        to_date_str = input("  تا تاریخ (شمسی - مثال: 1405/04/24) [پیش‌فرض: امروز]: ").strip()

        try:
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
        emp_manager = EmployeeManager()
        try:
            incomplete = analyzer.get_incomplete_attendances(from_date, to_date)

            if not incomplete:
                print("\n✅ هیچ تردد ناقصی در این بازه زمانی یافت نشد!")
                return

            # ✅ فیلتر کردن ترددهای شبانه (امروز ورود، فردا خروج)
            filtered_incomplete = []
            for item in incomplete:
                # ✅ حالت ۱: فقط ورود دارد (exit_count = 0)
                if item['issue'] == 'missing_exit' and item['enter_count'] > 0 and item['exit_count'] == 0:
                    next_day = item['date'] + timedelta(days=1)
                    next_day_attendances = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == next_day,
                            Attendance.is_deleted == False
                        )
                    ).all()

                    next_day_exits = [a for a in next_day_attendances if a.punch == 1]

                    if next_day_exits:
                        continue  # تردد شبانه است

                # ✅ حالت ۲: فقط خروج دارد (enter_count = 0)
                elif item['issue'] == 'missing_enter' and item['exit_count'] > 0 and item['enter_count'] == 0:
                    prev_day = item['date'] - timedelta(days=1)
                    prev_day_attendances = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == prev_day,
                            Attendance.is_deleted == False
                        )
                    ).all()

                    prev_day_enters = [a for a in prev_day_attendances if a.punch == 0]

                    if prev_day_enters:
                        continue  # تردد شبانه است

                # ✅ حالت ۳: عدم تعادل (enter_count != exit_count)
                elif item['issue'] == 'imbalance':
                    # بررسی آیا خروجی در اوایل صبح وجود دارد که متعلق به دیروز باشد
                    day_attendances = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == item['date'],
                            Attendance.is_deleted == False
                        )
                    ).order_by(Attendance.timestamp).all()

                    enters = [a for a in day_attendances if a.punch == 0]
                    exits = [a for a in day_attendances if a.punch == 1]

                    # اگر خروج بیشتر از ورود است
                    if len(exits) > len(enters):
                        # بررسی آیا خروجی در اوایل صبح (قبل از 08:00) وجود دارد
                        early_exits = [e for e in exits if e.timestamp.hour < 8]

                        if early_exits:
                            # بررسی آیا دیروز ورود داشته
                            prev_day = item['date'] - timedelta(days=1)
                            prev_day_attendances = analyzer.db.query(Attendance).filter(
                                and_(
                                    Attendance.user_id == item['user_id'],
                                    func.date(Attendance.timestamp) == prev_day,
                                    Attendance.is_deleted == False
                                )
                            ).all()

                            prev_day_enters = [a for a in prev_day_attendances if a.punch == 0]

                            if prev_day_enters:
                                # این خروج متعلق به دیروز است، نادیده بگیر
                                # اگر حالا balanced شد، حذف کن
                                adjusted_exit_count = len(exits) - len(early_exits)
                                if len(enters) == adjusted_exit_count:
                                    continue  # تردد شبانه است، حذف کن

                    # اگر ورود بیشتر از خروج است
                    elif len(enters) > len(exits):
                        # بررسی آیا ورودی در اواخر شب (بعد از 22:00) وجود دارد که فردا خروج داشته باشد
                        late_enters = [e for e in enters if e.timestamp.hour >= 22]

                        if late_enters:
                            # بررسی آیا فردا خروج دارد
                            next_day = item['date'] + timedelta(days=1)
                            next_day_attendances = analyzer.db.query(Attendance).filter(
                                and_(
                                    Attendance.user_id == item['user_id'],
                                    func.date(Attendance.timestamp) == next_day,
                                    Attendance.is_deleted == False
                                )
                            ).all()

                            next_day_exits = [a for a in next_day_attendances if a.punch == 1]

                            if next_day_exits:
                                # این ورود متعلق به فردا است، نادیده بگیر
                                adjusted_enter_count = len(enters) - len(late_enters)
                                if adjusted_enter_count == len(exits):
                                    continue  # تردد شبانه است، حذف کن

                # اگر به اینجا رسیدیم، یعنی واقعا ناقص است
                filtered_incomplete.append(item)

            if not filtered_incomplete:
                print("\n✅ هیچ تردد ناقصی یافت نشد (همه ترددهای شبانه هستند)")
                return

            print(f"\n⚠️  تعداد {len(filtered_incomplete)} تردد ناقص یافت شد:\n")

            # ✅ گروه‌بندی بر اساس دپارتمان
            by_department = {}
            for item in filtered_incomplete:
                # دریافت اطلاعات کارمند
                employee = analyzer.db.query(Employee).filter(Employee.user_id == item['user_id']).first()
                if employee:
                    dept = employee.department or 'بدون گروه'
                    dept_name = self._get_department_name(dept)
                    full_name = employee.full_name
                else:
                    dept = 'بدون گروه'
                    dept_name = 'بدون گروه'
                    full_name = f"کاربر {item['user_id']}"

                if dept not in by_department:
                    by_department[dept] = {
                        'name': dept_name,
                        'items': []
                    }

                by_department[dept]['items'].append({
                    **item,
                    'full_name': full_name
                })

            # ✅ نمایش به تفکیک گروه
            for dept, dept_data in sorted(by_department.items(), key=lambda x: x[1]['name']):
                dept_name = dept_data['name']
                items = dept_data['items']

                # شمارش بر اساس نوع مشکل
                missing_enter = sum(1 for i in items if i['issue'] == 'missing_enter')
                missing_exit = sum(1 for i in items if i['issue'] == 'missing_exit')
                imbalance = sum(1 for i in items if i['issue'] == 'imbalance')

                print(f"\n{'=' * 150}")
                print(
                    f"  🏢 گروه: {dept_name} ({len(items)} مورد) | ⬅️ ورود بدون خروج: {missing_enter} | ➡️ خروج بدون ورود: {missing_exit} | ⚠️ عدم تعادل: {imbalance}")
                print(f"{'=' * 150}")

                # جدول
                print(
                    "\n  ┌──────┬────────────┬────────┬────────────────────────┬──────────────┬──────────────────────┬────────┬────────┐")
                print(
                    "  │ ردیف │ تاریخ      │ کد     │ نام کامل               │ دپارتمان     │ وضعیت                │ ورود   │ خروج   │")
                print(
                    "  ├──────┼────────────┼────────┼────────────────────────┼──────────────┼──────────────────────┼────────┼────────┤")

                for i, item in enumerate(items, 1):
                    # تبدیل تاریخ میلادی به شمسی
                    j_date = jdatetime.date.fromgregorian(date=item['date'])
                    date_str = j_date.strftime('%Y/%m/%d')

                    full_name = item['full_name'][:22].ljust(22)
                    dept_display = dept_name[:12].ljust(12)

                    # وضعیت با ایموجی
                    if item['issue'] == 'missing_enter':
                        issue_str = '⬅️ خروج بدون ورود'
                    elif item['issue'] == 'missing_exit':
                        issue_str = '➡️ ورود بدون خروج'
                    elif item['issue'] == 'imbalance':
                        issue_str = f'⚠️ عدم تعادل'
                    else:
                        issue_str = '❓ نامشخص'
                    issue_str = issue_str.ljust(20)

                    print(
                        f"  │ {i:<4} │ {date_str:<10} │ {item['user_id']:<6} │ {full_name} │ {dept_display} │ {issue_str} │ {item['enter_count']:<6} │ {item['exit_count']:<6} │")

                print(
                    "  └──────┴────────────┴────────┴────────────────────────┴──────────────┴──────────────────────┴────────┴────────┘")

            # ✅ خلاصه کلی
            print(f"\n{'=' * 150}")
            print("  📊 خلاصه کلی:")
            print(f"{'=' * 150}")

            total_missing_enter = sum(1 for i in filtered_incomplete if i['issue'] == 'missing_enter')
            total_missing_exit = sum(1 for i in filtered_incomplete if i['issue'] == 'missing_exit')
            total_imbalance = sum(1 for i in filtered_incomplete if i['issue'] == 'imbalance')

            print(f"     • ⬅️ خروج بدون ورود   : {total_missing_enter} مورد")
            print(f"     • ➡️ ورود بدون خروج   : {total_missing_exit} مورد")
            print(f"     • ⚠️ عدم تعادل       : {total_imbalance} مورد")
            print(f"     • 📊 مجموع کل        : {len(filtered_incomplete)} مورد")

            # خلاصه بر اساس گروه
            print(f"\n  📊 خلاصه بر اساس گروه:")
            for dept, dept_data in sorted(by_department.items(), key=lambda x: x[1]['name']):
                print(f"     • {dept_data['name']:<15} : {len(dept_data['items'])} مورد")

        finally:
            analyzer.close()
            emp_manager.close()

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
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            g_date = j_date.togregorian()
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

        # 🆕 انتخاب نوع تعطیلی
        print("\n  📋 نوع تعطیلی:")
        print("    1. ملی (برای همه گروه‌ها)")
        print("    2. گروهی (فقط برای یک گروه خاص)")
        type_choice = input("  انتخاب [1/2] [پیش‌فرض: 1]: ").strip() or '1'

        is_national = True
        group_id = None
        group_name_display = "ملی (همه)"

        if type_choice == '2':
            is_national = False
            print("\n  👥 انتخاب گروه:")
            print("    1. رسمی")
            print("    2. وظیفه")
            print("    3. خریدخدمت")
            print("    4. قراردادی")
            print("    5. پزشک")
            group_choice = input("  انتخاب [1-5]: ").strip()

            group_map = {
                '1': ('1', 'رسمی'),
                '2': ('2', 'وظیفه'),
                '3': ('3', 'خریدخدمت'),
                '4': ('4', 'قراردادی'),
                '5': ('5', 'پزشک')
            }

            if group_choice not in group_map:
                print("  ❌ انتخاب نامعتبر")
                return

            group_id, group_name_display = group_map[group_choice]

        # پیش‌نمایش
        day_name = self._get_day_name(g_date)
        print("\n" + "-" * 70)
        print("  📋 پیش‌نمایش:")
        print(f"     • تاریخ شمسی    : {j_date.strftime('%Y/%m/%d')} ({day_name})")
        print(f"     • عنوان         : {title}")
        print(f"     • نوع           : {group_name_display}")
        print("-" * 70)

        confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("  ❌ عملیات لغو شد")
            return

        manager = HolidayManager()
        try:
            result = manager.add_holiday(
                holiday_date=g_date,
                title=title,
                is_national=is_national,
                group_id=group_id
            )
            print(f"\n  {result['message']}")
        finally:
            manager.close()

    def _show_year_holidays(self):
        """نمایش تعطیلات یک سال"""
        from core.holiday_manager import HolidayManager

        print("\n" + "=" * 90)
        print("  📅 لیست تعطیلات سال")
        print("=" * 90)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال (شمسی) [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        manager = HolidayManager()
        try:
            j_from = jdatetime.date(year, 1, 1)
            try:
                j_to = jdatetime.date(year, 12, 30)
            except ValueError:
                j_to = jdatetime.date(year, 12, 29)

            from_date = j_from.togregorian()
            to_date = j_to.togregorian()

            holidays = manager.get_holidays_in_range(from_date, to_date)

            if not holidays:
                print(f"\n  ⚠️  هیچ تعطیلی در سال {year} یافت نشد (فقط جمعه‌ها)")
                return

            # شمارش
            fridays_count = sum(1 for h in holidays if h['type'] == 'friday')
            national_count = sum(1 for h in holidays if h['type'] == 'custom')
            group_count = sum(1 for h in holidays if h['type'] == 'group')

            print(f"\n  📊 تعداد کل تعطیلات: {len(holidays)}")
            print(f"     • جمعه‌ها            : {fridays_count}")
            print(f"     • تعطیلات ملی       : {national_count}")
            print(f"     • تعطیلات گروهی     : {group_count}")

            # ✅ جدول با ستون گروه
            print("\n  ┌────────────┬─────────┬────────────────────┬──────────────┐")
            print("  │ تاریخ      │ روز     │ عنوان              │ گروه         │")
            print("  ├────────────┼─────────┼────────────────────┼──────────────┤")

            group_map = {
                '1': 'رسمی',
                '2': 'وظیفه',
                '3': 'خریدخدمت',
                '4': 'قراردادی',
                '5': 'پزشک'
            }

            for h in holidays:
                j_date = jdatetime.date.fromgregorian(date=h['date'])
                day_name = self._get_day_name(h['date'])

                if h['type'] == 'friday':
                    icon = "🟡"
                    group_display = "همه"
                elif h['type'] == 'custom':
                    icon = "🔴"
                    group_display = "ملی (همه)"
                else:  # group
                    icon = "🔵"
                    group_display = group_map.get(h.get('group_id', ''), h.get('group_id', ''))

                print(
                    f"  │ {j_date.strftime('%Y/%m/%d')} │ {day_name:<7} │ {icon} {h['title'][:17]:<17} │ {group_display:<12} │")

            print("  └────────────┴─────────┴────────────────────┴──────────────┘")

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

    def _approve_leave_requests(self):
        """تایید/رد درخواست‌های مرخصی با نمایش وضعیت استحقاقی"""
        from core.leave_request_manager import LeaveRequestManager
        from core.leave_manager import LeaveManager
        from core.contract_manager import ContractManager
        from models.contract import Contract

        print("\n" + "=" * 220)
        print("  ✅ تایید/رد درخواست‌های مرخصی")
        print("=" * 220)

        manager = LeaveRequestManager()
        leave_manager = LeaveManager()
        contract_manager = ContractManager()
        try:
            pending = manager.get_pending_requests()

            if not pending:
                print("\n  ⚠️  هیچ درخواست در انتظاری وجود ندارد")
                return

            # دریافت سال و ماه فعلی
            today_j = jdatetime.date.today()
            current_year = today_j.year
            current_month = today_j.month

            # گروه‌بندی بر اساس کاربر
            by_user = {}
            for req in pending:
                if req.user_id not in by_user:
                    by_user[req.user_id] = []
                by_user[req.user_id].append(req)

            print(f"\n  📋 تعداد درخواست‌های در انتظار: {len(pending)}")
            print(f"  👥 تعداد کاربران: {len(by_user)}")
            print(f"  📅 تاریخ: {today_j.strftime('%Y/%m/%d')}")

            # ✅ جدول وضعیت استحقاقی
            print(f"\n{'=' * 220}")
            print(f"  💰 وضعیت استحقاقی مرخصی کاربران")
            print(f"{'=' * 220}")

            print("\n  ┌────────┬──────────────────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
            print("  │ کد     │ نام کامل             │ استحقاقی │ میانگین  │ ماه‌های   │ مرخصی    │ مرخصی    │ مرخصی    │ مانده    │ وضعیت    │")
            print("  │        │                      │ سالانه   │ ماهانه   │ گذشته    │ مجاز     │ رفته     │ درخواست  │ فعلی     │          │")
            print("  ├────────┼──────────────────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤")

            user_stats = {}  # ذخیره آمار برای هر کاربر

            for user_id, requests in by_user.items():
                emp_name = manager.get_employee_name(user_id)

                # دریافت مانده مرخصی
                al_balance = leave_manager.get_balance(user_id, current_year, 'AL')
                cw_balance = leave_manager.get_balance(user_id, current_year, 'CW')

                # دریافت قرارداد فعال
                contract = contract_manager.db.query(Contract).filter(
                    and_(
                        Contract.user_id == user_id,
                        Contract.start_date <= date.today(),
                        or_(
                            Contract.end_date == None,
                            Contract.end_date >= date.today()
                        )
                    )
                ).order_by(Contract.start_date.desc()).first()

                # محاسبه استحقاق سالانه
                if contract and contract.annual_leave_days:
                    annual_leave = contract.annual_leave_days
                else:
                    annual_leave = 0

                # محاسبه میانگین ماهانه
                monthly_average = annual_leave / 12 if annual_leave > 0 else 0

                # محاسبه ماه‌های گذشته
                if contract:
                    contract_start_j = jdatetime.date.fromgregorian(date=contract.start_date)
                    contract_start_month = contract_start_j.month
                    contract_start_year = contract_start_j.year

                    if contract_start_year == current_year:
                        past_months = current_month - contract_start_month
                    else:
                        past_months = current_month - 1
                else:
                    past_months = current_month - 1

                if past_months < 0:
                    past_months = 0

                # مرخصی مجاز تا الان
                allowed_leave = monthly_average * past_months

                # محاسبه مرخصی رفته شده (تایید شده)
                user_requests = manager.get_user_requests(user_id, current_year, status='A')
                used_leave = sum(r.days_count for r in user_requests if r.leave_type == 'AL')

                # مرخصی در انتظار
                pending_leave = sum(r.days_count for r in requests)

                # مانده فعلی
                current_balance = al_balance + cw_balance

                # وضعیت (+ یا -)
                if allowed_leave > 0:
                    status_value = allowed_leave - used_leave - pending_leave
                    if status_value >= 0:
                        status_display = f'+{status_value:.1f}'
                    else:
                        status_display = f'{status_value:.1f}'
                else:
                    status_display = '--'

                # ذخیره آمار
                user_stats[user_id] = {
                    'annual_leave': annual_leave,
                    'monthly_average': monthly_average,
                    'past_months': past_months,
                    'allowed_leave': allowed_leave,
                    'used_leave': used_leave,
                    'pending_leave': pending_leave,
                    'current_balance': current_balance,
                    'status_display': status_display
                }

                # نمایش با ljust برای تراز دقیق
                print(f"  │ {user_id:<6} │ {emp_name[:20]:<20} │ {annual_leave:<8} │ {monthly_average:<8.1f} │ {past_months:<8} │ {allowed_leave:<8.1f} │ {used_leave:<8.1f} │ {pending_leave:<8} │ {current_balance:<8} │ {status_display:<8} │")

            print("  └────────┴──────────────────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘")

            # ✅ راهنما
            print(f"\n  💡 راهنما:")
            print(f"     • استحقاقی سالانه: مجموع مرخصی استحقاقی در قرارداد")
            print(f"     • میانگین ماهانه: استحقاقی سالانه ÷ 12")
            print(f"     • ماه‌های گذشته: تعداد ماه‌های سپری شده از شروع قرارداد")
            print(f"     • مرخصی مجاز: میانگین ماهانه × ماه‌های گذشته")
            print(f"     • مرخصی رفته: مجموع روزهای مرخصی تایید شده تا الان")
            print(f"     • مرخصی درخواست: روزهای در انتظار تایید")
            print(f"     • مانده فعلی: مانده مرخصی استحقاقی + ذخیره")
            print(f"     • وضعیت: مرخصی مجاز - (رفته + درخواست)")

            # ✅ لیست درخواست‌ها
            print(f"\n{'=' * 220}")
            print(f"  📋 لیست درخواست‌های در انتظار")
            print(f"{'=' * 220}")

            leave_type_names = {
                'AL': 'استحقاقی',
                'SL': 'استعلاجی',
                'RL': 'تشویقی',
                'UL': 'بدون حقوق'
            }

            print("\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬────────────┬────────┬──────────────┬──────────────┬──────────────┬────────────────┐")
            print("  │ ردیف │ کد     │ نام کامل             │ از تاریخ   │ تا تاریخ   │ نوع مرخصی  │ روزها  │ مانده استحقا │ مانده ذخیره  │ مانده نوع    │ وضعیت مانده    │")
            print("  ├──────┼────────┼──────────────────────┼────────────┼────────────┼────────────┼────────┼──────────────┼──────────────┼──────────────┼────────────────┤")

            for i, req in enumerate(pending, 1):
                full_name = manager.get_employee_name(req.user_id)
                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)
                leave_type = leave_type_names.get(req.leave_type, req.leave_type)

                # دریافت مانده مرخصی
                al_balance = leave_manager.get_balance(req.user_id, current_year, 'AL')
                cw_balance = leave_manager.get_balance(req.user_id, current_year, 'CW')
                sl_balance = leave_manager.get_balance(req.user_id, current_year, 'SL')
                rl_balance = leave_manager.get_balance(req.user_id, current_year, 'RL')

                # نمایش مانده بر اساس نوع مرخصی
                if req.leave_type == 'AL':
                    al_display = f"{al_balance:<12}"
                    cw_display = f"{cw_balance:<12}"
                    type_balance = f"{al_balance + cw_balance:<12}"
                    total_balance = al_balance + cw_balance
                    if total_balance >= req.days_count:
                        status_display = '✅ کافی'
                    else:
                        status_display = f'❌ {total_balance - req.days_count} روز کم'
                elif req.leave_type == 'SL':
                    al_display = f"{al_balance:<12}"
                    cw_display = f"{cw_balance:<12}"
                    type_balance = f"{sl_balance:<12}"
                    if sl_balance >= req.days_count:
                        status_display = '✅ کافی'
                    else:
                        status_display = f'❌ {sl_balance - req.days_count} روز کم'
                elif req.leave_type == 'RL':
                    al_display = f"{al_balance:<12}"
                    cw_display = f"{cw_balance:<12}"
                    type_balance = f"{rl_balance:<12}"
                    if rl_balance >= req.days_count:
                        status_display = '✅ کافی'
                    else:
                        status_display = f'❌ {rl_balance - req.days_count} روز کم'
                else:
                    al_display = f"{al_balance:<12}"
                    cw_display = f"{cw_balance:<12}"
                    type_balance = f"{'--':<12}"
                    status_display = '✅ بدون محدودیت'

                status_display = status_display.ljust(14)

                print(f"  │ {i:<4} │ {req.user_id:<6} │ {full_name[:20]:<20} │ {j_from.strftime('%Y/%m/%d')} │ {j_to.strftime('%Y/%m/%d')} │ {leave_type:<10} │ {req.days_count:<6} │ {al_display} │ {cw_display} │ {type_balance} │ {status_display} │")

            print("  └──────┴────────┴──────────────────────┴────────────┴────────────┴────────────┴────────┴──────────────┴──────────────┴──────────────┴────────────────┘")

            # انتخاب درخواست
            print("\n" + "-" * 220)
            choice_str = input("  شماره ردیف برای تایید/رد (یا 0 برای انصراف): ").strip()

            try:
                choice = int(choice_str)
                if choice == 0:
                    print("  ❌ عملیات لغو شد")
                    return
                if choice < 1 or choice > len(pending):
                    print("  ❌ شماره نامعتبر")
                    return
            except ValueError:
                print("  ❌ عدد نامعتبر")
                return

            selected = pending[choice - 1]

            # نمایش جزئیات
            print("\n" + "-" * 220)
            print("  📋 جزئیات درخواست:")
            print(f"     • ID              : {selected.id}")
            print(f"     • کد پرسنلی       : {selected.user_id}")
            print(f"     • نام             : {manager.get_employee_name(selected.user_id)}")
            print(f"     • از تاریخ        : {jdatetime.date.fromgregorian(date=selected.from_date).strftime('%Y/%m/%d')}")
            print(f"     • تا تاریخ        : {jdatetime.date.fromgregorian(date=selected.to_date).strftime('%Y/%m/%d')}")
            print(f"     • نوع مرخصی       : {leave_type_names.get(selected.leave_type, selected.leave_type)}")
            print(f"     • تعداد روز       : {selected.days_count}")
            print(f"     • دلیل            : {selected.reason or '-'}")

            # نمایش آمار استحقاقی
            if selected.user_id in user_stats:
                stats = user_stats[selected.user_id]
                print(f"\n  📊 وضعیت استحقاقی:")
                print(f"     • استحقاقی سالانه   : {stats['annual_leave']} روز")
                print(f"     • میانگین ماهانه    : {stats['monthly_average']:.1f} روز")
                print(f"     • ماه‌های گذشته     : {stats['past_months']} ماه")
                print(f"     • مرخصی مجاز        : {stats['allowed_leave']:.1f} روز")
                print(f"     • مرخصی رفته        : {stats['used_leave']:.1f} روز")
                print(f"     • مرخصی درخواست     : {stats['pending_leave']} روز")
                print(f"     • وضعیت             : {stats['status_display']}")

            # نمایش مانده مرخصی
            al_balance = leave_manager.get_balance(selected.user_id, current_year, 'AL')
            cw_balance = leave_manager.get_balance(selected.user_id, current_year, 'CW')
            sl_balance = leave_manager.get_balance(selected.user_id, current_year, 'SL')
            rl_balance = leave_manager.get_balance(selected.user_id, current_year, 'RL')

            print(f"\n  💰 مانده مرخصی فعلی:")
            print(f"     • استحقاقی (AL)   : {al_balance} روز")
            print(f"     • ذخیره (CW)      : {cw_balance} روز")
            print(f"     • استعلاجی (SL)   : {sl_balance} روز")
            print(f"     • تشویقی (RL)     : {rl_balance} روز")

            # بررسی مانده کافی
            if selected.leave_type == 'AL':
                total_balance = al_balance + cw_balance
                if total_balance < selected.days_count:
                    print(f"\n  ⚠️  هشدار: مانده کافی نیست! (مجموع: {total_balance}، درخواست: {selected.days_count})")
            elif selected.leave_type == 'SL':
                if sl_balance < selected.days_count:
                    print(f"\n  ⚠️  هشدار: مانده استعلاجی کافی نیست! (مانده: {sl_balance}، درخواست: {selected.days_count})")
            elif selected.leave_type == 'RL':
                if rl_balance < selected.days_count:
                    print(f"\n  ⚠️  هشدار: مانده تشویقی کافی نیست! (مانده: {rl_balance}، درخواست: {selected.days_count})")

            # انتخاب عملیات
            print("\n  عملیات:")
            print("    1. تایید")
            print("    2. رد")
            print("    0. انصراف")

            action = input("\n  انتخاب [0-2]: ").strip()

            if action == '0':
                print("  ❌ عملیات لغو شد")
                return
            elif action == '1':
                result = manager.approve_request(selected.id, approved_by="ADMIN")
                print(f"\n  {result['message']}")

                if result['success']:
                    new_al = leave_manager.get_balance(selected.user_id, current_year, 'AL')
                    new_cw = leave_manager.get_balance(selected.user_id, current_year, 'CW')
                    new_sl = leave_manager.get_balance(selected.user_id, current_year, 'SL')
                    new_rl = leave_manager.get_balance(selected.user_id, current_year, 'RL')

                    print(f"\n  💰 مانده مرخصی جدید:")
                    print(f"     • استحقاقی (AL)   : {new_al} روز")
                    print(f"     • ذخیره (CW)      : {new_cw} روز")
                    print(f"     • استعلاجی (SL)   : {new_sl} روز")
                    print(f"     • تشویقی (RL)     : {new_rl} روز")

            elif action == '2':
                reason = input("  دلیل رد (اختیاری): ").strip()
                result = manager.reject_request(selected.id, rejection_reason=reason)
                print(f"\n  {result['message']}")
            else:
                print("  ❌ انتخاب نامعتبر")

        finally:
            manager.close()
            leave_manager.close()
            contract_manager.close()


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

    def _get_department_name(self, dept_code: str) -> str:
        """تبدیل کد دپارتمان به نام فارسی"""
        dept_map = {
            '1': 'رسمی',
            '2': 'وظیفه',
            '3': 'خریدخدمت',
            '4': 'قراردادی',
            '5': 'پزشک',
            None: 'بدون گروه',
            '': 'بدون گروه'
        }
        return dept_map.get(str(dept_code) if dept_code else '', f'گروه {dept_code}')

    def _show_daily_report(self):
        """گزارش وضعیت روزانه - مرتب بر اساس گروه، وضعیت و تاریخ استخدام"""
        from core.daily_status_manager import DailyStatusManager
        from core.contract_manager import ContractManager

        print("\n" + "=" * 220)
        print("  📅 گزارش وضعیت روزانه")
        print("=" * 220)

        date_str = input("\n  📅 تاریخ (شمسی - مثال: 1405/04/01) [پیش‌فرض: امروز]: ").strip()
        if date_str:
            try:
                j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
                target_date = j_date.togregorian()
            except Exception as e:
                print(f"  ❌ خطا در تبدیل تاریخ: {e}")
                return
        else:
            target_date = date.today()

        # انتخاب گروه
        print("\n  📋 انتخاب گروه:")
        print("    0. همه گروه‌ها")
        print("    1. رسمی")
        print("    2. وظیفه")
        print("    3. خریدخدمت")
        print("    4. قراردادی")
        print("    5. پزشک")
        group_choice = input("  انتخاب [0-5] [پیش‌فرض: 0]: ").strip() or '0'

        if group_choice == '0':
            group_id = None
        elif group_choice.isdigit() and group_choice in ['1', '2', '3', '4', '5']:
            group_id = group_choice
        else:
            group_id = None

        manager = DailyStatusManager()
        contract_manager = ContractManager()
        try:
            report = manager.get_daily_report(target_date, group_id, active_only=True)

            j_date = jdatetime.date.fromgregorian(date=target_date)
            day_name = self._get_day_name(target_date)

            print(f"\n  📅 تاریخ: {j_date.strftime('%Y/%m/%d')} ({day_name})")
            print(f"  👥 تعداد کاربران: {len(report)}")

            if not report:
                print("\n  ⚠️  هیچ کاربری یافت نشد")
                print("  💡 نکته: مطمئن شوید کارمندان در جدول employee ثبت شده و فعال هستند")
                return

            # شمارش وضعیت‌ها
            status_counts = {}
            for r in report:
                code = r['status']
                status_counts[code] = status_counts.get(code, 0) + 1

            # ✅ مرتب‌سازی بر اساس گروه، وضعیت، تاریخ استخدام، نام
            status_order = {
                'P': 0, 'M': 1, 'LP': 2,
                'AL': 3, 'SL': 3, 'RL': 3, 'UL': 3, 'L': 3,
                'R': 4,
                'H': 5,
                'A': 6,
            }

            # ✅ مرتب‌سازی فقط بر اساس تاریخ استخدام
            def sort_key(r):
                hire_date = r.get('hire_date')
                if hire_date is None:
                    # اگر تاریخ استخدام ندارد، آخر قرار بگیرد
                    return (date.max, r.get('full_name', ''))
                return (hire_date, r.get('full_name', ''))


            report_sorted = sorted(report, key=sort_key)

            # گروه‌بندی بر اساس دپارتمان
            by_department = {}
            for r in report_sorted:
                dept = r.get('department', 'بدون گروه')
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(r)

            # نمایش به تفکیک گروه
            for dept, dept_report in sorted(by_department.items()):
                # ✅ شمارش بر اساس person_status
                present_count = sum(1 for r in dept_report if r.get('person_status') == 'حاضر')
                absent_count = sum(1 for r in dept_report if r.get('person_status') == 'غایب')
                leave_count = sum(1 for r in dept_report if r.get('person_status') == 'مرخصی')
                rest_count = sum(1 for r in dept_report if r.get('person_status') == 'استراحت')
                holiday_count = sum(1 for r in dept_report if r.get('person_status') == 'تعطیل')
                mission_count = sum(1 for r in dept_report if r.get('person_status') == 'ماموریت')
                late_count = sum(1 for r in dept_report if r.get('person_status') == 'حضور کم')

                # ✅ نام فارسی دپارتمان
                dept_name = self._get_department_name(dept)

                print(f"\n{'=' * 220}")
                print(
                    f"  🏢 گروه: {dept_name} ({len(dept_report)} کاربر) | ✅ حاضر: {present_count} | 💼 ماموریت: {mission_count} | ⏰ حضور کم: {late_count} | 🌴 مرخصی: {leave_count} | 🛌 استراحت: {rest_count} | 🟡 تعطیل: {holiday_count} | ❌ غایب: {absent_count}")
                print(f"{'=' * 220}")

                # ✅ جدول با ستون‌های جدید و تراز دقیق
                print(
                    "\n  ┌──────┬────────┬────────────────────────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────────────────┬──────────────┬────────┬────────┬──────────────┐")
                print(
                    "  │ ردیف │ کد     │ نام کامل               │ دپارتمان     │ تاریخ استخدام│ وضعیت روز    │ وضعیت فرد    │ وضعیت تردد           │ قرارداد      │ ورود   │ خروج   │ ساعات کاری   │")
                print(
                    "  ├──────┼────────┼────────────────────────┼──────────────┼──────────────┼──────────────┼──────────────┼──────────────────────┼──────────────┼────────┼────────┼──────────────┤")

                for i, r in enumerate(dept_report, 1):
                    # ✅ استفاده از ljust برای تراز دقیق
                    full_name = r['full_name'][:22].ljust(22)

                    # ✅ نام فارسی دپارتمان
                    dept_display = self._get_department_name(r.get('department', '-'))[:12].ljust(12)

                    # ✅ تاریخ استخدام
                    hire_date = r.get('hire_date')
                    if hire_date:
                        try:
                            j_hire = jdatetime.date.fromgregorian(date=hire_date)
                            hire_str = j_hire.strftime('%Y/%m/%d')
                        except:
                            hire_str = '  --  '
                    else:
                        hire_str = '  --  '
                    hire_str = hire_str.ljust(12)

                    contract_display = ('✅ فعال' if r['contract']['has_contract'] else '❌ بدون').ljust(12)

                    # ✅ سه ستون وضعیت با ایموجی
                    day_status_raw = r.get('day_status', 'کاری')
                    day_status = ('🔴 تعطیل' if day_status_raw == 'تعطیل' else '🟢 کاری').ljust(12)

                    person_status_raw = r.get('person_status', 'نامشخص')
                    if person_status_raw == 'حاضر':
                        person_status = '✅ حاضر'
                    elif person_status_raw == 'مرخصی':
                        person_status = '🌴 مرخصی'
                    elif person_status_raw == 'استراحت':
                        person_status = '🛌 استراحت'
                    elif person_status_raw == 'غایب':
                        person_status = '❌ غایب'
                    elif person_status_raw == 'تعطیل':
                        person_status = '🟡 تعطیل'
                    elif person_status_raw == 'ماموریت':
                        person_status = '💼 ماموریت'
                    elif person_status_raw == 'حضور کم':
                        person_status = '⏰ حضور کم'
                    else:
                        person_status = f'❓ {person_status_raw}'
                    person_status = person_status[:12].ljust(12)

                    # ✅ وضعیت تردد با ایموجی
                    attendance_status_raw = r.get('attendance_status', 'بدون تردد')
                    if attendance_status_raw == 'کامل':
                        attendance_status = '✅ کامل'
                    elif attendance_status_raw.startswith('کامل'):
                        attendance_status = f'✅ {attendance_status_raw}'
                    elif 'ناقص' in attendance_status_raw:
                        attendance_status = f'⚠️ {attendance_status_raw}'
                    elif 'ورود بدون' in attendance_status_raw:
                        attendance_status = f'⬅️ {attendance_status_raw}'
                    elif 'خروج بدون' in attendance_status_raw:
                        attendance_status = f'➡️ {attendance_status_raw}'
                    else:
                        attendance_status = '⚪ بدون تردد'
                    attendance_status = attendance_status[:20].ljust(20)

                    first_enter = r['first_enter'].strftime('%H:%M') if r['first_enter'] else '  --  '
                    last_exit = r['last_exit'].strftime('%H:%M') if r['last_exit'] else '  --  '

                    if r['work_hours'] > 0:
                        work_h = int(r['work_hours'])
                        work_m = int((r['work_hours'] - work_h) * 60)
                        work_str = f"{work_h:02d}:{work_m:02d}"
                    else:
                        work_str = '  --  '

                    print(
                        f"  │ {i:<4} │ {r['user_id']:<6} │ {full_name} │ {dept_display} │ {hire_str} │ {day_status} │ {person_status} │ {attendance_status} │ {contract_display} │ {first_enter} │ {last_exit} │ {work_str:<12} │")

                print(
                    "  └──────┴────────┴────────────────────────┴──────────────┴──────────────┴──────────────┴──────────────┴──────────────────────┴──────────────┴────────┴────────┴──────────────┘")

            # ✅ آمار کلی بر اساس person_status
            print(f"\n{'=' * 220}")
            print("  📊 آمار کلی:")
            print(f"{'=' * 220}")

            present_total = sum(1 for r in report if r.get('person_status') == 'حاضر')
            mission_total = sum(1 for r in report if r.get('person_status') == 'ماموریت')
            late_total = sum(1 for r in report if r.get('person_status') == 'حضور کم')
            leave_total = sum(1 for r in report if r.get('person_status') == 'مرخصی')
            rest_total = sum(1 for r in report if r.get('person_status') == 'استراحت')
            holiday_total = sum(1 for r in report if r.get('person_status') == 'تعطیل')
            absent_total = sum(1 for r in report if r.get('person_status') == 'غایب')

            print(f"     • ✅ حاضر              : {present_total} نفر")
            print(f"     • 💼 ماموریت           : {mission_total} نفر")
            print(f"     • ⏰ حضور کم           : {late_total} نفر")
            print(f"     • 🌴 مرخصی             : {leave_total} نفر")
            print(f"     • 🛌 استراحت           : {rest_total} نفر")
            print(f"     • 🟡 تعطیل             : {holiday_total} نفر")
            print(f"     • ❌ غایب              : {absent_total} نفر")

            # ✅ جزئیات مرخصی
            leave_details = {}
            for r in report:
                if r.get('person_status') == 'مرخصی':
                    code = r['status']
                    leave_details[code] = leave_details.get(code, 0) + 1

            if leave_details:
                print(f"\n  📋 جزئیات مرخصی:")
                for code, count in sorted(leave_details.items()):
                    status_name = manager.get_status_name(code)
                    emoji = {'AL': '🌴', 'SL': '🏥', 'RL': '🎁', 'UL': '💸', 'L': '🌴'}.get(code, '•')
                    print(f"     • {emoji} {status_name:<23} : {count} نفر")

        finally:
            manager.close()
            contract_manager.close()

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
        """گزارش ماهانه همه کاربران - فقط از employee"""
        from core.report_generator import ReportGenerator
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 140)
        print("  📊 گزارش ماهانه همه کاربران")
        print("=" * 140)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        # ✅ فیلتر بر اساس دپارتمان
        print("\n  📋 فیلتر بر اساس دپارتمان:")
        print("    0. همه دپارتمان‌ها")
        print("    1. رسمی")
        print("    2. وظیفه")
        print("    3. خریدخدمت")
        print("    4. قراردادی")
        print("    5. پزشک")
        dept_choice = input("  انتخاب [0-5]: ").strip()
        department = dept_choice if dept_choice != '0' else None

        generator = ReportGenerator()
        emp_manager = EmployeeManager()
        try:
            reports = generator.generate_monthly_report_for_all(year, month, department)

            print(f"\n  📅 ماه: {self._get_jalali_month_name(month)} {year}")
            print(f"  👥 تعداد کاربران: {len(reports)}")

            if not reports:
                print("\n  ⚠️  هیچ کاربری یافت نشد")
                return

            # ✅ گروه‌بندی بر اساس department
            by_department = {}
            for r in reports:
                dept = r['department']
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(r)

            # نمایش به تفکیک دپارتمان
            for dept, dept_reports in sorted(by_department.items()):
                print(f"\n{'=' * 140}")
                print(f"  🏢 دپارتمان: {dept} ({len(dept_reports)} کاربر)")
                print(f"{'=' * 140}")

                print(
                    "\n  ┌──────┬────────┬──────────────────────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────────┐")
                print(
                    "  │ ردیف │ کد     │ نام کامل             │حاضر│غایب│تعطیل│استحق│استعل│تشویق│بدون ح│مامور│حضورک│ویژه│ ساعت   │")
                print(
                    "  ├──────┼────────┼──────────────────────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────────┤")

                for i, r in enumerate(dept_reports, 1):
                    work_str = f"{int(r['work_hours'])}:{int((r['work_hours'] % 1) * 60):02d}"
                    print(f"  │ {i:<4} │ {r['user_id']:<6} │ {r['full_name'][:20]:<20} │ "
                          f"{r['present_days']:<2} │ {r['absent_days']:<2} │ {r['holiday_days']:<2} │ "
                          f"{r['annual_leave']:<2} │ {r['sick_leave']:<3} │ {r['reward_leave']:<3} │ "
                          f"{r['unpaid_leave']:<3} │ {r['mission_days']:<2} │ {r['late_days']:<2} │ {r['special_days']:<2} │ {work_str:<6} │")

                print(
                    "  └──────┴────────┴──────────────────────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────────┘")

                # خلاصه دپارتمان
                total_work = sum(r['work_hours'] for r in dept_reports)
                total_present = sum(r['present_days'] for r in dept_reports)
                total_absent = sum(r['absent_days'] for r in dept_reports)

                print(f"\n  📊 خلاصه دپارتمان {dept}:")
                print(f"     • مجموع ساعات کاری: {int(total_work)}:{int((total_work % 1) * 60):02d}")
                print(f"     • مجموع روزهای حاضر: {total_present}")
                print(f"     • مجموع روزهای غایب: {total_absent}")

        finally:
            generator.close()
            emp_manager.close()

    def _show_absent_report(self):
        """گزارش غیبت‌ها"""
        from core.report_generator import ReportGenerator
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 100)
        print("  ❌ گزارش غیبت‌ها")
        print("=" * 100)

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
        emp_manager = EmployeeManager()
        try:
            print("\n  ⏳ در حال محاسبه...")
            reports = generator.generate_absent_report(g_from, g_to)

            if not reports:
                print("\n  ✅ هیچ غیبتی در این بازه ثبت نشده است")
                return

            print(f"\n  📊 تعداد افراد غایب: {len(reports)}")

            # ✅ جدول با نام کامل و گروه
            print(
                "\n  ┌──────┬────────┬────────────────────────┬────────────┬──────────┬──────────────────────────────────────┐")
            print(
                "  │ ردیف │ کد     │ نام کامل               │ گروه       │ تعداد    │ تاریخ‌های غیبت                        │")
            print(
                "  ├──────┼────────┼────────────────────────┼────────────┼──────────┼──────────────────────────────────────┤")

            group_map = {
                '0': 'بدون گروه',
                '1': 'رسمی',
                '2': 'وظیفه',
                '3': 'خریدخدمت',
                '4': 'قراردادی',
                '5': 'پزشک'
            }
            for i, r in enumerate(reports, 1):
                # ✅ استفاده مستقیم از full_name و department
                full_name = r['full_name']
                department = r['department'][:10]

                dates_str = ', '.join([
                    jdatetime.date.fromgregorian(date=d).strftime('%Y/%m/%d')
                    for d in r['absent_dates'][:5]
                ])
                if len(r['absent_dates']) > 5:
                    dates_str += f" ... (+{len(r['absent_dates']) - 5})"

                print(
                    f"  │ {i:<4} │ {r['user_id']:<6} │ {full_name[:22]:<22} │ {department:<10} │ {r['absent_count']:<8} │ {dates_str:<36} │")

            print(
                "  └──────┴────────┴────────────────────────┴────────────┴──────────┴──────────────────────────────────────┘")

            # ✅ خلاصه بر اساس department
            dept_counts = {}
            for r in reports:
                dept = r['department']
                dept_counts[dept] = dept_counts.get(dept, 0) + r['absent_count']

            print(f"\n  📊 خلاصه بر اساس دپارتمان:")
            for dept, count in sorted(dept_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"     • {dept:<15} : {count} روز غیبت")
        finally:
            generator.close()
            emp_manager.close()

    def _show_leave_report(self):
        """گزارش مرخصی‌ها با ساختار جدید (کل، استفاده شده، مانده)"""
        from core.report_generator import ReportGenerator
        from core.excel_leave_export import ExcelLeaveExporter
        from core.pdf_leave_export import PDFLeaveExporter

        print("\n" + "=" * 250)
        print("  🌴 گزارش مرخصی‌ها")
        print("=" * 250)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [خالی = کل سال]: ").strip()
        month = int(month_str) if month_str else None

        generator = ReportGenerator()
        try:
            reports = generator.generate_leave_report(year, month)

            period = f"{self._get_jalali_month_name(month)} {year}" if month else f"سال {year}"
            print(f"\n  📅 دوره: {period}")
            print(f"  👥 تعداد کاربران: {len(reports)}")

            if not reports:
                print("\n  ⚠️  هیچ کاربری یافت نشد")
                return

            # ✅ نام‌های فارسی دپارتمان
            dept_names = {
                '1': 'رسمی',
                '2': 'وظیفه',
                '3': 'خریدخدمت',
                '4': 'قراردادی',
                '5': 'پزشک',
                None: 'بدون گروه',
                '': 'بدون گروه'
            }

            # ✅ گروه‌بندی بر اساس دپارتمان
            by_department = {}
            for r in reports:
                dept = r['department']
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(r)

            for dept, dept_reports in sorted(by_department.items()):
                dept_name = dept_names.get(str(dept), f'گروه {dept}')
                print(f"\n{'=' * 250}")
                print(f"  🏢 دپارتمان: {dept_name} ({len(dept_reports)} کاربر)")
                print(f"{'=' * 250}")

                # ✅ هدر دو سطری
                print("\n  ┌────┬──────┬────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐")
                print("  │ #  │ Code │ Name               │ AL-T │ AL-U │ AL-B │ SL-T │ SL-U │ SL-B │ RL-T │ RL-U │ RL-B │ UL-T │ UL-U │ UL-B │ CW-T │ CW-U │ CW-B │ TOT-T│ TOT-U│ TOT-B│")
                print("  ├────┼──────┼────────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤")

                for i, r in enumerate(dept_reports, 1):
                    print(f"  │ {i:<2} │ {r['user_id']:<4} │ {r['full_name'][:18]:<18} │ "
                          f"{r['al_total']:<4} │ {r['al_used']:<4} │ {r['al_balance']:<4} │ "
                          f"{r['sl_total']:<4} │ {r['sl_used']:<4} │ {r['sl_balance']:<4} │ "
                          f"{r['rl_total']:<4} │ {r['rl_used']:<4} │ {r['rl_balance']:<4} │ "
                          f"{r['ul_total']:<4} │ {r['ul_used']:<4} │ {r['ul_balance']:<4} │ "
                          f"{r['cw_total']:<4} │ {r['cw_used']:<4} │ {r['cw_balance']:<4} │ "
                          f"{r['tot_total']:<4} │ {r['tot_used']:<4} │ {r['tot_balance']:<4} │")

                print("  └────┴──────┴────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘")

                # خلاصه دپارتمان
                sum_al_t = sum(r['al_total'] for r in dept_reports)
                sum_al_u = sum(r['al_used'] for r in dept_reports)
                sum_al_b = sum(r['al_balance'] for r in dept_reports)
                sum_sl_t = sum(r['sl_total'] for r in dept_reports)
                sum_sl_u = sum(r['sl_used'] for r in dept_reports)
                sum_sl_b = sum(r['sl_balance'] for r in dept_reports)
                sum_rl_t = sum(r['rl_total'] for r in dept_reports)
                sum_rl_u = sum(r['rl_used'] for r in dept_reports)
                sum_rl_b = sum(r['rl_balance'] for r in dept_reports)
                sum_ul_t = sum(r['ul_total'] for r in dept_reports)
                sum_ul_u = sum(r['ul_used'] for r in dept_reports)
                sum_ul_b = sum(r['ul_balance'] for r in dept_reports)
                sum_cw_t = sum(r['cw_total'] for r in dept_reports)
                sum_cw_u = sum(r['cw_used'] for r in dept_reports)
                sum_cw_b = sum(r['cw_balance'] for r in dept_reports)
                sum_tot_t = sum(r['tot_total'] for r in dept_reports)
                sum_tot_u = sum(r['tot_used'] for r in dept_reports)
                sum_tot_b = sum(r['tot_balance'] for r in dept_reports)

                print("  ┌────┬──────┬────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐")
                print(f"  │ Σ  │      │                    │ {sum_al_t:<4} │ {sum_al_u:<4} │ {sum_al_b:<4} │ "
                      f"{sum_sl_t:<4} │ {sum_sl_u:<4} │ {sum_sl_b:<4} │ "
                      f"{sum_rl_t:<4} │ {sum_rl_u:<4} │ {sum_rl_b:<4} │ "
                      f"{sum_ul_t:<4} │ {sum_ul_u:<4} │ {sum_ul_b:<4} │ "
                      f"{sum_cw_t:<4} │ {sum_cw_u:<4} │ {sum_cw_b:<4} │ "
                      f"{sum_tot_t:<4} │ {sum_tot_u:<4} │ {sum_tot_b:<4} │")
                print("  └────┴──────┴────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘")

            # ✅ راهنما
            print(f"\n  💡 راهنمای ستون‌ها:")
            print(f"     • AL = Annual Leave (استحقاقی)")
            print(f"     • SL = Sick Leave (استعلاجی)")
            print(f"     • RL = Reward Leave (تشویقی)")
            print(f"     • UL = Unpaid Leave (بدون حقوق)")
            print(f"     • CW = Carryover (ذخیره سال قبل)")
            print(f"     • TOT = Total (مجموع)")
            print(f"     • T = Total (کل) | U = Used (استفاده شده) | B = Balance (مانده)")

            # ✅ منوی خروجی
            print("\n" + "=" * 250)
            print("  📤 خروجی:")
            print("    1. اکسل")
            print("    2. PDF")
            print("    3. هر دو")
            print("    0. بدون خروجی")
            export_choice = input("  انتخاب [0-3]: ").strip()

            if export_choice in ['1', '3']:
                exporter = ExcelLeaveExporter()
                filename = exporter.export_leave_report(reports, year, month, period)
                print(f"\n  ✅ فایل اکسل: {filename}")

            if export_choice in ['2', '3']:
                exporter = PDFLeaveExporter()
                filename = exporter.export_leave_report(reports, year, month, period, dept_names)
                print(f"\n  ✅ فایل PDF: {filename}")

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

            if not reports:
                print("\n  ⚠️  هیچ داده‌ای برای خروجی یافت نشد")
                return

            exporter = ExcelExporter()
            filename = exporter.export_monthly_report(reports, year, month)

            print(f"\n  ✅ فایل اکسل با موفقیت ایجاد شد:")
            print(f"     📁 {filename}")
            print(f"     📊 تعداد کاربران: {len(reports)}")

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

            print(f"\n  👤 اطلاعات کارمند:")
            print(f"     • کد پرسنلی    : {user_id}")
            print(f"     • نام کامل     : {employee.full_name}")
            print(f"     • دپارتمان     : {employee.department or 'بدون گروه'}")

            print(f"\n  📋 اطلاعات تکمیلی:")
            print(f"     • نام کامل     : {employee.full_name}")
            print(f"     • وضعیت        : {employee.status_name}")  # ✅ جدید
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

            # ✅ اطلاعات ترک کار
            if not employee.is_active:
                print(f"\n  ❌ اطلاعات ترک کار:")
                if employee.termination_date:
                    j_term = jdatetime.date.fromgregorian(date=employee.termination_date)
                    print(f"     • تاریخ ترک    : {j_term.strftime('%Y/%m/%d')}")
                if employee.termination_reason:
                    print(f"     • دلیل         : {employee.termination_reason}")

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
            print(f"     • فعال                  : {stats['active']} ✅")
            print(f"     • غیرفعال (ترک کار)     : {stats['inactive']} ❌")
            print(f"     • دارای کد ملی (فعال)   : {stats['with_national_code']}")
            print(f"     • دارای ایمیل (فعال)    : {stats['with_email']}")
            print(f"     • تعداد دپارتمان‌ها      : {stats['departments']}")

            print(f"\n  ⚧ آمار جنسیت (فعال):")
            print(f"     • مرد                   : {stats['males']}")
            print(f"     • زن                    : {stats['females']}")

            print(f"\n  💍 آمار تاهل (فعال):")
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

        print("\n" + "=" * 180)
        print("  📊 گزارش تحلیلی ماهانه")
        print("=" * 180)

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
                print(f"\n{'=' * 180}")
                print(f"  👥 گروه: {group_name} ({len(users)} کاربر)")
                print(f"{'=' * 180}")

                # ✅ جدول با فاصله بیشتر و ستون‌های درصد
                print(
                    "\n  ┌────┬────────┬────────────────────────┬──────┬──────┬──────┬──────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐")
                print(
                    "  │ #  │ کد     │ نام کامل               │ حاضر │ غایب │ مرخصی│ روز  │ ساعت     │ صبح      │ عصر      │ شب       │ کل       │ کسری/+   │")
                print(
                    "  │    │        │                        │      │      │      │ موظفی│ موظفی    │ (درصد)   │ (درصد)   │ (درصد)   │          │          │")
                print(
                    "  ├────┼────────┼────────────────────────┼──────┼──────┼──────┼──────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤")

                for i, u in enumerate(users, 1):
                    # فرمت ساعات
                    def fmt_hours(h):
                        if h == 0:
                            return "  --    "
                        sign = "-" if h < 0 else ""
                        abs_h = abs(h)
                        hours = int(abs_h)
                        minutes = int(round((abs_h - hours) * 60))
                        if minutes >= 60:
                            hours += 1
                            minutes = 0
                        return f"{sign}{hours:02d}:{minutes:02d}"

                    # ✅ محاسبه درصد
                    total = u['total_hours']
                    if total > 0:
                        morning_pct = (u['morning_hours'] / total) * 100
                        evening_pct = (u['evening_hours'] / total) * 100
                        night_pct = (u['night_hours'] / total) * 100
                    else:
                        morning_pct = 0
                        evening_pct = 0
                        night_pct = 0

                    # فرمت ساعت با درصد
                    morning_str = f"{fmt_hours(u['morning_hours'])} ({morning_pct:4.1f}%)"
                    evening_str = f"{fmt_hours(u['evening_hours'])} ({evening_pct:4.1f}%)"
                    night_str = f"{fmt_hours(u['night_hours'])} ({night_pct:4.1f}%)"

                    # فرمت کسری/اضافی
                    diff = u['difference']
                    if diff > 0.5:
                        diff_str = f"+{fmt_hours(diff)} ✅"
                    elif diff < -0.5:
                        diff_str = f"{fmt_hours(diff)} ❌"
                    else:
                        diff_str = f" 00:00 ✅"

                    # ✅ نام کامل با فاصله بیشتر (22 کاراکتر)
                    full_name = u['full_name'][:22]

                    print(f"  │ {i:<2} │ {u['user_id']:<6} │ {full_name:<22} │ "
                          f"{u['present_days']:<4} │ {u['absent_days']:<4} │ {u['leave_days']:<4} │ "
                          f"{u['required_days']:<4} │ {fmt_hours(u['required_hours'])} │ "
                          f"{morning_str:<8} │ {evening_str:<8} │ {night_str:<8} │ {fmt_hours(u['total_hours'])} │ {diff_str:<8} │")

                print(
                    "  └────┴────────┴────────────────────────┴──────┴──────┴──────┴──────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘")

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

    def _list_active_employees(self):
        """لیست کارمندان فعال"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 110)
        print("  👥 لیست کارمندان فعال")
        print("=" * 110)

        manager = EmployeeManager()
        try:
            employees = manager.get_all_employees(active_only=True)

            if not employees:
                print("\n  ⚠️  هیچ کارمند فعالی ثبت نشده است")
                return

            print(f"\n  📊 تعداد کارمندان فعال: {len(employees)}")

            print("\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬────────────┐")
            print("  │ ردیف │ کد     │ نام کامل             │ دپارتمان   │ سمت        │ تاریخ استخدام │")
            print("  ├──────┼────────┼──────────────────────┼────────────┼────────────┼────────────┤")

            for i, emp in enumerate(employees, 1):
                hire_str = ""
                if emp.hire_date:
                    j_hire = jdatetime.date.fromgregorian(date=emp.hire_date)
                    hire_str = j_hire.strftime('%Y/%m/%d')

                print(f"  │ {i:<4} │ {emp.user_id:<6} │ {emp.full_name[:20]:<20} │ "
                      f"{emp.department or '-':<10} │ {emp.position or '-':<10} │ {hire_str:<10} │")

            print("  └──────┴────────┴──────────────────────┴────────────┴────────────┴────────────┘")

        finally:
            manager.close()

    def _list_inactive_employees(self):
        """لیست کارمندان غیرفعال"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 120)
        print("  ❌ لیست کارمندان غیرفعال (ترک کار)")
        print("=" * 120)

        manager = EmployeeManager()
        try:
            employees = manager.db.query(Employee).filter(Employee.is_active == False).order_by(
                Employee.termination_date.desc()
            ).all()

            if not employees:
                print("\n  ✅ هیچ کارمند غیرفعالی وجود ندارد")
                return

            print(f"\n  📊 تعداد کارمندان غیرفعال: {len(employees)}")

            print("\n  ┌──────┬────────┬──────────────────────┬────────────┬────────────┬──────────────────────┐")
            print("  │ ردیف │ کد     │ نام کامل             │ دپارتمان   │ تاریخ ترک  │ دلیل                   │")
            print("  ├──────┼────────┼──────────────────────┼────────────┼────────────┼──────────────────────┤")

            for i, emp in enumerate(employees, 1):
                term_date_str = ""
                if emp.termination_date:
                    j_term = jdatetime.date.fromgregorian(date=emp.termination_date)
                    term_date_str = j_term.strftime('%Y/%m/%d')

                reason = (emp.termination_reason or '-')[:20]

                print(f"  │ {i:<4} │ {emp.user_id:<6} │ {emp.full_name[:20]:<20} │ "
                      f"{emp.department or '-':<10} │ {term_date_str:<10} │ {reason:<20} │")

            print("  └──────┴────────┴──────────────────────┴────────────┴────────────┴──────────────────────┘")

        finally:
            manager.close()

    def _set_employee_status(self):
        """تغییر وضعیت کارمند (فعال/غیرفعال)"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  🔄 تغییر وضعیت کارمند")
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

            current_status = "فعال ✅" if employee.is_active else "غیرفعال ❌"
            print(f"\n  👤 کاربر: {employee.full_name}")
            print(f"  📊 وضعیت فعلی: {current_status}")

            if employee.is_active:
                # غیرفعال کردن
                print("\n  🎯 عملیات: غیرفعال کردن (ثبت ترک کار)")

                term_date_str = input(f"  📅 تاریخ ترک کار (شمسی) [پیش‌فرض: امروز]: ").strip()
                try:
                    if term_date_str:
                        j_term = jdatetime.datetime.strptime(term_date_str, "%Y/%m/%d").date()
                        term_date = j_term.togregorian()
                    else:
                        term_date = date.today()
                except Exception as e:
                    print(f"  ❌ خطا در تبدیل تاریخ: {e}")
                    return

                print("\n  📋 دلایل ترک کار:")
                print("    1. استعفا")
                print("    2. بازنشستگی")
                print("    3. اخراج")
                print("    4. پایان قرارداد")
                print("    5. انتقال")
                print("    6. سایر")
                reason_choice = input("  انتخاب [1-6]: ").strip()

                reason_map = {
                    '1': 'استعفا',
                    '2': 'بازنشستگی',
                    '3': 'اخراج',
                    '4': 'پایان قرارداد',
                    '5': 'انتقال',
                    '6': 'سایر'
                }
                reason = reason_map.get(reason_choice, 'سایر')

                if reason_choice == '6':
                    custom_reason = input("  📝 دلیل (دستی): ").strip()
                    if custom_reason:
                        reason = custom_reason

                # پیش‌نمایش
                j_term_display = jdatetime.date.fromgregorian(date=term_date)
                print("\n" + "-" * 70)
                print("  📋 پیش‌نمایش:")
                print(f"     • کاربر           : {employee.full_name}")
                print(f"     • وضعیت جدید      : غیرفعال ❌")
                print(f"     • تاریخ ترک کار   : {j_term_display.strftime('%Y/%m/%d')}")
                print(f"     • دلیل            : {reason}")
                print("-" * 70)

                confirm = input("\n  آیا تایید می‌کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ لغو شد")
                    return

                result = manager.set_employee_status(
                    user_id=user_id,
                    is_active=False,
                    termination_date=term_date,
                    termination_reason=reason
                )
            else:
                # فعال کردن
                print("\n  🎯 عملیات: فعال کردن")
                print(f"     • تاریخ ترک کار قبلی: {employee.termination_date}")
                print(f"     • دلیل قبلی: {employee.termination_reason}")

                confirm = input("\n  آیا می‌خواهید کاربر را فعال کنید؟ (بله/خیر): ").strip()
                if confirm.lower() not in ['بله', 'yes', 'y']:
                    print("  ❌ لغو شد")
                    return

                result = manager.set_employee_status(
                    user_id=user_id,
                    is_active=True
                )

            print(f"\n  {result['message']}")

        finally:
            manager.close()

    def _show_detailed_monthly_report(self):
        """نمایش گزارش تفصیلی ماهانه"""
        from core.detailed_monthly_report import DetailedMonthlyReportGenerator

        print("\n" + "=" * 150)
        print("  📊 گزارش تفصیلی ماهانه کارمند - گروه قراردادی")
        print("=" * 150)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  📅 سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  📅 ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = DetailedMonthlyReportGenerator()
        try:
            # دریافت کارمندان گروه قراردادی
            employees = generator.get_employees_by_department('4')

            if not employees:
                print("\n  ⚠️  هیچ کارمند فعالی در گروه قراردادی یافت نشد")
                return

            print(f"\n  📋 انتخاب کارمند:")
            for i, emp in enumerate(employees, 1):
                print(f"    {i}. {emp.full_name} ({emp.user_id})")

            choice_str = input("\n  انتخاب: ").strip()
            try:
                choice = int(choice_str)
                if choice < 1 or choice > len(employees):
                    print("  ❌ انتخاب نامعتبر")
                    return
            except ValueError:
                print("  ❌ عدد نامعتبر")
                return

            selected_emp = employees[choice - 1]

            # تولید گزارش
            print("\n  ⏳ در حال تولید گزارش...")
            report = generator.generate_detailed_report(selected_emp.user_id, year, month)

            if not report['success']:
                print(f"\n  {report['message']}")
                return

            # نمایش گزارش
            self._display_detailed_report(report)

            # سوال برای خروجی
            print("\n  📤 خروجی:")
            print("    1. اکسل")
            print("    2. PDF")
            print("    3. هر دو")
            print("    0. بدون خروجی")
            export_choice = input("  انتخاب [0-3]: ").strip()

            if export_choice in ['1', '3']:
                from core.excel_detailed_export import DetailedExcelExporter
                exporter = DetailedExcelExporter()
                filename = exporter.export_detailed_report(report)
                print(f"\n  ✅ فایل اکسل: {filename}")

            if export_choice in ['2', '3']:
                from core.pdf_detailed_export import DetailedPDFExporter
                exporter = DetailedPDFExporter()
                filename = exporter.export_detailed_report(report)
                print(f"\n  ✅ فایل PDF: {filename}")

        finally:
            generator.close()

    def _display_detailed_report(self, report: Dict):
        """نمایش گزارش تفصیلی در کنسول"""
        emp = report['employee']
        summary = report['summary']

        print(f"\n{'=' * 180}")
        print(f"  گزارش تفصیلی: {emp['full_name']} ({emp['user_id']})")
        print(f"  {report['month_name']} {report['year']} | گروه قراردادی")
        print(f"{'=' * 180}")

        # جدول روزانه با تراز دقیق
        print(
            "\n  ┌────────────┬──────────┬──────────┬────────────────────┬────────┬────────┬────────────┬────────┬────────┐")
        print(
            "  │ تاریخ      │ روز      │ وضعیت روز│ وضعیت فرد          │ ورود   │ خروج   │ وضعیت تردد│ کارکرد │ اضافه  │")
        print(
            "  ├────────────┼──────────┼──────────┼────────────────────┼────────┼────────┼────────────┼────────┼────────┤")

        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '  --  '

            def fmt_hours(h):
                if h == 0:
                    return '  --  '
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            # وضعیت تردد
            if day['has_incomplete']:
                attendance_str = day['attendance_status'][:10]
            elif day['attendance_status'] == 'بدون تردد':
                attendance_str = '  --  '
            else:
                attendance_str = day['attendance_status'][:10]

            # ✅ تراز دقیق با ljust
            date_str = day['jalali_date'].ljust(10)
            day_name_str = day['day_name'].ljust(8)
            day_status_str = day['day_status'].ljust(8)
            person_status_str = day['person_status_name'].ljust(18)
            enter_str = fmt_time(day['first_enter']).ljust(6)
            exit_str = fmt_time(day['last_exit']).ljust(6)
            attendance_str = attendance_str.ljust(10)
            work_str = fmt_hours(day['work_hours']).ljust(6)
            overtime_str = fmt_hours(day['overtime']).ljust(6)

            print(f"  │ {date_str} │ {day_name_str} │ {day_status_str} │ {person_status_str} │ "
                  f"{enter_str} │ {exit_str} │ {attendance_str} │ {work_str} │ {overtime_str} │")

        print(
            "  └────────────┴──────────┴──────────┴────────────────────┴────────┴────────┴────────────┴────────┴────────┘")

        # خلاصه ماهانه
        print(f"\n{'=' * 180}")
        print(f"  خلاصه ماهانه - {emp['full_name']}")
        print(f"{'=' * 180}")

        def fmt_hours_summary(h):
            hours = int(h)
            minutes = int((h - hours) * 60)
            return f"{hours:03d}:{minutes:02d}"

        print(f"\n  موظفی:")
        print(f"     روزهای موظفی        : {summary['duty_days']} روز")
        print(f"     ساعات موظفی         : {fmt_hours_summary(summary['duty_hours'])} ساعت")

        print(f"\n  وضعیت روزها:")
        print(f"     حضور                : {summary['present_days']} روز")
        print(f"     مرخصی               : {summary['leave_days']} روز")
        print(f"     غیبت                : {summary['absent_days']} روز")
        print(f"     استراحت             : {summary['rest_days']} روز")
        print(f"     جمعه کاری           : {summary['friday_work_days']} روز")

        print(f"\n  ساعات کاری:")
        print(f"     کارکرد ماهانه       : {fmt_hours_summary(summary['total_work_hours'])} ساعت")
        print(f"     ساعات صبح (6-14)    : {fmt_hours_summary(summary['total_morning'])} ساعت")
        print(f"     ساعات عصر (14-22)   : {fmt_hours_summary(summary['total_evening'])} ساعت")
        print(f"     ساعات شب (22-6)     : {fmt_hours_summary(summary['total_night'])} ساعت")

        print(f"\n  اضافه کاری:")
        print(f"     اضافه کاری روزانه   : {fmt_hours_summary(summary['daily_overtime'])} ساعت")
        print(f"     اضافه کاری هفتگی    : {fmt_hours_summary(summary['weekly_overtime'])} ساعت")
        print(f"     جمعه کاری           : {fmt_hours_summary(summary['friday_work_hours'])} ساعت")

        print(f"\n  کسری و اضافی (بدون تهاتر):")
        print(f"     مجموع کسری          : {fmt_hours_summary(summary['deficit'])} ساعت")
        print(f"     مجموع اضافی         : {fmt_hours_summary(summary['surplus'])} ساعت")

        print(f"{'=' * 180}")

    def _show_all_employees_detailed_report(self):
        """نمایش گزارش تفصیلی همه کارمندان"""
        from core.detailed_monthly_report import DetailedMonthlyReportGenerator
        from core.excel_detailed_export import DetailedExcelExporter
        from core.pdf_detailed_export import DetailedPDFExporter

        print("\n" + "=" * 100)
        print("  گزارش تفصیلی همه کارمندان گروه قراردادی")
        print("=" * 100)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = DetailedMonthlyReportGenerator()
        try:
            # دریافت کارمندان گروه قراردادی
            employees = generator.get_employees_by_department('4')

            if not employees:
                print("\n  هیچ کارمند فعالی در گروه قراردادی یافت نشد")
                return

            print(f"\n  تعداد کارمندان: {len(employees)}")
            print("  در حال تولید گزارش برای همه کارمندان...")

            # تولید گزارش برای همه کارمندان
            reports = []
            for i, emp in enumerate(employees, 1):
                print(f"    [{i}/{len(employees)}] {emp.full_name}...")
                report = generator.generate_detailed_report(emp.user_id, year, month)
                if report['success']:
                    reports.append(report)

            print(f"\n  گزارش {len(reports)} کارمند با موفقیت تولید شد")

            if not reports:
                print("\n  هیچ گزارشی تولید نشد")
                return

            # نمایش خلاصه کلی در کنسول
            self._display_all_employees_summary(reports, year, month)

            # سوال برای خروجی
            print("\n  خروجی:")
            print("    1. اکسل")
            print("    2. PDF")
            print("    3. هر دو")
            print("    0. بدون خروجی")
            export_choice = input("  انتخاب [0-3]: ").strip()

            month_name = reports[0]['month_name'] if reports else ''

            if export_choice in ['1', '3']:
                exporter = DetailedExcelExporter()
                filename = exporter.export_all_employees_report(reports, year, month, month_name)
                print(f"\n  فایل اکسل: {filename}")

            if export_choice in ['2', '3']:
                exporter = DetailedPDFExporter()
                filename = exporter.export_all_employees_report(reports, year, month, month_name)
                print(f"\n  فایل PDF: {filename}")

        finally:
            generator.close()

    def _display_all_employees_summary(self, reports: List[Dict], year: int, month: int):
        """نمایش خلاصه کلی همه کارمندان در کنسول"""
        month_name = reports[0]['month_name'] if reports else ''

        print(f"\n{'=' * 180}")
        print(f"  خلاصه گزارش ماهانه - {month_name} {year}")
        print(f"  تعداد کارمندان: {len(reports)}")
        print(f"{'=' * 180}")

        # هدر جدول
        print("\n  ┌──────┬────────┬──────────────────────┬────────┬──────┬──────┬──────┬────────┬────────┬────────┐")
        print("  │ ردیف │ کد     │ نام کامل             │ دپارتمان│موظفی │ حضور │ غیبت │ کارکرد │ اضافی  │ کسری   │")
        print("  ├──────┼────────┼──────────────────────┼────────┼──────┼──────┼──────┼────────┼────────┼────────┤")

        def fmt_hours(h):
            if h == 0:
                return '  --  '
            hours = int(h)
            minutes = int((h - hours) * 60)
            return f"{hours:02d}:{minutes:02d}"

        for i, report in enumerate(reports, 1):
            emp = report['employee']
            summary = report['summary']

            print(f"  │ {i:<4} │ {emp['user_id']:<6} │ {emp['full_name'][:20]:<20} │ {emp['department']:<6} │ "
                  f"{fmt_hours(summary['duty_hours'])} │ {summary['present_days']:<4} │ {summary['absent_days']:<4} │ "
                  f"{fmt_hours(summary['total_work_hours'])} │ {fmt_hours(summary['surplus'])} │ {fmt_hours(summary['deficit'])} │")

        print("  └──────┴────────┴──────────────────────┴────────┴──────┴──────┴──────┴────────┴────────┴────────┘")

        # آمار کلی
        total_work = sum(r['summary']['total_work_hours'] for r in reports)
        total_duty = sum(r['summary']['duty_hours'] for r in reports)
        total_overtime = sum(r['summary']['surplus'] for r in reports)
        total_deficit = sum(r['summary']['deficit'] for r in reports)

        print(f"\n  آمار کلی:")
        print(f"     مجموع کارکرد همه کارمندان : {fmt_hours(total_work)} ساعت")
        print(f"     مجموع موظفی همه کارمندان  : {fmt_hours(total_duty)} ساعت")
        print(f"     مجموع اضافی همه کارمندان  : {fmt_hours(total_overtime)} ساعت")
        print(f"     مجموع کسری همه کارمندان   : {fmt_hours(total_deficit)} ساعت")

        print(f"{'=' * 180}")

    def _get_department_name(self, dept_code: str) -> str:
        """تبدیل کد دپارتمان به نام فارسی"""
        dept_map = {
            '1': 'رسمی',
            '2': 'وظیفه',
            '3': 'خریدخدمت',
            '4': 'قراردادی',
            '5': 'پزشک',
            None: 'بدون گروه',
            '': 'بدون گروه'
        }
        return dept_map.get(str(dept_code), f'گروه {dept_code}')

    def _update_employee_info(self):
        """ویرایش اطلاعات کارمند"""
        from core.employee_manager import EmployeeManager

        print("\n" + "=" * 70)
        print("  ✏️  ویرایش اطلاعات کارمند")
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
                create = input("  آیا می‌خواهید اطلاعات جدید ایجاد کنید؟ (بله/خیر): ").strip()
                if create.lower() in ['بله', 'yes', 'y']:
                    self._add_employee_info()
                return

            # نمایش اطلاعات فعلی
            print("\n" + "-" * 70)
            print("  📋 اطلاعات فعلی:")
            print("-" * 70)
            print(f"     • کد پرسنلی     : {employee.user_id}")
            print(f"     • نام             : {employee.first_name}")
            print(f"     • نام خانوادگی    : {employee.last_name}")
            print(f"     • نام پدر         : {employee.father_name or '-'}")
            print(f"     • کد ملی          : {employee.national_code or '-'}")

            if employee.birth_date:
                j_birth = jdatetime.date.fromgregorian(date=employee.birth_date)
                print(f"     • تاریخ تولد      : {j_birth.strftime('%Y/%m/%d')}")
            else:
                print(f"     • تاریخ تولد      : -")

            print(f"     • جنسیت           : {employee.gender_name}")
            print(f"     • وضعیت تاهل      : {employee.marital_status_name}")
            print(f"     • ایمیل           : {employee.email or '-'}")

            if employee.hire_date:
                j_hire = jdatetime.date.fromgregorian(date=employee.hire_date)
                print(f"     • تاریخ استخدام   : {j_hire.strftime('%Y/%m/%d')}")
            else:
                print(f"     • تاریخ استخدام   : -")

            print(f"     • دپارتمان        : {employee.department or '-'}")
            print(f"     • سمت             : {employee.position or '-'}")
            print(f"     • وضعیت           : {employee.status_name}")
            print(f"     • یادداشت         : {employee.notes or '-'}")
            print("-" * 70)

            # منوی ویرایش
            print("\n  📝 کدام فیلد را می‌خواهید ویرایش کنید؟")
            print("    1. نام")
            print("    2. نام خانوادگی")
            print("    3. نام پدر")
            print("    4. کد ملی")
            print("    5. تاریخ تولد")
            print("    6. جنسیت")
            print("    7. وضعیت تاهل")
            print("    8. ایمیل")
            print("    9. تاریخ استخدام")
            print("    10. دپارتمان")
            print("    11. سمت")
            print("    12. یادداشت")
            print("    0. انصراف")

            field_choice = input("\n  انتخاب [0-12]: ").strip()

            if field_choice == '0':
                print("  ❌ عملیات لغو شد")
                return

            # ویرایش فیلد انتخاب شده
            updated = False

            if field_choice == '1':
                new_value = input(f"  نام جدید [{employee.first_name}]: ").strip()
                if new_value:
                    employee.first_name = new_value
                    updated = True

            elif field_choice == '2':
                new_value = input(f"  نام خانوادگی جدید [{employee.last_name}]: ").strip()
                if new_value:
                    employee.last_name = new_value
                    updated = True

            elif field_choice == '3':
                new_value = input(f"  نام پدر جدید [{employee.father_name or '-'}]: ").strip()
                employee.father_name = new_value if new_value else None
                updated = True

            elif field_choice == '4':
                new_value = input(f"  کد ملی جدید [{employee.national_code or '-'}]: ").strip()
                if new_value:
                    # بررسی تکراری نبودن
                    existing = manager.db.query(Employee).filter(
                        Employee.national_code == new_value,
                        Employee.user_id != user_id
                    ).first()
                    if existing:
                        print(f"  ❌ این کد ملی قبلاً برای {existing.full_name} ثبت شده است")
                        return
                    employee.national_code = new_value
                    updated = True
                else:
                    employee.national_code = None
                    updated = True

            elif field_choice == '5':
                new_value = input(
                    f"  تاریخ تولد جدید (شمسی - مثال: 1370/05/15) [{employee.birth_date or '-'}]: ").strip()
                if new_value:
                    try:
                        j_date = jdatetime.datetime.strptime(new_value, "%Y/%m/%d").date()
                        employee.birth_date = j_date.togregorian()
                        updated = True
                    except Exception as e:
                        print(f"  ❌ خطا در تبدیل تاریخ: {e}")
                        return
                else:
                    employee.birth_date = None
                    updated = True

            elif field_choice == '6':
                print("    M. مرد")
                print("    F. زن")
                new_value = input(f"  جنسیت جدید [{employee.gender or '-'}]: ").strip().upper()
                if new_value in ['M', 'F']:
                    employee.gender = new_value
                    updated = True
                elif new_value:
                    print("  ❌ انتخاب نامعتبر")
                    return

            elif field_choice == '7':
                print("    S. مجرد")
                print("    M. متاهل")
                new_value = input(f"  وضعیت تاهل جدید [{employee.marital_status or '-'}]: ").strip().upper()
                if new_value in ['S', 'M']:
                    employee.marital_status = new_value
                    updated = True
                elif new_value:
                    print("  ❌ انتخاب نامعتبر")
                    return

            elif field_choice == '8':
                new_value = input(f"  ایمیل جدید [{employee.email or '-'}]: ").strip()
                employee.email = new_value if new_value else None
                updated = True

            elif field_choice == '9':
                new_value = input(f"  تاریخ استخدام جدید (شمسی) [{employee.hire_date or '-'}]: ").strip()
                if new_value:
                    try:
                        j_date = jdatetime.datetime.strptime(new_value, "%Y/%m/%d").date()
                        employee.hire_date = j_date.togregorian()
                        updated = True
                    except Exception as e:
                        print(f"  ❌ خطا در تبدیل تاریخ: {e}")
                        return
                else:
                    employee.hire_date = None
                    updated = True

            elif field_choice == '10':
                print("    1. رسمی")
                print("    2. وظیفه")
                print("    3. خریدخدمت")
                print("    4. قراردادی")
                print("    5. پزشک")
                new_value = input(f"  دپارتمان جدید [{employee.department or '-'}]: ").strip()
                if new_value in ['1', '2', '3', '4', '5']:
                    employee.department = new_value
                    updated = True
                elif new_value:
                    print("  ❌ انتخاب نامعتبر")
                    return

            elif field_choice == '11':
                new_value = input(f"  سمت جدید [{employee.position or '-'}]: ").strip()
                employee.position = new_value if new_value else None
                updated = True

            elif field_choice == '12':
                new_value = input(f"  یادداشت جدید [{employee.notes or '-'}]: ").strip()
                employee.notes = new_value if new_value else None
                updated = True

            else:
                print("  ❌ انتخاب نامعتبر")
                return

            if not updated:
                print("  ⚠️  تغییری اعمال نشد")
                return

            # ذخیره تغییرات
            try:
                manager.db.commit()
                print("\n  ✅ اطلاعات کارمند با موفقیت به‌روزرسانی شد")

                # نمایش اطلاعات جدید
                print("\n" + "-" * 70)
                print("  📋 اطلاعات به‌روزرسانی شده:")
                print("-" * 70)
                print(f"     • کد پرسنلی     : {employee.user_id}")
                print(f"     • نام کامل        : {employee.full_name}")
                print(f"     • دپارتمان        : {employee.department or '-'}")
                print(f"     • سمت             : {employee.position or '-'}")
                print(f"     • وضعیت           : {employee.status_name}")
                print("-" * 70)
            except Exception as e:
                manager.db.rollback()
                print(f"\n  ❌ خطا در ذخیره تغییرات: {e}")

        finally:
            manager.close()

    def _approve_all_pending_leaves(self):
        """تایید همه درخواست‌های مرخصی در انتظار به صورت یکجا"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 100)
        print("  ✅ تایید همه درخواست‌های مرخصی در انتظار")
        print("=" * 100)

        manager = LeaveRequestManager()
        try:
            # دریافت لیست درخواست‌های در انتظار
            pending = manager.get_pending_requests()

            if not pending:
                print("\n  ⚠️  هیچ درخواست در انتظاری وجود ندارد")
                return

            # نمایش لیست درخواست‌ها
            print(f"\n  📋 تعداد درخواست‌های در انتظار: {len(pending)}")
            print("\n  ┌──────┬────────┬────────────────────────┬────────────┬────────────┬────────────┬────────┐")
            print("  │ ردیف │ کد     │ نام کامل               │ از تاریخ   │ تا تاریخ   │ نوع مرخصی  │ روزها  │")
            print("  ├──────┼────────┼────────────────────────┼────────────┼────────────┼────────────┼────────┤")

            leave_type_names = {
                'AL': 'استحقاقی',
                'SL': 'استعلاجی',
                'RL': 'تشویقی',
                'UL': 'بدون حقوق'
            }

            for i, req in enumerate(pending, 1):
                # دریافت نام کامل
                full_name = manager.get_employee_name(req.user_id)

                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)

                leave_type = leave_type_names.get(req.leave_type, req.leave_type)

                print(
                    f"  │ {i:<4} │ {req.user_id:<6} │ {full_name[:22]:<22} │ {j_from.strftime('%Y/%m/%d')} │ {j_to.strftime('%Y/%m/%d')} │ {leave_type:<10} │ {req.days_count:<6} │")

            print("  └──────┴────────┴────────────────────────┴────────────┴────────────┴────────────┴────────┘")

            # آمار کلی
            total_days = sum(req.days_count for req in pending)
            print(f"\n  📊 مجموع روزهای مرخصی: {total_days} روز")

            # تایید
            print("\n" + "-" * 100)
            confirm = input("  آیا می‌خواهید همه این درخواست‌ها را تایید کنید؟ (بله/خیر): ").strip()

            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            # تایید همه
            result = manager.approve_all_pending()
            print(f"\n  {result['message']}")

        finally:
            manager.close()

    def _show_detailed_monthly_report_v2(self):
        """نمایش گزارش تفصیلی ماهانه V2 - با ستون‌های متعدد ورود/خروج"""
        from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
        from core.excel_detailed_export_v2 import DetailedExcelExporterV2
        from core.pdf_detailed_export_v2 import DetailedPDFExporterV2

        print("\n" + "=" * 200)
        print("  گزارش تفصیلی ماهانه V2 - گروه قراردادی")
        print("=" * 200)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = DetailedMonthlyReportGeneratorV2()
        try:
            employees = generator.get_employees_by_department('4')

            if not employees:
                print("\n  هیچ کارمند فعالی در گروه قراردادی یافت نشد")
                return

            print(f"\n  انتخاب کارمند:")
            for i, emp in enumerate(employees, 1):
                hire_str = ""
                if emp.hire_date:
                    try:
                        j_hire = jdatetime.date.fromgregorian(date=emp.hire_date)
                        hire_str = f" ({j_hire.strftime('%Y/%m/%d')})"
                    except:
                        pass
                print(f"    {i}. {emp.full_name} ({emp.user_id}){hire_str}")

            choice_str = input("\n  انتخاب: ").strip()
            try:
                choice = int(choice_str)
                if choice < 1 or choice > len(employees):
                    print("  انتخاب نامعتبر")
                    return
            except ValueError:
                print("  عدد نامعتبر")
                return

            selected_emp = employees[choice - 1]

            print("\n  در حال تولید گزارش...")
            report = generator.generate_detailed_report(selected_emp.user_id, year, month)

            if not report['success']:
                print(f"\n  {report['message']}")
                return

            self._display_detailed_report_v2(report)

            print("\n  خروجی:")
            print("    1. اکسل")
            print("    2. PDF")
            print("    3. هر دو")
            print("    0. بدون خروجی")
            export_choice = input("  انتخاب [0-3]: ").strip()

            if export_choice in ['1', '3']:
                exporter = DetailedExcelExporterV2()
                filename = exporter.export_detailed_report(report)
                print(f"\n  فایل اکسل: {filename}")

            if export_choice in ['2', '3']:
                exporter = DetailedPDFExporterV2()
                filename = exporter.export_detailed_report(report)
                print(f"\n  فایل PDF: {filename}")

        finally:
            generator.close()

    def _display_detailed_report_v2(self, report: Dict):
        """نمایش گزارش تفصیلی V2 در کنسول"""
        emp = report['employee']
        summary = report['summary']

        print(f"\n{'=' * 220}")
        print(f"  گزارش تفصیلی V2: {emp['full_name']} ({emp['user_id']})")
        print(f"  {report['month_name']} {report['year']} | گروه قراردادی")
        print(f"{'=' * 220}")

        # جدول روزانه با ستون‌های متعدد
        print(
            "\n  ┌────────────┬──────────┬──────────┬──────────────┬────────┬────────┬────────┬────────┬────────┬────────┬──────────────┬────────┬────────┬────────┐")
        print(
            "  │ تاریخ      │ روز      │ وضعیت روز│ وضعیت فرد    │ ورود۱  │ خروج۱  │ ورود۲  │ خروج۲  │ ورود۳  │ خروج۳  │ وضعیت تردد   │ کارکرد │ اضافی  │ کسری   │")
        print(
            "  ├────────────┼──────────┼──────────┼──────────────┼────────┼────────┼────────┼────────┼────────┼────────┼──────────────┼────────┼────────┼────────┤")

        for day in report['days']:
            def fmt_time(dt):
                return dt.strftime('%H:%M') if dt else '  --  '

            def fmt_hours(h):
                if h == 0:
                    return '  --  '
                hours = int(h)
                minutes = int((h - hours) * 60)
                return f"{hours:02d}:{minutes:02d}"

            # ✅ استخراج جفت‌های ورود/خروج
            pairs = day.get('attendance_pairs', [])
            enter1 = fmt_time(pairs[0]['enter']) if len(pairs) > 0 else '  --  '
            exit1 = fmt_time(pairs[0]['exit']) if len(pairs) > 0 else '  --  '
            enter2 = fmt_time(pairs[1]['enter']) if len(pairs) > 1 else '  --  '
            exit2 = fmt_time(pairs[1]['exit']) if len(pairs) > 1 else '  --  '
            enter3 = fmt_time(pairs[2]['enter']) if len(pairs) > 2 else '  --  '
            exit3 = fmt_time(pairs[2]['exit']) if len(pairs) > 2 else '  --  '

            # وضعیت تردد
            attendance_str = day['attendance_status']
            if attendance_str == 'بدون تردد':
                attendance_str = '  --  '
            attendance_str = attendance_str[:12].ljust(12)

            # وضعیت روز و فرد
            day_status = ('🔴 تعطیل' if day['is_day_off'] else '🟢 کاری').ljust(10)

            person_status_raw = day['person_status_name']
            if person_status_raw == 'حاضر':
                person_status = '✅ حاضر'
            elif person_status_raw == 'مرخصی':
                person_status = '🌴 مرخصی'
            elif person_status_raw == 'استراحت':
                person_status = '🛌 استراحت'
            elif person_status_raw == 'غایب':
                person_status = '❌ غایب'
            elif person_status_raw == 'تعطیل':
                person_status = '🟡 تعطیل'
            elif 'حاضر' in person_status_raw and 'تعطیل' in person_status_raw:
                person_status = '🏢 تعطیل کاری'
            else:
                person_status = person_status_raw
            person_status = person_status[:12].ljust(12)

            print(f"  │ {day['jalali_date']} │ {day['day_name']:<8} │ {day_status} │ {person_status} │ "
                  f"{enter1} │ {exit1} │ {enter2} │ {exit2} │ {enter3} │ {exit3} │ {attendance_str} │ {fmt_hours(day['work_hours'])} │ {fmt_hours(day['surplus'])} │ {fmt_hours(day['deficit'])} │")

        print(
            "  └────────────┴──────────┴──────────┴──────────────┴────────┴────────┴────────┴────────┴────────┴────────┴──────────────┴────────┴────────┴────────┘")

        # خلاصه ماهانه
        print(f"\n{'=' * 220}")
        print(f"  خلاصه ماهانه - {emp['full_name']}")
        print(f"{'=' * 220}")

        def fmt_hours_summary(h):
            hours = int(h)
            minutes = int((h - hours) * 60)
            return f"{hours:03d}:{minutes:02d}"

        print(f"\n  موظفی:")
        print(f"     روزهای موظفی        : {summary['duty_days']} روز")
        print(f"     ساعات موظفی         : {fmt_hours_summary(summary['duty_hours'])} ساعت")

        print(f"\n  وضعیت روزها:")
        print(f"     حضور (کاری عادی)  : {summary['present_days']} روز")
        print(f"     جمعه کاری         : {summary['friday_work_days']} روز")
        print(f"     تعطیل کاری        : {summary['holiday_work_days']} روز")
        print(f"     مرخصی             : {summary['leave_days']} روز")
        print(f"     غیبت              : {summary['absent_days']} روز")
        print(f"     استراحت           : {summary['rest_days']} روز")
        print(f"     تعطیل             : {summary['holiday_days']} روز")

        print(f"\n  ساعات کاری:")
        print(f"     کارکرد ماهانه       : {fmt_hours_summary(summary['total_work_hours'])} ساعت")
        print(f"     ساعات صبح (6-14)    : {fmt_hours_summary(summary['total_morning'])} ساعت")
        print(f"     ساعات عصر (14-22)   : {fmt_hours_summary(summary['total_evening'])} ساعت")
        print(f"     ساعات شب (22-6)     : {fmt_hours_summary(summary['total_night'])} ساعت")

        print(f"\n  اضافه کاری و کسری (مبنای 7:20):")
        print(f"     مجموع اضافی         : {fmt_hours_summary(summary['total_surplus'])} ساعت")
        print(f"     مجموع کسری          : {fmt_hours_summary(summary['total_deficit'])} ساعت")
        print(f"     اضافه کاری هفتگی    : {fmt_hours_summary(summary['weekly_overtime'])} ساعت")
        print(f"     جمعه کاری           : {fmt_hours_summary(summary['friday_work_hours'])} ساعت")

        # ✅ وضعیت کلی - تهاتر اضافی و کسری
        print(f"\n  وضعیت کلی:")
        print(f"     تهاتر اضافی و کسری  : {fmt_hours_summary(abs(summary['net_balance']))} ساعت")
        print(f"     وضعیت نهایی         : {summary['overall_status']}")
        print(f"     مقدار خالص          : {fmt_hours_summary(summary['net_balance_hours'])} ساعت")

        print(f"{'=' * 220}")

    def _show_all_employees_detailed_report_v2(self):
        """نمایش گزارش تفصیلی همه کارمندان V2"""
        from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
        from core.excel_detailed_export_v2 import DetailedExcelExporterV2
        from core.pdf_detailed_export_v2 import DetailedPDFExporterV2

        print("\n" + "=" * 150)
        print("  گزارش تفصیلی همه کارمندان V2 - گروه قراردادی")
        print("=" * 150)

        today_j = jdatetime.date.today()
        year_str = input(f"\n  سال شمسی [پیش‌فرض: {today_j.year}]: ").strip()
        year = int(year_str) if year_str else today_j.year

        month_str = input(f"  ماه (1-12) [پیش‌فرض: {today_j.month}]: ").strip()
        month = int(month_str) if month_str else today_j.month

        generator = DetailedMonthlyReportGeneratorV2()
        try:
            employees = generator.get_employees_by_department('4')

            if not employees:
                print("\n  هیچ کارمند فعالی در گروه قراردادی یافت نشد")
                return

            print(f"\n  تعداد کارمندان: {len(employees)}")
            print("  در حال تولید گزارش برای همه کارمندان...")

            reports = []
            for i, emp in enumerate(employees, 1):
                print(f"    [{i}/{len(employees)}] {emp.full_name}...")
                report = generator.generate_detailed_report(emp.user_id, year, month)
                if report['success']:
                    reports.append(report)

            print(f"\n  گزارش {len(reports)} کارمند با موفقیت تولید شد")

            if not reports:
                print("\n  هیچ گزارشی تولید نشد")
                return

            self._display_all_employees_summary_v2(reports, year, month)

            print("\n  خروجی:")
            print("    1. اکسل")
            print("    2. PDF")
            print("    3. هر دو")
            print("    0. بدون خروجی")
            export_choice = input("  انتخاب [0-3]: ").strip()

            month_name = reports[0]['month_name'] if reports else ''

            if export_choice in ['1', '3']:
                exporter = DetailedExcelExporterV2()
                filename = exporter.export_all_employees_report(reports, year, month, month_name)
                print(f"\n  فایل اکسل: {filename}")

            if export_choice in ['2', '3']:
                exporter = DetailedPDFExporterV2()
                filename = exporter.export_all_employees_report(reports, year, month, month_name)
                print(f"\n  فایل PDF: {filename}")

        finally:
            generator.close()

    def _display_all_employees_summary_v2(self, reports: List[Dict], year: int, month: int):
        """نمایش خلاصه کلی همه کارمندان V2"""
        month_name = reports[0]['month_name'] if reports else ''

        print(f"\n{'=' * 200}")
        print(f"  خلاصه گزارش ماهانه V2 - {month_name} {year}")
        print(f"  تعداد کارمندان: {len(reports)}")
        print(f"{'=' * 200}")

        print("\n  ┌──────┬────────┬──────────────────────┬────────┬──────┬──────┬──────┬────────┬────────┬────────┐")
        print("  │ ردیف │ کد     │ نام کامل             │ دپارتمان│موظفی │ حضور │ غیبت │ کارکرد │ اضافی  │ کسری   │")
        print("  ├──────┼────────┼──────────────────────┼────────┼──────┼──────┼──────┼────────┼────────┼────────┤")

        def fmt_hours(h):
            if h == 0:
                return '  --  '
            hours = int(h)
            minutes = int((h - hours) * 60)
            return f"{hours:02d}:{minutes:02d}"

        for i, report in enumerate(reports, 1):
            emp = report['employee']
            summary = report['summary']

            print(f"  │ {i:<4} │ {emp['user_id']:<6} │ {emp['full_name'][:20]:<20} │ {emp['department']:<6} │ "
                  f"{fmt_hours(summary['duty_hours'])} │ {summary['present_days']:<4} │ {summary['absent_days']:<4} │ "
                  f"{fmt_hours(summary['total_work_hours'])} │ {fmt_hours(summary['total_surplus'])} │ {fmt_hours(summary['total_deficit'])} │")

        print("  └──────┴────────┴──────────────────────┴────────┴──────┴──────┴──────┴────────┴────────┴────────┘")

    def _admin_delete_leave_request(self):
        """حذف درخواست مرخصی توسط مدیر"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 120)
        print("  🗑️ حذف درخواست مرخصی (مدیر)")
        print("=" * 120)

        manager = LeaveRequestManager()
        try:
            # فیلتر اختیاری
            print("\n  🔍 فیلتر:")
            print("    1. همه درخواست‌ها")
            print("    2. بر اساس کد پرسنلی")
            print("    3. بر اساس وضعیت")
            filter_choice = input("  انتخاب [1-3] [پیش‌فرض: 1]: ").strip() or '1'

            user_filter = None
            status_filter = None

            if filter_choice == '2':
                user_filter = input("  کد پرسنلی: ").strip()
            elif filter_choice == '3':
                print("    P. در انتظار")
                print("    A. تایید شده")
                print("    R. رد شده")
                print("    C. لغو شده")
                status_filter = input("  وضعیت [P/A/R/C]: ").strip().upper()

            # دریافت لیست درخواست‌ها
            if user_filter:
                requests = manager.get_all_requests(user_filter)
            elif status_filter:
                requests = manager.db.query(LeaveRequest).filter(
                    LeaveRequest.status == status_filter
                ).order_by(LeaveRequest.from_date.desc()).all()
            else:
                requests = manager.get_all_requests()

            if not requests:
                print("\n  ⚠️ هیچ درخواستی یافت نشد")
                return

            # نمایش لیست
            leave_type_names = {
                'AL': 'استحقاقی',
                'SL': 'استعلاجی',
                'RL': 'تشویقی',
                'UL': 'بدون حقوق'
            }

            status_names = {
                'P': '⏳ در انتظار',
                'A': '✅ تایید شده',
                'R': '❌ رد شده',
                'C': '🚫 لغو شده'
            }

            print(f"\n  📋 تعداد درخواست‌ها: {len(requests)}")
            print(
                "\n  ┌──────┬──────┬────────┬────────────────────────┬────────────┬────────────┬────────────┬────────┐")
            print("  │ ردیف │ ID   │ کد     │ نام کامل               │ از تاریخ   │ تا تاریخ   │ نوع مرخصی  │ وضعیت  │")
            print("  ├──────┼──────┼────────┼────────────────────────┼────────────┼────────────┼────────────┼────────┤")

            for i, req in enumerate(requests, 1):
                full_name = manager.get_employee_name(req.user_id)
                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)
                leave_type = leave_type_names.get(req.leave_type, req.leave_type)
                status = status_names.get(req.status, req.status)

                print(
                    f"  │ {i:<4} │ {req.id:<4} │ {req.user_id:<6} │ {full_name[:22]:<22} │ {j_from.strftime('%Y/%m/%d')} │ {j_to.strftime('%Y/%m/%d')} │ {leave_type:<10} │ {status:<6} │")

            print("  └──────┴──────┴────────┴────────────────────────┴────────────┴────────────┴────────────┴────────┘")

            # انتخاب برای حذف
            print("\n" + "-" * 120)
            choice_str = input("  شماره ردیف برای حذف (یا 0 برای انصراف): ").strip()

            try:
                choice = int(choice_str)
                if choice == 0:
                    print("  ❌ عملیات لغو شد")
                    return
                if choice < 1 or choice > len(requests):
                    print("  ❌ شماره نامعتبر")
                    return
            except ValueError:
                print("  ❌ عدد نامعتبر")
                return

            selected = requests[choice - 1]

            # نمایش جزئیات و تایید
            print("\n" + "-" * 120)
            print("  📋 جزئیات درخواست:")
            print(f"     • ID              : {selected.id}")
            print(f"     • کد پرسنلی       : {selected.user_id}")
            print(f"     • نام             : {manager.get_employee_name(selected.user_id)}")
            print(
                f"     • از تاریخ        : {jdatetime.date.fromgregorian(date=selected.from_date).strftime('%Y/%m/%d')}")
            print(
                f"     • تا تاریخ        : {jdatetime.date.fromgregorian(date=selected.to_date).strftime('%Y/%m/%d')}")
            print(f"     • نوع مرخصی       : {leave_type_names.get(selected.leave_type, selected.leave_type)}")
            print(f"     • تعداد روز       : {selected.days_count}")
            print(f"     • وضعیت           : {status_names.get(selected.status, selected.status)}")
            print(f"     • دلیل            : {selected.reason or '-'}")

            print("\n  ⚠️  هشدار: این عملیات غیرقابل بازگشت است!")
            confirm = input("  آیا مطمئن هستید؟ (بله/خیر): ").strip()

            if confirm.lower() not in ['بله', 'yes', 'y']:
                print("  ❌ عملیات لغو شد")
                return

            # حذف
            result = manager.delete_leave_request(selected.id)
            print(f"\n  {result['message']}")

            if result['success']:
                info = result['info']
                print(f"\n  📋 اطلاعات حذف شده:")
                print(f"     • کد پرسنلی       : {info['user_id']}")
                print(
                    f"     • از تاریخ        : {jdatetime.date.fromgregorian(date=info['from_date']).strftime('%Y/%m/%d')}")
                print(
                    f"     • تا تاریخ        : {jdatetime.date.fromgregorian(date=info['to_date']).strftime('%Y/%m/%d')}")
                print(f"     • تعداد روز       : {info['days_count']}")

        finally:
            manager.close()

    def _show_all_leave_requests(self):
        """نمایش همه درخواست‌های مرخصی (برای مدیر)"""
        from core.leave_request_manager import LeaveRequestManager

        print("\n" + "=" * 120)
        print("  📋 مشاهده همه درخواست‌های مرخصی")
        print("=" * 120)

        manager = LeaveRequestManager()
        try:
            # فیلتر
            print("\n  🔍 فیلتر:")
            print("    1. همه درخواست‌ها")
            print("    2. بر اساس کد پرسنلی")
            print("    3. بر اساس وضعیت")
            filter_choice = input("  انتخاب [1-3] [پیش‌فرض: 1]: ").strip() or '1'

            user_filter = None
            status_filter = None

            if filter_choice == '2':
                user_filter = input("  کد پرسنلی: ").strip()
            elif filter_choice == '3':
                print("    P. در انتظار")
                print("    A. تایید شده")
                print("    R. رد شده")
                print("    C. لغو شده")
                status_filter = input("  وضعیت [P/A/R/C]: ").strip().upper()

            # دریافت لیست
            if user_filter:
                requests = manager.get_all_requests(user_filter)
            elif status_filter:
                requests = manager.db.query(LeaveRequest).filter(
                    LeaveRequest.status == status_filter
                ).order_by(LeaveRequest.from_date.desc()).all()
            else:
                requests = manager.get_all_requests()

            if not requests:
                print("\n  ⚠️ هیچ درخواستی یافت نشد")
                return

            # نمایش
            leave_type_names = {
                'AL': 'استحقاقی',
                'SL': 'استعلاجی',
                'RL': 'تشویقی',
                'UL': 'بدون حقوق'
            }

            status_names = {
                'P': '⏳ در انتظار',
                'A': '✅ تایید شده',
                'R': '❌ رد شده',
                'C': '🚫 لغو شده'
            }

            print(f"\n  📋 تعداد درخواست‌ها: {len(requests)}")
            print(
                "\n  ┌──────┬────────┬────────────────────────┬────────────┬────────────┬────────────┬────────┬────────────────┐")
            print(
                "  │ ID   │ کد     │ نام کامل               │ از تاریخ   │ تا تاریخ   │ نوع مرخصی  │ وضعیت  │ دلیل           │")
            print(
                "  ├──────┼────────┼────────────────────────┼────────────┼────────────┼────────────┼────────┼────────────────┤")

            for req in requests:
                full_name = manager.get_employee_name(req.user_id)
                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                j_to = jdatetime.date.fromgregorian(date=req.to_date)
                leave_type = leave_type_names.get(req.leave_type, req.leave_type)
                status = status_names.get(req.status, req.status)
                reason = (req.reason or '-')[:14]

                print(
                    f"  │ {req.id:<4} │ {req.user_id:<6} │ {full_name[:22]:<22} │ {j_from.strftime('%Y/%m/%d')} │ {j_to.strftime('%Y/%m/%d')} │ {leave_type:<10} │ {status:<6} │ {reason:<14} │")

            print(
                "  └──────┴────────┴────────────────────────┴────────────┴────────────┴────────────┴────────┴────────────────┘")

            # آمار
            status_counts = {}
            for req in requests:
                status_counts[req.status] = status_counts.get(req.status, 0) + 1

            print(f"\n  📊 آمار:")
            for status, count in sorted(status_counts.items()):
                print(f"     • {status_names.get(status, status)}: {count} درخواست")

            total_days = sum(req.days_count for req in requests if req.status == 'A')
            print(f"\n  📅 مجموع روزهای مرخصی تایید شده: {total_days} روز")

        finally:
            manager.close()