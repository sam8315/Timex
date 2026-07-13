from zk import ZK
from typing import List, Dict, Optional
from datetime import datetime
import jdatetime


class DeviceManager:
    """مدیریت ارتباط با دستگاه حضور و غیاب"""

    def __init__(self, ip: str, port: int = 4370, timeout: int = 30):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.zk = ZK(ip, port=port, timeout=timeout)
        self.conn = None
        self._device_info = {}

    def connect(self) -> bool:
        """برقراری اتصال با دستگاه"""
        try:
            self.conn = self.zk.connect()
            return True
        except Exception as e:
            print(f"❌ خطا در اتصال: {e}")
            return False

    def disconnect(self):
        """قطع اتصال"""
        if self.conn:
            try:
                self.conn.disconnect()
                self.conn = None
            except:
                pass

    def _ensure_connected(self) -> bool:
        """اطمینان از برقراری اتصال"""
        if not self.conn:
            print("❌ ابتدا باید به دستگاه متصل شوید")
            return False
        return True

    # ============================================
    # اطلاعات دستگاه
    # ============================================

    def get_device_info(self) -> Dict:
        """دریافت اطلاعات کامل دستگاه"""
        if not self._ensure_connected():
            return {}

        info = {'ip': self.ip, 'port': self.port}

        methods = [
            ('time', 'get_time', lambda x: str(x)),
            ('serial', 'get_serialnumber', lambda x: x),
            ('platform', 'get_platform', lambda x: x),
            ('firmware', 'get_firmware_version', lambda x: x),
        ]

        for key, method_name, converter in methods:
            try:
                method = getattr(self.conn, method_name)
                info[key] = converter(method())
            except Exception as e:
                info[key] = f"خطا: {e}"

        self._device_info = info
        return info

    # ============================================
    # مدیریت کاربران
    # ============================================

    def get_users(self) -> List[Dict]:
        """دریافت لیست کاربران"""
        if not self._ensure_connected():
            return []

        try:
            users = self.conn.get_users()
            return [
                {
                    'uid': u.uid,
                    'user_id':u.user_id,
                    'name': u.name,
                    'password':u.password,
                    'card': u.card,
                    'group_id': u.group_id,
                    'privilege': u.privilege
                }
                for u in users
            ]
        except Exception as e:
            print(f"❌ خطا در دریافت کاربران: {e}")
            return []

    def find_user(self, user_id: int) -> Optional[Dict]:
        """پیدا کردن کاربر بر اساس USER_ID"""
        users = self.get_users()
        for user in users:
            if user['user_id'] == str(user_id):
                return user
        return None

    def find_user_by_personnel_code(self, code: str) -> Optional[Dict]:
        """
        جستجوی کاربر بر اساس کد پرسنلی (نام کاربر)

        Args:
            code: کد پرسنلی (مثال: NN-6925, A.H, KH.JOKAR)

        Returns:
            Dict: اطلاعات کاربر یا None
        """
        users = self.get_users()

        # جستجوی دقیق
        for user in users:
            if user['name'].upper() == code.upper():
                return user

        # جستجوی تقریبی (اگر دقیق پیدا نشد)
        for user in users:
            if code.upper() in user['name'].upper():
                return user

        return None

    def search_users(self, query: str) -> List[Dict]:
        """
        جستجوی چندگانه کاربران بر اساس کد پرسنلی

        Args:
            query: عبارت جستجو

        Returns:
            List[Dict]: لیست کاربران منطبق
        """
        users = self.get_users()
        results = []

        query_upper = query.upper()

        for user in users:
            if query_upper in user['name'].upper():
                results.append(user)

        return results
    # ============================================
    # مدیریت رکوردهای تردد
    # ============================================

    def get_attendance(self) -> List[Dict]:
        """دریافت رکوردهای تردد"""
        if not self._ensure_connected():
            return []

        try:
            attendance = self.conn.get_attendance()
            return [
                {
                    'user_id': a.user_id,
                    'timestamp': a.timestamp,
                    'status': a.status,
                    'punch': a.punch
                }
                for a in attendance
            ]
        except Exception as e:
            print(f"❌ خطا در دریافت رکوردها: {e}")
            return []

    def get_attendance_by_date(self, date_str: str) -> List[Dict]:
        """دریافت رکوردهای یک روز خاص (فرمت: 1405/04/17)"""
        try:
            jdate = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            records = self.get_attendance()
            return [
                r for r in records
                if r['timestamp'].date() == jdate
            ]
        except Exception as e:
            print(f"❌ خطا در فیلتر تاریخ: {e}")
            return []

    def clear_attendance(self) -> bool:
        """پاک کردن رکوردهای تردد از دستگاه"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.clear_attendance()
            return True
        except Exception as e:
            print(f"❌ خطا در پاک کردن رکوردها: {e}")
            return False

    # ============================================
    # تنظیمات دستگاه
    # ============================================

    def sync_time(self) -> bool:
        """همگام‌سازی زمان دستگاه با سرور"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.set_time(datetime.now())
            return True
        except Exception as e:
            print(f"❌ خطا در همگام‌سازی زمان: {e}")
            return False

    def enable_device(self) -> bool:
        """فعال‌سازی دستگاه (خروج از حالت قفل)"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.enable_device()
            return True
        except Exception as e:
            print(f"❌ خطا: {e}")
            return False

    def disable_device(self, timeout: int = 10) -> bool:
        """قفل کردن دستگاه (برای انجام تنظیمات)"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.disable_device(timeout=timeout)
            return True
        except Exception as e:
            print(f"❌ خطا: {e}")
            return False

    def restart(self) -> bool:
        """ریستارت دستگاه"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.restart()
            return True
        except Exception as e:
            print(f"❌ خطا: {e}")
            return False
