"""
اسکریپت تشخیص مشکل "بدون تردد" با وجود تردد
"""
import sys
import os
from datetime import date, datetime
from sqlalchemy import and_, func
import jdatetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.engine import SessionLocal
from models.attendance import Attendance
from models.daily_status import DailyStatus
from core.daily_status_manager import DailyStatusManager


def debug_attendance(user_id: str, target_date: date):
    """تشخیص مشکل تردد یک کاربر در یک تاریخ"""
    db = SessionLocal()

    print("\n" + "=" * 80)
    print(f"  🔍 تشخیص مشکل تردد")
    print(f"  👤 کاربر: {user_id}")
    print(f"  📅 تاریخ: {target_date}")
    print("=" * 80)

    try:
        # ۱. بررسی رکوردهای Attendance
        print("\n  📊 مرحله ۱: بررسی رکوردهای Attendance")

        # query اصلی (همان query در get_daily_report)
        attendances = db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == target_date,
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).all()

        print(f"     • تعداد رکوردهای یافت شده: {len(attendances)}")

        if not attendances:
            print("     ❌ هیچ رکوردی یافت نشد!")

            # بررسی بدون فیلتر is_deleted
            all_attendances = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == user_id,
                    func.date(Attendance.timestamp) == target_date
                )
            ).all()

            print(f"     • تعداد رکوردها (بدون فیلتر is_deleted): {len(all_attendances)}")

            if all_attendances:
                print("     ⚠️  رکوردها وجود دارند ولی is_deleted = True است!")
                for a in all_attendances:
                    print(f"        - ID: {a.id}, Time: {a.timestamp}, Punch: {a.punch}, Deleted: {a.is_deleted}")
        else:
            print("     ✅ رکوردها یافت شدند:")
            enters = [a for a in attendances if a.punch == 0]
            exits = [a for a in attendances if a.punch == 1]

            print(f"        • ورودها: {len(enters)}")
            print(f"        • خروج‌ها: {len(exits)}")

            for a in attendances:
                punch_name = "ورود" if a.punch == 0 else "خروج"
                print(f"        - ID: {a.id}, Time: {a.timestamp}, Punch: {punch_name}")

        # ۲. بررسی DailyStatus
        print("\n  📊 مرحله ۲: بررسی DailyStatus")

        daily_status = db.query(DailyStatus).filter(
            and_(
                DailyStatus.user_id == user_id,
                DailyStatus.status_date == target_date
            )
        ).first()

        if daily_status:
            print(f"     • وضعیت: {daily_status.status_code}")
            print(f"     • منبع: {daily_status.source}")
            print(f"     • leave_request_id: {daily_status.leave_request_id}")
        else:
            print("     ⚠️  هیچ DailyStatus ثبت نشده است")

        # ۳. تست detect_status
        print("\n  📊 مرحله ۳: تست detect_status")

        manager = DailyStatusManager()
        try:
            status_info = manager.detect_status(user_id, target_date)
            print(f"     • وضعیت تشخیص داده شده: {status_info['status']}")
            print(f"     • منبع: {status_info['source']}")
            print(f"     • توضیحات: {status_info.get('description', '-')}")
        finally:
            manager.close()

        # ۴. بررسی روز قبل و بعد
        print("\n  📊 مرحله ۴: بررسی روز قبل و بعد (برای تردد شبانه)")

        from datetime import timedelta
        prev_day = target_date - timedelta(days=1)
        next_day = target_date + timedelta(days=1)

        prev_attendances = db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == prev_day,
                Attendance.is_deleted == False
            )
        ).all()

        next_attendances = db.query(Attendance).filter(
            and_(
                Attendance.user_id == user_id,
                func.date(Attendance.timestamp) == next_day,
                Attendance.is_deleted == False
            )
        ).all()

        print(f"     • روز قبل ({prev_day}): {len(prev_attendances)} رکورد")
        print(f"     • روز بعد ({next_day}): {len(next_attendances)} رکورد")

        if prev_attendances:
            prev_enters = [a for a in prev_attendances if a.punch == 0]
            prev_exits = [a for a in prev_attendances if a.punch == 1]
            print(f"        - ورود: {len(prev_enters)}, خروج: {len(prev_exits)}")

            # بررسی خروج دیر وقت
            late_exits = [e for e in prev_exits if e.timestamp.hour >= 22]
            if late_exits:
                print(f"        ⚠️  {len(late_exits)} خروج دیر وقت (بعد از 22:00)")

        if next_attendances:
            next_enters = [a for a in next_attendances if a.punch == 0]
            next_exits = [a for a in next_attendances if a.punch == 1]
            print(f"        - ورود: {len(next_enters)}, خروج: {len(next_exits)}")

            # بررسی ورود زود وقت
            early_enters = [e for e in next_enters if e.timestamp.hour < 8]
            if early_enters:
                print(f"        ⚠️  {len(early_enters)} ورود زود وقت (قبل از 08:00)")

    finally:
        db.close()


def main():
    """تابع اصلی"""
    user_id = input("\n  📛 کد پرسنلی کاربر: ").strip()
    if not user_id:
        print("  ❌ کد پرسنلی نمی‌تواند خالی باشد")
        return

    date_str = input("  📅 تاریخ (شمسی - مثال: 1405/04/18): ").strip()
    if not date_str:
        print("  ❌ تاریخ نمی‌تواند خالی باشد")
        return

    try:
        j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
        target_date = j_date.togregorian()
    except Exception as e:
        print(f"  ❌ خطا در تبدیل تاریخ: {e}")
        return

    debug_attendance(user_id, target_date)


if __name__ == '__main__':
    main()