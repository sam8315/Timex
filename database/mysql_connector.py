"""
اتصال به دیتابیس MySQL قدیمی و خواندن داده‌های تردد
"""
import pymysql
from typing import List, Dict, Optional
from config.settings import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER,
    MYSQL_PASSWORD, MYSQL_DB
)


class MySQLConnector:
    """مدیریت اتصال به MySQL قدیمی"""

    def __init__(self):
        self.connection: Optional[pymysql.connections.Connection] = None

    def connect(self) -> bool:
        """برقراری اتصال به MySQL"""
        try:
            self.connection = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            return True
        except Exception as e:
            print(f"❌ خطا در اتصال به MySQL: {e}")
            return False

    def disconnect(self):
        """قطع اتصال"""
        if self.connection:
            try:
                self.connection.close()
                self.connection = None
            except:
                pass

    def _ensure_connected(self) -> bool:
        """اطمینان از اتصال"""
        if not self.connection:
            print("❌ ابتدا باید به MySQL متصل شوید")
            return False
        return True

    def test_connection(self) -> bool:
        """تست اتصال با یک کوئری ساده"""
        if not self._ensure_connected():
            return False
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            print(f"❌ خطا در تست اتصال: {e}")
            return False

    def get_ioinfo_records(
            self,
            limit: Optional[int] = None,
            from_date: Optional[str] = None
    ) -> List[Dict]:
        """
        خواندن رکوردهای جدول ioinfo

        Args:
            limit: محدود کردن تعداد رکوردها (برای تست)
            from_date: فقط رکوردهای بعد از این تاریخ شمسی 
                      (مثال: 1405/04/17) - برای Sync تدریجی

        Returns:
            List[Dict]: لیست رکوردها
        """
        if not self._ensure_connected():
            return []

        try:
            query = "SELECT Perno, EnterDate, EnterTime, ExitDate, ExitTime FROM ioinfo"
            params = []

            conditions = []
            if from_date:
                # فیلتر بر اساس تاریخ ورود
                conditions.append("EnterDate >= %s")
                params.append(from_date)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY EnterDate ASC, EnterTime ASC"

            if limit:
                query += f" LIMIT {limit}"

            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()

        except Exception as e:
            print(f"❌ خطا در خواندن رکوردها از MySQL: {e}")
            return []

    def get_unique_personnel(self) -> List[int]:
        """دریافت لیست کدهای پرسنلی منحصر به فرد"""
        if not self._ensure_connected():
            return []

        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT DISTINCT Perno FROM ioinfo ORDER BY Perno")
                return [row['Perno'] for row in cursor.fetchall()]
        except Exception as e:
            print(f"❌ خطا در دریافت لیست پرسنل: {e}")
            return []

    def get_record_count(self) -> int:
        """دریافت تعداد کل رکوردها"""
        if not self._ensure_connected():
            return 0

        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as cnt FROM ioinfo")
                result = cursor.fetchone()
                return result['cnt'] if result else 0
        except Exception as e:
            print(f"❌ خطا در شمارش رکوردها: {e}")
            return 0