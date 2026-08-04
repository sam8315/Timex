"""
Script to run the ADMS server with an initial one-time sync
"""
import sys
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging with timestamp
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.device_manager import DeviceManager
from core.adms_server import run_server


def perform_initial_sync(device_ip: str, device_port: int):
    """Perform a one-time sync of existing attendance records before starting the API"""
    logger.info("=" * 70)
    logger.info("  INITIAL DEVICE SYNC")
    logger.info("=" * 70)
    logger.info("  Syncing existing attendance records from device before starting API...")

    manager = DeviceManager(ip=device_ip, port=device_port)

    try:
        if manager.connect():
            logger.info("  Connected to device. Starting sync (dry_run_first=False)...")

            result = manager.sync_attendance_to_db(dry_run_first=False)

            if 'error' in result:
                logger.error(f"  ❌ Sync failed: {result['error']}")
            else:
                logger.info(f"  ✅ Sync completed successfully.")
                logger.info(f"     - Total fetched  : {result.get('total_fetched', 0)}")
                logger.info(f"     - Newly inserted : {result.get('inserted', 0)}")
                logger.info(f"     - Skipped (dups) : {result.get('skipped_duplicates', 0)}")

            manager.disconnect()
        else:
            logger.warning("  ⚠️ Could not connect to device for initial sync.")
            logger.warning("  ➡️ Starting API server anyway (will sync new records via ADMS push).")
    except Exception as e:
        logger.error(f"  ❌ Initial sync error: {e}")


if __name__ == "__main__":
    # Read configuration from environment (with fallback defaults)
    device_ip = os.getenv("DEVICE_IP", "192.168.1.232")
    device_port = int(os.getenv("DEVICE_PORT", "4370"))
    adms_host = os.getenv("ADMS_HOST", "0.0.0.0")
    adms_port = int(os.getenv("ADMS_PORT", "8081"))

    # 1. Perform initial sync using device settings
    perform_initial_sync(device_ip, device_port)

    # 2. Start ADMS API Server
    logger.info(f"Starting ADMS server on {adms_host}:{adms_port}")
    run_server(host=adms_host, port=adms_port)