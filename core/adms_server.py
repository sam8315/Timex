"""
ADMS Server for receiving real-time attendance data from the device
Mode: Local Network (OFF + OFF)
"""
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from datetime import datetime
import logging
from sqlalchemy import and_
from database.engine import SessionLocal
from models.attendance import Attendance

logger = logging.getLogger(__name__)

app = FastAPI(title="ADMS Server", version="1.0.0")

# Store connected devices info
connected_devices = {}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "status": "running",
        "message": "ADMS Server is running",
        "connected_devices": len(connected_devices)
    }


@app.get("/iclock/cdata")
async def handshake(request: Request):
    """
    Device handshake
    The device calls this endpoint to check connection
    """
    sn = request.query_params.get('SN', 'unknown')
    options = request.query_params.get('options', 'all')

    logger.debug(
        "Handshake from device",
        extra={"event": "device.handshake", "device_id": sn},
    )

    connected_devices[sn] = {
        'last_seen': datetime.now(),
        'ip': request.client.host,
        'options': options
    }

    return PlainTextResponse("OK")


@app.post("/iclock/cdata")
async def receive_data(request: Request):
    """
    Receive data from device
    Includes: attendance, users, operations
    """
    sn = request.query_params.get('SN', 'unknown')
    table = request.query_params.get('table', '').upper()
    stamp = request.query_params.get('Stamp', '')

    body = await request.body()
    body_text = body.decode('utf-8', errors='ignore').strip()
    payload_size = len(body)

    logger.debug(
        "Device data request table=%s stamp=%s payload_size=%s",
        table,
        stamp,
        payload_size,
        extra={"event": "device.request", "device_id": sn},
    )

    if 'ATTLOG' in table or 'CHECKLOG' in table or 'ATTLOG' in body_text or 'CHECKLOG' in body_text:
        await process_attendance_data(sn, body_text)
    elif 'USERINFO' in table or 'USERINFO' in body_text:
        await process_user_data(sn, body_text)
    elif 'OPERLOG' in table or 'OPLOG' in table or 'OPERLOG' in body_text or 'OPLOG' in body_text:
        logger.debug(
            "Received OPERLOG (ignored)",
            extra={"event": "device.request", "device_id": sn},
        )
    else:
        if body_text:
            logger.warning(
                "Unknown data type table=%s payload_size=%s",
                table,
                payload_size,
                extra={"event": "device.request", "device_id": sn},
            )

    return PlainTextResponse("OK")


async def process_attendance_data(sn: str, data: str):
    """Process attendance records"""
    if not data.strip():
        logger.debug(
            "Empty attendance data (heartbeat or sync)",
            extra={"event": "device.request", "device_id": sn},
        )
        return

    lines = data.strip().split('\n')
    records_added = 0

    db = SessionLocal()
    try:
        for line in lines:
            line = line.strip()
            if not line or line.startswith('ATTLOG') or line.startswith('CHECKLOG'):
                continue

            parts = line.split('\t')
            if len(parts) < 4:
                continue

            user_id = parts[0].strip()
            timestamp_str = parts[1].strip()
            status = int(parts[2].strip()) if parts[2].strip() else 0
            punch = int(parts[3].strip()) if parts[3].strip() else 0

            try:
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    logger.warning(
                        "Invalid timestamp format",
                        extra={"event": "device.request", "device_id": sn},
                    )
                    continue

            existing = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == user_id,
                    Attendance.timestamp == timestamp
                )
            ).first()

            if not existing:
                attendance = Attendance(
                    user_id=user_id,
                    timestamp=timestamp,
                    status=punch,
                    punch=status,
                    source='A'  # ✅ CHANGED: 'A' for API/ADMS (was 'D')
                )
                db.add(attendance)
                records_added += 1

        if records_added > 0:
            db.commit()
            logger.info(
                "Saved %s new attendance records",
                records_added,
                extra={"event": "sync.completed", "device_id": sn},
            )
        else:
            logger.debug(
                "No new attendance records (all duplicates)",
                extra={"event": "sync.completed", "device_id": sn},
            )

    except Exception:
        db.rollback()
        logger.exception(
            "Error processing attendance",
            extra={"event": "sync.failed", "device_id": sn},
        )
    finally:
        db.close()


async def process_user_data(sn: str, data: str):
    """Process user data"""
    logger.info(
        "Received user data (ignored for now) payload_size=%s",
        len(data.encode('utf-8', errors='ignore')),
        extra={"event": "device.request", "device_id": sn},
    )


@app.get("/iclock/devicemd")
async def get_device_info(request: Request):
    sn = request.query_params.get('SN', 'unknown')
    logger.debug(
        "Device info request",
        extra={"event": "device.request", "device_id": sn},
    )
    return PlainTextResponse("OK")


@app.post("/iclock/devicemd")
async def send_command(request: Request):
    sn = request.query_params.get('SN', 'unknown')
    body = await request.body()
    logger.debug(
        "Send command to device payload_size=%s",
        len(body),
        extra={"event": "device.request", "device_id": sn},
    )
    return PlainTextResponse("OK")


@app.get("/iclock/getrequest")
async def get_request(request: Request):
    sn = request.query_params.get('SN', 'unknown')
    logger.debug(
        "getrequest poll",
        extra={"event": "device.request", "device_id": sn},
    )
    return PlainTextResponse("")


@app.get("/status")
async def status():
    return {
        "server_status": "running",
        "connected_devices": len(connected_devices),
        "devices": [
            {
                "serial": sn,
                "ip": info['ip'],
                "last_seen": info['last_seen'].isoformat()
            }
            for sn, info in connected_devices.items()
        ]
    }


def run_server(host: str = "0.0.0.0", port: int = 8081):
    import uvicorn

    logger.info(
        "ADMS API server starting address=%s:%s endpoint=/iclock/cdata status=/status",
        host,
        port,
        extra={"event": "service.starting"},
    )

    try:
        # log_config=None keeps Timex shared logging (same pattern as run_web.py).
        uvicorn.run(app, host=host, port=port, log_level="info", log_config=None)
    except OSError:
        logger.critical(
            "ADMS server failed to bind %s:%s",
            host,
            port,
            exc_info=True,
            extra={"event": "service.stopping"},
        )
        raise
    except Exception:
        logger.critical(
            "ADMS server crashed",
            exc_info=True,
            extra={"event": "service.stopping"},
        )
        raise
    finally:
        logger.info(
            "ADMS API server stopped",
            extra={"event": "service.stopping"},
        )
