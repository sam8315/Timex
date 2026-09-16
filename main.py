from core.device_manager import DeviceManager
from ui.console import ConsoleUI
from config.settings import DEVICE_IP, DEVICE_PORT


def main():
    manager = DeviceManager(DEVICE_IP, DEVICE_PORT)
    ui = ConsoleUI(manager)

    try:
        ui.run()
    except KeyboardInterrupt:
        manager.disconnect()
        print("\n\n👋 BYE!")


if __name__ == "__main__":
    main()