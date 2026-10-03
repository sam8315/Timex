"""
Script to run the ADMS server with an initial one-time sync
"""
import sys
import os
import time
import threading
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logging_config import configure_logging

configure_logging("adms")
logger = logging.getLogger(__name__)

from core.device_manager import DeviceManager
from core.adms_server import run_server


def perform_initial_sync(device_ip: str, device_port: int):
    """Perform a one-time sync of existing attendance records before starting the API"""
    logger.info(
        "Initial device sync starting",
        extra={"event": "sync.started", "device_id": device_ip},
    )

    manager = DeviceManager(ip=device_ip, port=device_port)

    try:
        if manager.connect():
            logger.info(
                "Connected to device; starting sync",
                extra={"event": "sync.started", "device_id": device_ip},
            )

            result = manager.sync_attendance_to_db(dry_run_first=False)

            if 'error' in result:
                logger.error(
                    "Sync failed: %s",
                    result['error'],
                    extra={"event": "sync.failed", "device_id": device_ip},
                )
            else:
                logger.info(
                    "Sync completed successfully",
                    extra={
                        "event": "sync.completed",
                        "device_id": device_ip,
                        "duration_ms": result.get("duration_ms"),
                    },
                )
                logger.info(
                    "Sync summary: fetched=%s inserted=%s duplicates=%s errors=%s",
                    result.get('total_fetched', 0),
                    result.get('inserted', 0),
                    result.get('skipped_duplicates', 0),
                    result.get('errors', 0),
                    extra={"event": "sync.completed", "device_id": device_ip},
                )

            manager.disconnect()
        else:
            logger.warning(
                "Could not connect to device for initial sync; starting API anyway",
                extra={"event": "device.offline", "device_id": device_ip},
            )
    except Exception:
        logger.exception(
            "Initial sync error",
            extra={"event": "sync.failed", "device_id": device_ip},
        )


def monitor_device_connection(device_ip: str, device_port: int, check_interval: int = 60):
    """
    Periodically check device connectivity.
    If device was offline and comes back online, trigger a full sync.
    """
    was_connected = False
    logger.info(
        "Starting device connection monitor (interval=%ss)",
        check_interval,
        extra={"event": "service.starting", "device_id": device_ip},
    )

    while True:
        try:
            manager = DeviceManager(ip=device_ip, port=device_port)
            is_connected = manager.connect()
            manager.disconnect()

            if is_connected and not was_connected:
                logger.info(
                    "Device reconnected; performing full sync",
                    extra={"event": "device.reconnected", "device_id": device_ip},
                )
                perform_initial_sync(device_ip, device_port)
                was_connected = True
            elif is_connected and was_connected:
                pass
            elif not is_connected and was_connected:
                logger.warning(
                    "Device went offline",
                    extra={"event": "device.offline", "device_id": device_ip},
                )
                was_connected = False
            else:
                pass

        except Exception:
            logger.exception(
                "Monitor error",
                extra={"event": "sync.failed", "device_id": device_ip},
            )

        time.sleep(check_interval)


if __name__ == "__main__":
    device_ip = os.getenv("DEVICE_IP", "192.168.1.232")
    device_port = int(os.getenv("DEVICE_PORT", "4370"))
    adms_host = os.getenv("ADMS_HOST", "0.0.0.0")
    adms_port = int(os.getenv("ADMS_PORT", "8081"))

    logger.info(
        "ADMS process starting host=%s port=%s",
        adms_host,
        adms_port,
        extra={"event": "service.starting", "device_id": device_ip},
    )

    try:
        perform_initial_sync(device_ip, device_port)

        monitor_thread = threading.Thread(
            target=monitor_device_connection,
            args=(device_ip, device_port, 60),
            daemon=True,
        )
        monitor_thread.start()

        logger.info(
            "Starting ADMS server on %s:%s",
            adms_host,
            adms_port,
            extra={"event": "service.starting"},
        )
        run_server(host=adms_host, port=adms_port)
    except KeyboardInterrupt:
        logger.info(
            "ADMS process stopping",
            extra={"event": "service.stopping"},
        )
    except Exception:
        logger.critical(
            "ADMS process failed",
            exc_info=True,
            extra={"event": "service.stopping"},
        )
        raise
