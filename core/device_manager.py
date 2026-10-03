from zk import ZK
from typing import List, Dict, Optional
from datetime import datetime
import logging
import time
import jdatetime

logger = logging.getLogger(__name__)


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
            logger.warning(
                "Device connection failed: %s",
                type(e).__name__,
                extra={"event": "device.offline", "device_id": self.ip},
            )
            return False

    def disconnect(self):
        """قطع اتصال"""
        if self.conn:
            try:
                self.conn.disconnect()
                self.conn = None
            except Exception:
                pass

    def _ensure_connected(self) -> bool:
        """اطمینان از برقراری اتصال"""
        if not self.conn:
            logger.warning(
                "Device is not connected",
                extra={"event": "device.offline", "device_id": self.ip},
            )
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
        except Exception:
            logger.exception(
                "Failed to fetch users from device",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
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
            logger.debug(
                "Attendance records received count=%s",
                len(attendance),
                extra={"event": "attendance.received", "device_id": self.ip},
            )
            return [
                {
                    'user_id': a.user_id,
                    'timestamp': a.timestamp,
                    'status': a.status,
                    'punch': a.punch
                }
                for a in attendance
            ]
        except Exception:
            logger.exception(
                "Failed to fetch attendance records",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
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
        except Exception:
            logger.exception(
                "Failed to filter attendance by date",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return []

    def clear_attendance(self) -> bool:
        """پاک کردن رکوردهای تردد از دستگاه"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.clear_attendance()
            return True
        except Exception:
            logger.exception(
                "Failed to clear attendance on device",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return False

    def sync_attendance_to_db(self, dry_run_first: bool = True) -> Dict:
        """
        Synchronize attendance records from the device to the database
        """
        from database.engine import SessionLocal
        from models.attendance import Attendance
        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy.exc import SQLAlchemyError

        started = time.perf_counter()
        logger.info(
            "Attendance synchronization started",
            extra={"event": "sync.started", "device_id": self.ip},
        )
        stats = {
            'total_fetched': 0,
            'new_records': 0,
            'inserted': 0,
            'skipped_duplicates': 0,
            'errors': 0,
            'last_db_record': None,
            'first_device_record': None,
            'time_gap': None
        }

        def _duration_ms() -> int:
            return int((time.perf_counter() - started) * 1000)

        def _log_sync_completed(message: str, level: int = logging.INFO) -> None:
            logger.log(
                level,
                "%s fetched=%s inserted=%s duplicates=%s errors=%s",
                message,
                stats['total_fetched'],
                stats['inserted'],
                stats['skipped_duplicates'],
                stats['errors'],
                extra={
                    "event": "sync.completed",
                    "device_id": self.ip,
                    "duration_ms": _duration_ms(),
                },
            )

        # Step 1: Connect to the device
        logger.debug(
            "Sync step 1: connecting to device",
            extra={"event": "sync.started", "device_id": self.ip},
        )

        was_connected = self.conn is not None
        if not was_connected:
            logger.info(
                "Device was not connected; attempting connect",
                extra={"event": "sync.started", "device_id": self.ip},
            )
            if not self.connect():
                stats['duration_ms'] = _duration_ms()
                logger.error(
                    "Could not establish connection to device",
                    extra={
                        "event": "sync.failed",
                        "device_id": self.ip,
                        "duration_ms": stats['duration_ms'],
                    },
                )
                return {'error': '❌ Could not establish connection to device'}
            logger.info(
                "Device successfully connected",
                extra={"event": "device.reconnected", "device_id": self.ip},
            )
        else:
            logger.debug(
                "Device was already connected",
                extra={"event": "sync.started", "device_id": self.ip},
            )

        try:
            # Step 2: Get the latest record from the database
            logger.debug(
                "Sync step 2: checking latest record in database",
                extra={"event": "sync.started", "device_id": self.ip},
            )

            db = SessionLocal()
            try:
                # ✅ Only records with source D (Device) or A (API)
                last_record = db.query(Attendance).filter(
                    Attendance.source.in_(['D', 'A'])
                ).order_by(
                    Attendance.timestamp.desc()
                ).first()

                if last_record:
                    stats['last_db_record'] = last_record.timestamp
                    logger.debug(
                        "Latest DB record timestamp=%s user_id=%s",
                        last_record.timestamp,
                        last_record.user_id,
                        extra={
                            "event": "sync.started",
                            "device_id": self.ip,
                            "user_id": last_record.user_id,
                        },
                    )
                else:
                    stats['last_db_record'] = None
                    logger.debug(
                        "Database has no prior device/API attendance records",
                        extra={"event": "sync.started", "device_id": self.ip},
                    )
            finally:
                db.close()

            # Step 3: Get records from the device
            logger.debug(
                "Sync step 3: reading attendance records from device",
                extra={"event": "sync.started", "device_id": self.ip},
            )

            device_attendance = self.conn.get_attendance()
            stats['total_fetched'] = len(device_attendance)
            logger.info(
                "Found %s records on device",
                len(device_attendance),
                extra={"event": "attendance.received", "device_id": self.ip},
            )

            if stats['total_fetched'] == 0:
                stats['duration_ms'] = _duration_ms()
                _log_sync_completed("No records found on device")
                return stats

            # Step 4: Find the first unsynchronized record
            logger.debug(
                "Sync step 4: checking unsynchronized records",
                extra={"event": "sync.started", "device_id": self.ip},
            )

            # Sort device records by time
            device_attendance_sorted = sorted(device_attendance, key=lambda x: x.timestamp)

            if stats['last_db_record']:
                # Remove timezone for comparison
                last_db_timestamp = stats['last_db_record']
                if last_db_timestamp.tzinfo is not None:
                    last_db_timestamp = last_db_timestamp.replace(tzinfo=None)

                # Find the first record newer than the latest database record
                first_new_record = None
                for record in device_attendance_sorted:
                    record_time = record.timestamp
                    if record_time.tzinfo is not None:
                        record_time = record_time.replace(tzinfo=None)

                    if record_time > last_db_timestamp:
                        first_new_record = record
                        break

                if first_new_record:
                    stats['first_device_record'] = first_new_record.timestamp
                    stats['new_records'] = sum(
                        1 for r in device_attendance_sorted
                        if (r.timestamp.replace(tzinfo=None) if r.timestamp.tzinfo else r.timestamp) > last_db_timestamp
                    )

                    # Calculate time difference
                    record_time = first_new_record.timestamp
                    if record_time.tzinfo is not None:
                        record_time = record_time.replace(tzinfo=None)
                    time_gap = record_time - last_db_timestamp
                    stats['time_gap'] = time_gap

                    logger.debug(
                        "First unsynchronized record timestamp=%s user_id=%s new_records=%s time_gap=%s",
                        first_new_record.timestamp,
                        first_new_record.user_id,
                        stats['new_records'],
                        time_gap,
                        extra={
                            "event": "sync.started",
                            "device_id": self.ip,
                            "user_id": first_new_record.user_id,
                        },
                    )
                else:
                    stats['duration_ms'] = _duration_ms()
                    _log_sync_completed("All records are synchronized", level=logging.DEBUG)
                    return stats
            else:
                # Database is empty, all records are new
                stats['first_device_record'] = device_attendance_sorted[0].timestamp
                stats['new_records'] = len(device_attendance_sorted)
                logger.debug(
                    "Database empty; treating all device records as new count=%s",
                    stats['new_records'],
                    extra={"event": "sync.started", "device_id": self.ip},
                )

            # Step 5: DRY RUN
            if dry_run_first:
                logger.info(
                    "Dry-run sync (no changes)",
                    extra={"event": "sync.started", "device_id": self.ip},
                )

                dry_stats = self._dry_run_sync(device_attendance_sorted, stats['last_db_record'])

                logger.info(
                    "Dry-run results would_insert=%s would_skip_duplicate=%s would_skip_old=%s total_skipped=%s",
                    dry_stats['would_insert'],
                    dry_stats['would_skip_duplicate'],
                    dry_stats['would_skip_old'],
                    dry_stats['total_skipped'],
                    extra={"event": "sync.started", "device_id": self.ip},
                )

                # Ask for confirmation (interactive CLI path; keep input())
                confirm = input("  Do you want to proceed with actual synchronization? (yes/no): ").strip()

                if confirm.lower() not in ['yes', 'y']:
                    stats['duration_ms'] = _duration_ms()
                    logger.info(
                        "Sync operation cancelled by operator",
                        extra={
                            "event": "sync.completed",
                            "device_id": self.ip,
                            "duration_ms": stats['duration_ms'],
                        },
                    )
                    return stats

            # Step 6: Actual execution
            logger.debug(
                "Sync step 6: saving to database",
                extra={"event": "sync.started", "device_id": self.ip},
            )

            db = SessionLocal()
            batch_size = 200

            for i, record in enumerate(device_attendance_sorted, 1):
                # Remove timezone for comparison
                record_time = record.timestamp
                if record_time.tzinfo is not None:
                    record_time = record_time.replace(tzinfo=None)

                # Process only new records
                if stats['last_db_record']:
                    last_db_timestamp = stats['last_db_record']
                    if last_db_timestamp.tzinfo is not None:
                        last_db_timestamp = last_db_timestamp.replace(tzinfo=None)
                    if record_time <= last_db_timestamp:
                        continue

                try:
                    user_id_str = str(record.user_id)

                    stmt = insert(Attendance).values(
                        user_id=user_id_str,
                        timestamp=record.timestamp,
                        status=record.status if record.status is not None else 0,
                        punch=record.punch if record.punch is not None else 0,
                        source=Attendance.SOURCE_DEVICE
                    ).on_conflict_do_nothing(
                        index_elements=['user_id', 'timestamp']
                    )

                    result = db.execute(stmt)

                    if result.rowcount > 0:
                        stats['inserted'] += 1
                    else:
                        stats['skipped_duplicates'] += 1

                    # Batch commit
                    if i % batch_size == 0 or i == len(device_attendance_sorted):
                        db.commit()
                        logger.debug(
                            "Batch saved %s/%s",
                            i,
                            len(device_attendance_sorted),
                            extra={"event": "sync.started", "device_id": self.ip},
                        )

                except SQLAlchemyError as e:
                    db.rollback()
                    logger.warning(
                        "Error on record index=%s user_id=%s error=%s",
                        i,
                        record.user_id,
                        type(e).__name__,
                        extra={
                            "event": "sync.failed",
                            "device_id": self.ip,
                            "user_id": str(record.user_id),
                        },
                    )
                    stats['errors'] += 1

            db.close()
            logger.debug(
                "Attendance synchronization write phase completed",
                extra={"event": "sync.completed", "device_id": self.ip},
            )

        except Exception:
            logger.exception(
                "General error during attendance synchronization",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            stats['errors'] += 1

        finally:
            # Step 7: Disconnect
            logger.debug(
                "Sync step 7: disconnecting from device",
                extra={"event": "sync.completed", "device_id": self.ip},
            )

            if self.conn and hasattr(self.conn, 'disconnect'):
                try:
                    self.disconnect()
                    logger.debug(
                        "Disconnected from device",
                        extra={"event": "sync.completed", "device_id": self.ip},
                    )
                except Exception as e:
                    logger.warning(
                        "Error during disconnection: %s",
                        type(e).__name__,
                        extra={"event": "sync.failed", "device_id": self.ip},
                    )

        stats['duration_ms'] = _duration_ms()
        _log_sync_completed("Attendance synchronization finished")
        logger.debug(
            "Sync detail last_db=%s first_new=%s time_gap=%s",
            stats['last_db_record'],
            stats['first_device_record'],
            stats['time_gap'],
            extra={
                "event": "sync.completed",
                "device_id": self.ip,
                "duration_ms": stats['duration_ms'],
            },
        )

        return stats

    def _dry_run_sync(self, device_attendance: List, last_db_timestamp) -> Dict:
        """
        DRY RUN: بررسی رکوردها بدون ذخیره
        """
        from database.engine import SessionLocal
        from models.attendance import Attendance
        from sqlalchemy import and_

        would_insert = 0
        would_skip_duplicate = 0  # ✅ رکوردهای تکراری در دیتابیس
        would_skip_old = 0  # ✅ رکوردهای قدیمی (قبل از آخرین رکورد)

        # ✅ حذف timezone برای مقایسه
        if last_db_timestamp and last_db_timestamp.tzinfo is not None:
            last_db_timestamp = last_db_timestamp.replace(tzinfo=None)

        db = SessionLocal()
        try:
            for record in device_attendance:
                # ✅ حذف timezone از رکورد دستگاه
                record_time = record.timestamp
                if record_time.tzinfo is not None:
                    record_time = record_time.replace(tzinfo=None)

                # ✅ بررسی رکوردهای قدیمی
                if last_db_timestamp and record_time <= last_db_timestamp:
                    would_skip_old += 1
                    continue

                # ✅ بررسی رکوردهای تکراری در دیتابیس
                existing = db.query(Attendance).filter(
                    and_(
                        Attendance.user_id == str(record.user_id),
                        Attendance.timestamp == record.timestamp
                    )
                ).first()

                if existing:
                    would_skip_duplicate += 1
                else:
                    would_insert += 1

        finally:
            db.close()

        return {
            'would_insert': would_insert,
            'would_skip_duplicate': would_skip_duplicate,
            'would_skip_old': would_skip_old,
            'total_skipped': would_skip_duplicate + would_skip_old
        }

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
        except Exception:
            logger.exception(
                "Failed to sync device time",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return False

    def enable_device(self) -> bool:
        """فعال‌سازی دستگاه (خروج از حالت قفل)"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.enable_device()
            return True
        except Exception:
            logger.exception(
                "Failed to enable device",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return False

    def disable_device(self, timeout: int = 10) -> bool:
        """قفل کردن دستگاه (برای انجام تنظیمات)"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.disable_device(timeout=timeout)
            return True
        except Exception:
            logger.exception(
                "Failed to disable device",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return False

    def restart(self) -> bool:
        """ریستارت دستگاه"""
        if not self._ensure_connected():
            return False

        try:
            self.conn.restart()
            return True
        except Exception:
            logger.exception(
                "Failed to restart device",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            return False

    def sync_users_to_db(self) -> Dict:
        """
        خواندن کاربران از دستگاه و ذخیره در دیتابیس
        """
        from database.engine import SessionLocal
        from models.user import User
        from sqlalchemy.exc import SQLAlchemyError

        if not self._ensure_connected():
            return {'error': 'اتصال برقرار نیست'}

        stats = {
            'total_users': 0,
            'new_users': 0,
            'updated_users': 0,
            'errors': 0
        }

        started = time.perf_counter()
        logger.info(
            "User synchronization started",
            extra={"event": "sync.started", "device_id": self.ip},
        )

        try:
            device_users = self.conn.get_users()
            stats['total_users'] = len(device_users)
            logger.info(
                "Fetched %s users from device",
                len(device_users),
                extra={"event": "sync.started", "device_id": self.ip},
            )

            db = SessionLocal()
            logger.debug(
                "Saving users to database",
                extra={"event": "sync.started", "device_id": self.ip},
            )

            for i, device_user in enumerate(device_users, 1):
                try:
                    # تبدیل user_id به String
                    user_id_str = str(device_user.user_id)

                    existing_user = db.query(User).filter(User.user_id == user_id_str).first()

                    if existing_user:
                        existing_user.name = device_user.name
                        existing_user.card = device_user.card
                        # existing_user.group_id = device_user.group_id     #گروه کابر نباید تغییر کند
                        existing_user.privilege = device_user.privilege
                        stats['updated_users'] += 1
                    else:
                        new_user = User(
                            user_id=user_id_str,  # ✅ استفاده از user_id (نه uid)
                            name=device_user.name,
                            card=device_user.card,
                            group_id=device_user.group_id,
                            privilege=device_user.privilege
                        )
                        db.add(new_user)
                        stats['new_users'] += 1

                    if i % 50 == 0 or i == len(device_users):
                        db.commit()
                        logger.debug(
                            "User batch saved %s/%s",
                            i,
                            len(device_users),
                            extra={"event": "sync.started", "device_id": self.ip},
                        )

                except SQLAlchemyError as e:
                    db.rollback()
                    logger.warning(
                        "Error syncing user_id=%s error=%s",
                        device_user.user_id,
                        type(e).__name__,
                        extra={
                            "event": "sync.failed",
                            "device_id": self.ip,
                            "user_id": str(device_user.user_id),
                        },
                    )
                    stats['errors'] += 1

            db.close()
            logger.debug(
                "User synchronization write phase completed",
                extra={"event": "sync.completed", "device_id": self.ip},
            )

        except Exception:
            logger.exception(
                "General error during user synchronization",
                extra={"event": "sync.failed", "device_id": self.ip},
            )
            stats['errors'] += 1

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "User sync finished total=%s new=%s updated=%s errors=%s",
            stats['total_users'],
            stats['new_users'],
            stats['updated_users'],
            stats['errors'],
            extra={
                "event": "sync.completed",
                "device_id": self.ip,
                "duration_ms": duration_ms,
            },
        )

        return stats
