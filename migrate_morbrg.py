"""
اسکریپت یکبار مصرف برای انتقال داده‌های جدول morbrg از MySQL به PostgreSQL
"""
import pymysql
from datetime import date, timedelta
from sqlalchemy import and_
from config.settings import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER,
    MYSQL_PASSWORD, MYSQL_DB
)
from database.engine import SessionLocal
from models.leave_request import LeaveRequest
from models.daily_status import DailyStatus
from models.user import User
from core.holiday_manager import HolidayManager
import jdatetime

# نگاشت Type قدیمی به leave_type جدید
TYPE_MAPPING = {
    2: 'AL',  # مرخصی استحقاقی
    4: 'SL',  # مرخصی استعلاجی
    8: 'M',  # مأموریت
}


def calculate_working_days(from_date: date, to_date: date, holiday_manager: HolidayManager) -> int:
    """محاسبه تعداد روزهای کاری بین دو تاریخ"""
    days = 0
    current = from_date
    while current <= to_date:
        # جمعه نیست و تعطیل نیست
        if current.weekday() != 4 and not holiday_manager.is_holiday(current):
            days += 1
        current += timedelta(days=1)
    return days


def jalali_to_gregorian(jalali_str: str) -> date:
    """تبدیل تاریخ شمسی به میلادی"""
    j_date = jdatetime.datetime.strptime(jalali_str, "%Y/%m/%d").date()
    return j_date.togregorian()


