"""
اسکریپت یکبار مصرف برای غیرفعال کردن کارمندانی که در یک ماه اخیر تردد نداشته‌اند
"""
from datetime import date, timedelta
from sqlalchemy import and_, func
from database.engine import SessionLocal
from models.employee import Employee
from models.attendance import Attendance
import jdatetime


def deactivate_inactive_employees():
    """غیرفعال کردن کارمندان بدون تردد در یک ماه اخیر"""
    print("=" * 70)
    print("  🔄 غیرفعال کردن کارمندان بدون تردد اخیر")
    print("=" * 70)

    db = SessionLocal()

    try:
        # ✅ تاریخ امروز
        today = date.today()
        one_month_ago = today - timedelta(days=30)

        j_today = jdatetime.date.fromgregorian(date=today)
        j_one_month_ago = jdatetime.date.fromgregorian(date=one_month_ago)

        print(f"\n  📅 تاریخ امروز: {j_today.strftime('%Y/%m/%d')}")
        print(f"  📅 یک ماه قبل: {j_one_month_ago.strftime('%Y/%m/%d')}")

        # 1. دریافت تمام کارمندان فعال
        active_employees = db.query(Employee).filter(Employee.is_active == True).all()
        print(f"\n  📊 تعداد کارمندان فعال: {len(active_employees)}")

        if not active_employees:
            print("  ✅ هیچ کارمند فعالی وجود ندارد")
            return

        # 2. پیدا کردن کاربرانی که در یک ماه اخیر تردد داشته‌اند
        users_with_attendance = db.query(Attendance.user_id).filter(
            and_(
                func.date(Attendance.timestamp) >= one_month_ago,
                func.date(Attendance.timestamp) <= today,
                Attendance.is_deleted == False
            )
        ).distinct().all()

        users_with_attendance_set = set(u[0] for u in users_with_attendance)
        print(f"  📊 کاربران دارای تردد در یک ماه اخیر: {len(users_with_attendance_set)}")

        # 3. پیدا کردن کارمندانی که باید غیرفعال شوند
        to_deactivate = []
        for emp in active_employees:
            if emp.user_id not in users_with_attendance_set:
                to_deactivate.append(emp)

        print(f"  📊 کارمندانی که غیرفعال می‌شوند: {len(to_deactivate)}")

        if not to_deactivate:
            print("\n  ✅ همه کارمندان فعال در یک ماه اخیر تردد داشته‌اند")
            return

        # 4. نمایش لیست
        print("\n  📋 لیست کارمندانی که غیرفعال می‌شوند:")
        print("  " + "-" * 70)
        print(f"  {'#':<4} {'کد':<8} {'نام کامل':<25} {'دپارتمان':<15} {'آخرین تردد':<12}")
        print("  " + "-" * 70)

        for i, emp in enumerate(to_deactivate, 1):
            # پیدا کردن آخرین تردد
            last_attendance = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == emp.user_id,
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp.desc()).first()

            if last_attendance:
                j_last = jdatetime.date.fromgregorian(date=last_attendance.timestamp.date())
                last_str = j_last.strftime('%Y/%m/%d')
            else:
                last_str = "بدون تردد"

            print(f"  {i:<4} {emp.user_id:<8} {emp.full_name[:23]:<25} {emp.department or '-':<15} {last_str:<12}")

        print("  " + "-" * 70)

        # 5. تایید
        confirm = input(
            f"\n  ⚠️  آیا مطمئن هستید که می‌خواهید {len(to_deactivate)} کارمند را غیرفعال کنید؟ (بله/خیر): ").strip()
        if confirm.lower() not in ['بله', 'yes', 'y']:
            print("  ❌ عملیات لغو شد")
            return

        # 6. غیرفعال کردن
        print("\n  💾 در حال غیرفعال کردن...")
        deactivated_count = 0
        errors = 0

        for emp in to_deactivate:
            try:
                emp.is_active = False
                emp.termination_date = today
                emp.termination_reason = "عدم تردد در یک ماه اخیر"
                deactivated_count += 1
            except Exception as e:
                print(f"  ❌ خطا در غیرفعال کردن {emp.user_id}: {e}")
                errors += 1

        # Commit
        db.commit()

        # 7. نمایش آمار
        print("\n" + "=" * 70)
        print("  📊 آمار:")
        print("=" * 70)
        print(f"  • کل کارمندان فعال (قبل)  : {len(active_employees)}")
        print(f"  • دارای تردد اخیر         : {len(users_with_attendance_set)}")
        print(f"  • غیرفعال شده             : {deactivated_count} ✅")
        print(f"  • خطاها                   : {errors}")
        print("=" * 70)

        # 8. آمار نهایی
        final_active = db.query(Employee).filter(Employee.is_active == True).count()
        final_inactive = db.query(Employee).filter(Employee.is_active == False).count()

        print(f"\n  📊 وضعیت نهایی:")
        print(f"     • فعال     : {final_active}")
        print(f"     • غیرفعال  : {final_inactive}")

        print("\n✅ عملیات کامل شد!")

    except Exception as e:
        db.rollback()
        print(f"\n❌ خطای کلی: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    deactivate_inactive_employees()