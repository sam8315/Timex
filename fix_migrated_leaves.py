"""
اسکریپت اصلاح مرخصی‌های منتقل شده از morbrg
نسخه ۲ - با تبدیل صحیح سال میلادی به شمسی
"""
from sqlalchemy import and_
from database.engine import SessionLocal
from models.leave_request import LeaveRequest
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
import jdatetime


LEAVE_TYPE_NAMES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
    # ✅ مأموریت حذف شد - نباید مانده مرخصی داشته باشد
}


def gregorian_to_jalali_year(g_date) -> int:
    """تبدیل تاریخ میلادی به سال شمسی"""
    return jdatetime.date.fromgregorian(date=g_date).year


def fix_migrated_leaves():
    """اصلاح مرخصی‌های منتقل شده"""
    print("=" * 70)
    print("  🔧 اصلاح مرخصی‌های منتقل شده از morbrg (نسخه ۲)")
    print("=" * 70)

    db = SessionLocal()

    stats = {
        'total_requests': 0,
        'fixed': 0,
        'skipped': 0,
        'skipped_mission': 0,  # ✅ شمارش مأموریت‌ها
        'errors': 0
    }

    try:
        # دریافت تمام درخواست‌های تایید شده که از migration آمده‌اند
        migrated_requests = db.query(LeaveRequest).filter(
            and_(
                LeaveRequest.status == 'A',
                LeaveRequest.approved_by == 'migration'
            )
        ).all()

        stats['total_requests'] = len(migrated_requests)
        print(f"\n📊 تعداد درخواست‌های منتقل شده: {len(migrated_requests)}")

        if not migrated_requests:
            print("✅ هیچ درخواست منتقل شده‌ای یافت نشد")
            return

        # گروه‌بندی بر اساس کاربر، **سال شمسی** و نوع
        user_leaves = {}
        for req in migrated_requests:
            # ✅ تبدیل سال میلادی به شمسی
            jalali_year = gregorian_to_jalali_year(req.from_date)

            # ✅ رد کردن مأموریت (چون مانده مرخصی ندارد)
            if req.leave_type == 'M':
                stats['skipped_mission'] += 1
                continue

            key = (req.user_id, jalali_year, req.leave_type)

            if key not in user_leaves:
                user_leaves[key] = {
                    'total_days': 0,
                    'requests': []
                }
            user_leaves[key]['total_days'] += req.days_count
            user_leaves[key]['requests'].append(req)

        print(f"📊 تعداد گروه‌های یکتا: {len(user_leaves)}")
        print(f"📊 مأموریت‌های رد شده: {stats['skipped_mission']}")

        # پردازش هر گروه
        print("\n💾 در حال ایجاد تراکنش‌ها...")

        for (user_id, jalali_year, leave_type), data in user_leaves.items():
            total_days = data['total_days']
            type_name = LEAVE_TYPE_NAMES.get(leave_type, leave_type)

            try:
                # 1. بررسی وجود تراکنش قبلی (با نوع MIGRATION)
                existing_transaction = db.query(LeaveTransaction).filter(
                    and_(
                        LeaveTransaction.user_id == user_id,
                        LeaveTransaction.year == jalali_year,  # ✅ سال شمسی
                        LeaveTransaction.leave_type == leave_type,
                        LeaveTransaction.transaction_type == 'MIGRATION'
                    )
                ).first()

                if existing_transaction:
                    stats['skipped'] += 1
                    continue

                # 2. بررسی وجود مانده
                balance = db.query(LeaveBalance).filter(
                    and_(
                        LeaveBalance.user_id == user_id,
                        LeaveBalance.year == jalali_year,  # ✅ سال شمسی
                        LeaveBalance.leave_type == leave_type
                    )
                ).first()

                if balance:
                    # کسر از مانده
                    old_balance = balance.balance
                    balance.balance -= total_days
                    new_balance = balance.balance
                else:
                    # ایجاد مانده منفی
                    balance = LeaveBalance(
                        user_id=user_id,
                        year=jalali_year,  # ✅ سال شمسی
                        leave_type=leave_type,
                        balance=-total_days
                    )
                    db.add(balance)
                    old_balance = 0
                    new_balance = -total_days

                # 3. ایجاد تراکنش برداشت
                transaction = LeaveTransaction(
                    user_id=user_id,
                    year=jalali_year,  # ✅ سال شمسی
                    leave_type=leave_type,
                    amount=-total_days,
                    transaction_type='MIGRATION',
                    description=f'انتقال از morbrg - {len(data["requests"])} درخواست ({total_days} روز)'
                )
                db.add(transaction)

                stats['fixed'] += 1
                print(f"  ✅ {user_id} | سال {jalali_year} | {type_name} | "
                      f"مانده: {old_balance} → {new_balance} ({-total_days} روز)")

            except Exception as e:
                db.rollback()
                print(f"  ❌ خطا در {user_id}/{jalali_year}/{leave_type}: {e}")
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
    print("  📊 آمار اصلاح:")
    print("=" * 70)
    print(f"  • کل درخواست‌های منتقل شده : {stats['total_requests']}")
    print(f"  • مأموریت‌های رد شده        : {stats['skipped_mission']}")
    print(f"  • اصلاح شده                 : {stats['fixed']} ✅")
    print(f"  • رد شده (قبلاً اصلاح شده)  : {stats['skipped']} ⚠️")
    print(f"  • خطاها                     : {stats['errors']} ❌")
    print("=" * 70)

    print("\n✅ عملیات کامل شد!")


if __name__ == "__main__":
    confirm = input("⚠️  آیا مطمئن هستید؟ (بله/خیر): ").strip()
    if confirm.lower() in ['بله', 'yes', 'y']:
        fix_migrated_leaves()
    else:
        print("❌ عملیات لغو شد")