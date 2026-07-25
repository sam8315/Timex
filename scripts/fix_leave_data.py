"""
اسکریپت پر کردن سه جدول بر اساس leave_requests
پیش‌نیاز:
  1. سه جدول leave_balances, leave_transactions, daily_statuses پاک شده باشند
  2. مرخصی از طریق قرارداد شارژ شده باشد
"""
import sys
import os
from datetime import date, timedelta, datetime
from typing import Dict
from sqlalchemy import and_
import jdatetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.engine import SessionLocal
from models.leave_request import LeaveRequest
from models.daily_status import DailyStatus
from core.leave_manager import LeaveManager
from core.holiday_manager import HolidayManager


class LeaveRebuilder:
    """پر کردن سه جدول از leave_requests"""

    def __init__(self, dry_run: bool = True):
        self.db = SessionLocal()
        self.leave_manager = LeaveManager()
        self.holiday_manager = HolidayManager()
        self.dry_run = dry_run
        self.log = []

    def close(self):
        if self.db:
            self.db.close()
        if self.leave_manager:
            self.leave_manager.close()
        if self.holiday_manager:
            self.holiday_manager.close()

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        self.log.append(line)
        print(line)

    def save_log(self, filename: str = "rebuild_leave_log.txt"):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.log))
        print(f"\n✅ لاگ ذخیره شد: {filename}")

    def rebuild(self) -> Dict:
        """
        فقط دو کار انجام می‌دهد:
        1. ایجاد DailyStatus برای روزهای کاری هر درخواست تایید شده
        2. فراخوانی debit_leave برای کسر از مانده و ثبت تراکنش
        """
        self._log("=" * 70)
        self._log("  پر کردن سه جدول از leave_requests")
        mode = "DRY RUN" if self.dry_run else "LIVE"
        self._log(f"  حالت: {mode}")
        self._log("=" * 70)

        # دریافت همه درخواست‌های تایید شده به ترتیب تاریخ
        requests = self.db.query(LeaveRequest).filter(
            LeaveRequest.status == 'A'
        ).order_by(LeaveRequest.from_date, LeaveRequest.id).all()

        self._log(f"\n📊 تعداد درخواست‌های تایید شده: {len(requests)}")

        stats = {
            'total': len(requests),
            'processed': 0,
            'daily_status_created': 0,
            'debit_done': 0,
            'errors': 0,
            'error_details': []
        }

        for req in requests:
            # تبدیل تاریخ به شمسی
            try:
                j_from = jdatetime.date.fromgregorian(date=req.from_date)
                jalali_year = j_from.year
            except Exception as e:
                self._log(f"  ❌ درخواست {req.id}: خطا در تبدیل تاریخ: {e}")
                stats['errors'] += 1
                continue

            self._log(f"\n📋 درخواست {req.id} | کاربر {req.user_id} | "
                      f"{req.from_date} تا {req.to_date} | "
                      f"{req.leave_type} | {req.days_count} روز | سال {jalali_year}")

            # ─── ۱. ایجاد DailyStatus ───
            ds_count = 0
            current = req.from_date
            while current <= req.to_date:
                # فقط روزهای کاری
                is_friday = current.weekday() == 4
                is_holiday = self.holiday_manager.is_holiday(current)

                if not is_friday and not is_holiday:
                    # بررسی تکراری نبودن
                    existing = self.db.query(DailyStatus).filter(
                        and_(
                            DailyStatus.user_id == req.user_id,
                            DailyStatus.status_date == current
                        )
                    ).first()

                    if not existing:
                        if not self.dry_run:
                            ds = DailyStatus(
                                user_id=req.user_id,
                                status_date=current,
                                status_code=req.leave_type,
                                leave_request_id=req.id
                            )
                            self.db.add(ds)
                        ds_count += 1

                current += timedelta(days=1)

            stats['daily_status_created'] += ds_count
            self._log(f"   📅 DailyStatus: {ds_count} روز")

            # ─── ۲. کسر از مانده + ثبت تراکنش ───
            if not self.dry_run:
                result = self.leave_manager.debit_leave(
                    user_id=req.user_id,
                    year=jalali_year,
                    leave_type=req.leave_type,
                    amount=req.days_count,
                    description=f'بازسازی - درخواست {req.id}',
                    reference_id=req.id
                )

                if result['success']:
                    self._log(f"   💳 DEBIT: {result['message']}")
                    stats['debit_done'] += 1
                else:
                    self._log(f"   ❌ DEBIT: {result['message']}")
                    stats['errors'] += 1
                    stats['error_details'].append(
                        f"درخواست {req.id} کاربر {req.user_id}: {result['message']}"
                    )
            else:
                self._log(f"   🔍 [DRY RUN] کسر {req.days_count} روز {req.leave_type}")
                stats['debit_done'] += 1

            stats['processed'] += 1

        # ذخیره DailyStatus‌ها
        if not self.dry_run:
            try:
                self.db.commit()
                self._log("\n✅ تغییرات ذخیره شد")
            except Exception as e:
                self.db.rollback()
                self._log(f"\n❌ خطا در ذخیره: {e}")
                stats['errors'] += 1

        # ─── خلاصه ───
        self._log("\n" + "=" * 70)
        self._log("  خلاصه")
        self._log("=" * 70)
        self._log(f"  درخواست‌های پردازش شده : {stats['processed']} از {stats['total']}")
        self._log(f"  DailyStatus ایجاد شده  : {stats['daily_status_created']}")
        self._log(f"  DEBIT انجام شده        : {stats['debit_done']}")
        self._log(f"  خطاها                  : {stats['errors']}")

        if stats['error_details']:
            self._log("\n  ⚠️ جزئیات خطاها:")
            for err in stats['error_details']:
                self._log(f"     • {err}")

        if self.dry_run:
            self._log("\n💡 برای اجرای واقعی:")
            self._log("   python scripts/rebuild_leave_from_requests.py --apply")

        return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='پر کردن سه جدول از leave_requests'
    )
    parser.add_argument('--apply', action='store_true',
                        help='اجرای واقعی')
    parser.add_argument('--log-file', type=str,
                        default='rebuild_leave_log.txt')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  🔧 پر کردن سه جدول از leave_requests")
    print("=" * 70)

    if not args.apply:
        print("\n  🔍 DRY RUN - بدون تغییر")
    else:
        print("\n  ⚠️  LIVE - با تغییر")
        print("  ⚠️  مطمئن شوید:")
        print("     1. سه جدول پاک شده‌اند")
        print("     2. مرخصی شارژ شده است")
        confirm = input("\n  ادامه؟ (yes/no): ").strip()
        if confirm.lower() != 'yes':
            print("  ❌ لغو شد")
            return

    rebuilder = LeaveRebuilder(dry_run=not args.apply)
    try:
        rebuilder.rebuild()
        rebuilder.save_log(args.log_file)
    except Exception as e:
        print(f"\n❌ خطا: {e}")
        import traceback
        traceback.print_exc()
    finally:
        rebuilder.close()


if __name__ == '__main__':
    main()