"""
اسکریپت debug برای بررسی مشکل درخواست مرخصی
"""
from datetime import date
from database.engine import SessionLocal
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.user import User
import jdatetime


def debug_leave_request():
    """بررسی مشکل درخواست مرخصی"""
    print("=" * 70)
    print("  🔍 Debug: بررسی مشکل درخواست مرخصی")
    print("=" * 70)

    db = SessionLocal()

    user_id = '3274'

    # 1. بررسی مانده مرخصی
    print(f"\n📊 بررسی مانده مرخصی کاربر {user_id}:")

    # سال شمسی 1405
    jalali_year = 1405
    print(f"\n  🔹 جستجو با سال شمسی {jalali_year}:")

    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == jalali_year,
        LeaveBalance.leave_type == 'AL'
    ).first()

    if balance:
        print(f"     ✅ مانده یافت شد: {balance.balance} روز")
    else:
        print(f"     ❌ مانده یافت نشد!")

    # سال میلادی 2026 (معادل 1405)
    gregorian_year = 2026
    print(f"\n  🔹 جستجو با سال میلادی {gregorian_year}:")

    balance = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user_id,
        LeaveBalance.year == gregorian_year,
        LeaveBalance.leave_type == 'AL'
    ).first()

    if balance:
        print(f"     ✅ مانده یافت شد: {balance.balance} روز")
    else:
        print(f"     ❌ مانده یافت نشد!")

    # 2. نمایش تمام مانده‌های کاربر
    print(f"\n📋 تمام مانده‌های کاربر {user_id}:")
    balances = db.query(LeaveBalance).filter(LeaveBalance.user_id == user_id).all()

    if not balances:
        print("  ❌ هیچ مانده‌ای وجود ندارد")
    else:
        for b in balances:
            print(f"     • سال {b.year} | نوع {b.leave_type} | مانده {b.balance}")

    # 3. تست تبدیل تاریخ
    print("\n" + "=" * 70)
    print("  🧪 تست تبدیل تاریخ")
    print("=" * 70)

    test_date_str = "1405/04/28"
    print(f"\n  تاریخ شمسی: {test_date_str}")

    try:
        j_date = jdatetime.datetime.strptime(test_date_str, "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        print(f"  ✅ تبدیل موفق:")
        print(f"     شمسی: {j_date}")
        print(f"     میلادی: {g_date}")
        print(f"     سال شمسی: {j_date.year}")
        print(f"     سال میلادی: {g_date.year}")

        # تبدیل برعکس
        j_back = jdatetime.date.fromgregorian(date=g_date)
        print(f"     تبدیل برعکس: {j_back} (سال: {j_back.year})")

    except Exception as e:
        print(f"  ❌ خطا: {e}")

    # 4. بررسی درخواست‌های موجود
    print("\n" + "=" * 70)
    print(f"  📜 درخواست‌های مرخصی کاربر {user_id}")
    print("=" * 70)

    requests = db.query(LeaveRequest).filter(LeaveRequest.user_id == user_id).all()

    if not requests:
        print("  ❌ هیچ درخواستی وجود ندارد")
    else:
        for req in requests:
            j_from = jdatetime.date.fromgregorian(date=req.from_date)
            print(f"\n  ID: {req.id}")
            print(f"     از تاریخ: {req.from_date} (شمسی: {j_from})")
            print(f"     تا تاریخ: {req.to_date}")
            print(f"     نوع: {req.leave_type}")
            print(f"     روز: {req.days_count}")
            print(f"     وضعیت: {req.status}")

    db.close()


if __name__ == "__main__":
    debug_leave_request()