"""
اسکریپت یکبار مصرف برای انتقال اطلاعات کاربران از جدول person (MySQL)
به جدول employee (PostgreSQL)
فقط نام و فامیل منتقل می‌شود
"""
import pymysql
from sqlalchemy import and_
from config.settings import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER,
    MYSQL_PASSWORD, MYSQL_DB
)
from database.engine import SessionLocal
from models.employee import Employee
from models.user import User


def migrate_person():
    """انتقال داده‌های person به employee"""
    print("=" * 70)
    print("  🔄 انتقال اطلاعات کاربران از person به employee")
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
                           SELECT Perno, Name, Family
                           FROM person
                           ORDER BY Perno
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

    stats = {
        'total': len(records),
        'migrated': 0,
        'skipped_no_user': 0,
        'skipped_exists': 0,
        'skipped_no_name': 0,
        'errors': 0
    }

    print("\n💾 در حال انتقال داده‌ها...")

    try:
        for i, record in enumerate(records, 1):
            perno = str(record['Perno']).strip()
            first_name = (record.get('Name') or '').strip()
            last_name = (record.get('Family') or '').strip()

            # بررسی وجود نام و فامیل
            if not first_name and not last_name:
                print(f"  ⚠️  کاربر {perno} نام و فامیل ندارد")
                stats['skipped_no_name'] += 1
                continue

            # بررسی وجود کاربر در جدول users
            user = db.query(User).filter(User.user_id == perno).first()
            if not user:
                print(f"  ⚠️  کاربر {perno} در جدول users یافت نشد")
                stats['skipped_no_user'] += 1
                continue

            # بررسی وجود در employee
            existing = db.query(Employee).filter(Employee.user_id == perno).first()
            if existing:
                stats['skipped_exists'] += 1
                continue

            # ایجاد رکورد employee
            try:
                employee = Employee(
                    user_id=perno,
                    first_name=first_name or '-',
                    last_name=last_name or '-'
                )
                db.add(employee)
                stats['migrated'] += 1

                if i % 50 == 0:
                    db.commit()
                    print(f"  ✅ ذخیره شد: {i}/{stats['total']}")

            except Exception as e:
                db.rollback()
                print(f"  ❌ خطا در Perno {perno}: {e}")
                stats['errors'] += 1

        # Commit نهایی
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"\n❌ خطای کلی: {e}")
        stats['errors'] += 1
    finally:
        db.close()

    # نمایش آمار
    print("\n" + "=" * 70)
    print("  📊 آمار انتقال:")
    print("=" * 70)
    print(f"  • کل رکوردها              : {stats['total']}")
    print(f"  • منتقل شده               : {stats['migrated']} ✅")
    print(f"  • رد شده (بدون نام)       : {stats['skipped_no_name']}")
    print(f"  • رد شده (کاربر نبود)     : {stats['skipped_no_user']}")
    print(f"  • رد شده (قبلاً ثبت شده)  : {stats['skipped_exists']}")
    print(f"  • خطاها                   : {stats['errors']}")
    print("=" * 70)

    print("\n✅ انتقال کامل شد!")


if __name__ == "__main__":
    confirm = input("⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
    if confirm.lower() in ['بله', 'yes', 'y']:
        migrate_person()
    else:
        print("❌ عملیات لغو شد")