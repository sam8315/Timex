"""
اسکریپت روزانه: پایان وضعیت «در حال تحصیل» برای بستگان با study_end_date گذشته.

فقط is_studying=False می‌کند؛ رکورد فعال می‌ماند و status تأیید عوض نمی‌شود.
زمان‌بندی پیشنهادی: Windows Task Scheduler / cron.
"""
from datetime import date

import jdatetime

from database.engine import SessionLocal
from web.services.employee_relative_service import expire_ended_studies


def main() -> None:
    today = date.today()
    today_j = jdatetime.date.fromgregorian(date=today)
    print("=" * 70)
    print("  انقضای وضعیت تحصیل بستگان")
    print("=" * 70)
    print(f"\n  تاریخ امروز: {today_j.strftime('%Y/%m/%d')} ({today.isoformat()})")

    db = SessionLocal()
    try:
        updated = expire_ended_studies(db, as_of=today)
        print(f"  تعداد به‌روزرسانی‌شده: {updated}")
        if updated == 0:
            print("  موردی برای انقضا نبود")
        else:
            print("  is_studying برای موارد منقضی روی false تنظیم شد")
    finally:
        db.close()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
