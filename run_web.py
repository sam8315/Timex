"""اجرای سرور وب"""
import re
import uvicorn
from dotenv import load_dotenv
import sys
import io, os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

load_dotenv()
import logging

# فعال‌سازی لاگ برای دیباگ
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# تنظیم کدگذاری خروجی به UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

TEST_USER_ID = "admin"
TEST_PASSWORD = "123456"


def create_database_if_missing() -> None:
    """Create the configured PostgreSQL database when it does not exist."""
    from config.settings import DB_NAME
    from database.engine import engine

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", DB_NAME):
        raise ValueError("DB_NAME must contain only letters, numbers, and underscores")

    maintenance_url = engine.url.set(database="postgres")
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with maintenance_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    finally:
        maintenance_engine.dispose()


def ensure_database_tables() -> None:
    """Create the database and any mapped tables required by the web application."""
    from database.engine import engine
    from database.init_db import create_tables

    try:
        create_tables()
    except OperationalError as error:
        # PostgreSQL error 3D000 means the configured database does not exist.
        if getattr(error.orig, "pgcode", None) != "3D000":
            raise
        create_database_if_missing()
        engine.dispose()
        create_tables()


def ensure_test_access() -> None:
    """Create the initial test super-admin and its login profile only when absent."""
    from database.engine import SessionLocal
    from models.employee import Employee
    from models.user import User
    from web.security import hash_password

    db = SessionLocal()
    try:
        created = False
        user = db.query(User).filter(User.user_id == TEST_USER_ID).first()
        if not user:
            user = User(
                user_id=TEST_USER_ID,
                name="Test Administrator",
                password_hash=hash_password(TEST_PASSWORD),
                must_change_password=False,
                role="super_admin",
                web_enabled=True,
            )
            db.add(user)
            created = True

        employee = db.query(Employee).filter(Employee.user_id == TEST_USER_ID).first()
        if not employee:
            employee = Employee(
                user_id=TEST_USER_ID,
                national_code=TEST_USER_ID,
                first_name="Test",
                last_name="Administrator",
                is_active=True,
            )
            db.add(employee)
            created = True

        if created:
            db.commit()
            print("Test administrator access was created.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8082"))

    ensure_database_tables()
    ensure_test_access()

    print(f"🚀 سرور وب در http://{host}:{port} اجرا می‌شود...")

    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=False
    )