def migrate_morbrg():
    """انتقال داده‌های morbrg"""
    print("=" * 70)
    print("  🔄 انتقال داده‌های جدول morbrg")
    print("=" * 70)

    # اتصال به MySQL
    print("\n🔌 در حال اتصال به MySQL...")
    try:
        mysql_conn = pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        print("✅ اتصال به MySQL برقرار شد")
    except Exception as e:
        print(f"❌ خطا در اتصال به MySQL: {e}")
        return

    # خواندن رکوردها
    print("\n📖 در حال خواندن رکوردها...")
    try:
        with mysql_conn.cursor() as cursor:
            cursor.execute("""
                           SELECT BrgNo,
                                  Perno,
                                  BeginDate,
                                  EndDate,
                                  BeginTime,
                                  EndTime,
                                  RequestDate,
                                  Type,
                                  Description
                           FROM morbrg
                           ORDER BY BrgNo
                           """)
            records = cursor.fetchall()
        print(f"✅ تعداد {len(records)} رکورد یافت شد")
    except Exception as e:
        print(f"❌ خطا در خواندن رکوردها: {e}")
        mysql_conn.close()
        return

    mysql_conn.close()

    # اتصال به PostgreSQL
    print("\n🔌 در حال اتصال به PostgreSQL...")
    db = SessionLocal()
    holiday_manager = HolidayManager()

    stats = {
        'total': len(records),
        'migrated': 0,
        'skipped_no_user': 0,
        'skipped_invalid_type': 0,
        'skipped_duplicate': 0,
        'errors': 0,
        'daily_statuses_created': 0
    }

    print("\n💾 در حال انتقال داده‌ها...")

    try:
        for i, record in enumerate(records, 1):
            perno = str(record['Perno'])
            brg_no = record['BrgNo']
            begin_date_str = record['BeginDate']
            end_date_str = record['EndDate']
            req_date_str = record['RequestDate']
            type_code = record['Type']
            description = record['Description'] or ''

            # بررسی وجود کاربر
            user = db.query(User).filter(User.user_id == perno).first()
            if not user:
                print(f"  ⚠️  کاربر {perno} یافت نشد (BrgNo: {brg_no})")
                stats['skipped_no_user'] += 1
                continue

            # نگاشت نوع
            leave_type = TYPE_MAPPING.get(type_code)
            if not leave_type:
                print(f"  ⚠️  نوع ناشناخته {type_code} (BrgNo: {brg_no})")
                stats['skipped_invalid_type'] += 1
                continue

            # تبدیل تاریخ‌ها
            try:
                begin_date = jalali_to_gregorian(begin_date_str)
                end_date = jalali_to_gregorian(end_date_str)
                request_date = jalali_to_gregorian(req_date_str)
            except Exception as e:
                print(f"  ⚠️  خطا در تبدیل تاریخ (BrgNo: {brg_no}): {e}")
                stats['errors'] += 1
                continue

            # محاسبه تعداد روزهای کاری
            days_count = calculate_working_days(begin_date, end_date, holiday_manager)

            if days_count == 0:
                print(f"  ⚠️  هیچ روز کاری در بازه نیست (BrgNo: {brg_no})")
                stats['skipped_duplicate'] += 1
                continue

            # بررسی تکراری نبودن
            existing = db.query(LeaveRequest).filter(
                and_(
                    LeaveRequest.user_id == perno,
                    LeaveRequest.from_date == begin_date,
                    LeaveRequest.to_date == end_date,
                    LeaveRequest.leave_type == leave_type
                )
            ).first()

            if existing:
                stats['skipped_duplicate'] += 1
                continue

            # ایجاد درخواست مرخصی
            try:
                leave_request = LeaveRequest(
                    user_id=perno,
                    leave_type=leave_type,
                    from_date=begin_date,
                    to_date=end_date,
                    days_count=days_count,
                    reason=f"[انتقال از سیستم قدیمی - BrgNo: {brg_no}] {description}".strip(),
                    status='A',  # تایید شده (چون قدیمی است)
                    approved_by='migration',
                    approved_at=request_date
                )
                db.add(leave_request)
                db.flush()  # برای دریافت ID

                # ایجاد daily_statuses برای هر روز کاری
                current = begin_date
                while current <= end_date:
                    if current.weekday() != 4 and not holiday_manager.is_holiday(current):
                        # بررسی وجود وضعیت قبلی
                        existing_status = db.query(DailyStatus).filter(
                            and_(
                                DailyStatus.user_id == perno,
                                DailyStatus.status_date == current
                            )
                        ).first()

                        if not existing_status:
                            daily_status = DailyStatus(
                                user_id=perno,
                                status_date=current,
                                status_code=leave_type,
                                description=f"انتقال از morbrg (BrgNo: {brg_no})",
                                leave_request_id=leave_request.id
                            )
                            db.add(daily_status)
                            stats['daily_statuses_created'] += 1

                    current += timedelta(days=1)

                stats['migrated'] += 1

                if i % 50 == 0:
                    db.commit()
                    print(f"  ✅ ذخیره شد: {i}/{stats['total']}")

            except Exception as e:
                db.rollback()
                print(f"  ❌ خطا در BrgNo {brg_no}: {e}")
                stats['errors'] += 1

        # Commit نهایی
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"\n❌ خطای کلی: {e}")
        stats['errors'] += 1
    finally:
        db.close()
        holiday_manager.close()

    # نمایش آمار
    print("\n" + "=" * 70)
    print("  📊 آمار انتقال:")
    print("=" * 70)
    print(f"  • کل رکوردها              : {stats['total']}")
    print(f"  • منتقل شده               : {stats['migrated']} ✅")
    print(f"  • رد شده (کاربر نبود)     : {stats['skipped_no_user']}")
    print(f"  • رد شده (نوع نامعتبر)    : {stats['skipped_invalid_type']}")
    print(f"  • رد شده (تکراری)         : {stats['skipped_duplicate']}")
    print(f"  • خطاها                   : {stats['errors']}")
    print(f"  • وضعیت‌های روزانه ایجاد شده: {stats['daily_statuses_created']}")
    print("=" * 70)

    print("\n✅ انتقال کامل شد!")
    print("💡 نکته: مانده مرخصی کسر نشد (داده‌های قدیمی هستند)")


if __name__ == "__main__":
    confirm = input("⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
    if confirm.lower() in ['بله', 'yes', 'y']:
        migrate_morbrg()
    else:
        print("❌ عملیات لغو شد")