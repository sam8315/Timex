"""
Script to run the ADMS server with an initial one-time sync
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.device_manager import DeviceManager
from core.adms_server import run_server


def perform_initial_sync():
    """Perform a one-time sync of existing attendance records before starting the API"""
    print("\n" + "=" * 70)
    print("  INITIAL DEVICE SYNC")
    print("=" * 70)
    print("  Syncing existing attendance records from device before starting API...")

    # ⚠️ IMPORTANT: Update these values to match your device's IP and Port
    DEVICE_IP = "192.168.1.232"
    DEVICE_PORT = 4370

    manager = DeviceManager(ip=DEVICE_IP, port=DEVICE_PORT)

    try:
        if manager.connect():
            print("  Connected to device. Starting sync (dry_run_first=False)...")

            result = manager.sync_attendance_to_db(dry_run_first=False)

            if 'error' in result:
                print(f"  ❌ Sync failed: {result['error']}")
            else:
                print(f"  ✅ Sync completed successfully.")
                print(f"     - Total fetched  : {result.get('total_fetched', 0)}")
                print(f"     - Newly inserted : {result.get('inserted', 0)}")
                print(f"     - Skipped (dups) : {result.get('skipped_duplicates', 0)}")

            manager.disconnect()
        else:
            print("  ⚠️ Could not connect to device for initial sync.")
            print("  ➡️ Starting API server anyway (will sync new records via ADMS push).")
    except Exception as e:
        print(f"  ❌ Initial sync error: {e}")
    # ✅ هیچ finally و close() لازم نیست


if __name__ == "__main__":
    # 1. Perform initial sync
    perform_initial_sync()

    # 2. Start ADMS API Server
    HOST = "0.0.0.0"  # Listen on all interfaces
    PORT = 8081

    run_server(host=HOST, port=PORT)