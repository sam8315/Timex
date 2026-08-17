"""
نقطه ورود ربات بله
اجرا: python -m bot.main
"""
import time
import sys

from bot import bale_api
from bot.config import POLLING_TIMEOUT
from bot.handlers import handle_message


def main():
    print("=" * 50)
    print("🤖 ربات تردد بله")
    print("=" * 50)

    # بررسی اتصال به ربات
    bot_info = bale_api.get_me()
    if not bot_info.get('ok'):
        print("❌ خطا: اتصال به ربات برقرار نشد!")
        print("   لطفاً توکن ربات را در bot/config.py بررسی کنید.")
        sys.exit(1)

    bot_name = bot_info.get('result', {}).get('username', 'unknown')
    print(f"✅ ربات متصل شد: @{bot_name}")
    print(f"⏱️ شروع polling...\n")

    offset = 0

    try:
        while True:
            try:
                updates = bale_api.get_updates(offset=offset, timeout=POLLING_TIMEOUT)

                for update in updates:
                    offset = update.get('update_id', 0) + 1

                    message = update.get('message')
                    if message:
                        try:
                            handle_message(message)
                        except Exception as e:
                            print(f"❌ خطا در پردازش پیام: {e}")

            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"⚠️ خطا در polling: {e}")
                time.sleep(5)

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n🛑 ربات متوقف شد.")


if __name__ == "__main__":
    main()