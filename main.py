from core.device_manager import DeviceManager
from ui.console import ConsoleUI
from config.settings import DEVICE_IP, DEVICE_PORT
from database.init_db import create_tables


def main():
    """تابع اصلی برنامه"""
    # ساخت/بررسی جداول دیتابیس در شروع برنامه
    print("🔧 در حال آماده‌سازی دیتابیس...")
    create_tables()
    print()

    manager = DeviceManager(DEVICE_IP, DEVICE_PORT)
    ui = ConsoleUI(manager)

    try:
        ui.run()
    except KeyboardInterrupt:
        manager.disconnect()
        print("\n\n👋 BYE!")


if __name__ == "__main__":
    main()