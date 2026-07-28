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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

    logger.info(f"Handshake from device: {sn}")

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

    logger.info(f"Received data from device {sn} - Table: {table}, Stamp: {stamp}")

    body = await request.body()
    body_text = body.decode('utf-8', errors='ignore').strip()

    if 'ATTLOG' in table or 'CHECKLOG' in table or 'ATTLOG' in body_text or 'CHECKLOG' in body_text:
        await process_attendance_data(sn, body_text)
    elif 'USERINFO' in table or 'USERINFO' in body_text:
        await process_user_data(sn, body_text)
    elif 'OPERLOG' in table or 'OPLOG' in table or 'OPERLOG' in body_text or 'OPLOG' in body_text:
        logger.info(f"Received OPERLOG from device {sn} (Device operation log - ignored for now)")
    else:
        if body_text:
            logger.warning(f"Unknown data type from {sn} - Table: {table}")
            logger.debug(f"Body: {body_text[:200]}")

    return PlainTextResponse("OK")


async def process_attendance_data(sn: str, data: str):
    """Process attendance records"""
    if not data.strip():
        logger.info(f"Empty attendance data from device {sn} (Heartbeat or Sync)")
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
                    logger.warning(f"Invalid timestamp format: {timestamp_str}")
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
                    status=status,
                    punch=punch,
                    source='A'  # ✅ CHANGED: 'A' for API/ADMS (was 'D')
                )
                db.add(attendance)
                records_added += 1

        if records_added > 0:
            db.commit()
            logger.info(f"Saved {records_added} new attendance records from device {sn}")
        else:
            logger.info(f"No new attendance records from device {sn} (all duplicates)")

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing attendance: {e}")
    finally:
        db.close()


async def process_user_data(sn: str, data: str):
    """Process user data"""
    logger.info(f"Received user data from {sn} (ignored for now)")


@app.get("/iclock/devicemd")
async def get_device_info(request: Request):
    sn = request.query_params.get('SN', 'unknown')
    logger.info(f"Device info request from {sn}")
    return PlainTextResponse("OK")


@app.post("/iclock/devicemd")
async def send_command(request: Request):
    sn = request.query_params.get('SN', 'unknown')
    await request.body()
    logger.info(f"Send command to device {sn}")
    return PlainTextResponse("OK")


@app.get("/iclock/getrequest")
async def get_request(request: Request):
    sn = request.query_params.get('SN', 'unknown')
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

    print("\n" + "=" * 70)
    print("  ADMS API SERVER STARTING")
    print("=" * 70)
    print(f"  Address : http://{host}:{port}")
    print(f"  Endpoint: http://{host}:{port}/iclock/cdata")
    print(f"  Status  : http://{host}:{port}/status")
    print("=" * 70)
    print("\n  Device Settings:")
    print(f"     ADMS: ON")
    print(f"     Server Address: {host}")
    print(f"     Server Port: {port}")
    print("=" * 70 + "\n")

    uvicorn.run(app, host=host, port=port, log_level="info")