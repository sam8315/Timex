"""
اسکریپت debug برای بررسی خروجی generate_leave_report
"""
from core.report_generator import ReportGenerator


def debug():
    print("=" * 70)
    print("  🔍 Debug: بررسی خروجی generate_leave_report")
    print("=" * 70)

    generator = ReportGenerator()
    try:
        reports = generator.generate_leave_report(1405, None)

        print(f"\n📊 تعداد گزارش‌ها: {len(reports)}")

        if reports:
            print("\n📋 اولین گزارش:")
            first_report = reports[0]
            print(f"  کلیدها: {list(first_report.keys())}")
            print(f"  مقادیر: {first_report}")

            # بررسی وجود کلیدها
            required_keys = ['user_id', 'full_name', 'department', 'annual_leave',
                             'sick_leave', 'reward_leave', 'unpaid_leave',
                             'total_days', 'total_requests']

            print("\n✅ بررسی کلیدهای مورد نیاز:")
            for key in required_keys:
                exists = key in first_report
                status = "✅" if exists else "❌"
                print(f"  {status} {key}: {first_report.get(key, 'NOT FOUND')}")
        else:
            print("\n⚠️  هیچ گزارشی یافت نشد")

    finally:
        generator.close()


if __name__ == "__main__":
    debug()