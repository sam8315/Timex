"""اجرای سرور وب"""
import re
import uvicorn
from dotenv import load_dotenv
import sys
import io, os
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from core.logging_config import configure_logging
from core.service_monitoring import record_error, record_startup, record_success

load_dotenv()

logger = logging.getLogger(__name__)

TEST_USER_ID = "admin"
TEST_PASSWORD = "123456"


def _configure_stdio_utf8() -> None:
    """Set UTF-8 stdio only for the real process entrypoint (not imports/tests)."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        # Some hosts/tests replace stdio without a raw buffer.
        pass


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
            logger.info(
                "Database created name=%s",
                DB_NAME,
                extra={"event": "database.ready"},
            )
    finally:
        maintenance_engine.dispose()


def ensure_database_tables() -> None:
    """
    در هر اجرای سرور:
    - اگر دیتابیس نباشد، ساخته می‌شود
    - جداول جدید مدل‌ها ساخته می‌شوند (create_all)
    - ستون‌های جدید به جداول موجود اضافه می‌شوند (migrate_missing_columns)
    - سایر migrationهای داخلی init_db اجرا می‌شوند
    """
    # ثبت همهٔ مدل‌ها در MetaData قبل از create_all / migrate
    import models  # noqa: F401
    from database.engine import engine
    from database.init_db import create_tables, check_tables

    logger.info(
        "Ensuring database tables",
        extra={"event": "service.starting"},
    )
    try:
        create_tables()
        check_tables()
    except OperationalError as error:
        # PostgreSQL error 3D000 means the configured database does not exist.
        if getattr(error.orig, "pgcode", None) != "3D000":
            raise
        logger.warning(
            "Database does not exist; creating",
            extra={"event": "service.starting"},
        )
        create_database_if_missing()
        engine.dispose()
        create_tables()
        check_tables()

    logger.info(
        "Database tables ready",
        extra={"event": "database.ready"},
    )


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
            logger.info(
                "Test administrator access was created",
                extra={"event": "service.starting"},
            )
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to ensure test access",
            extra={"event": "service.starting"},
        )
        raise
    finally:
        db.close()


def main() -> None:
    """Web process entrypoint (DB readiness → startup mark → uvicorn)."""
    _configure_stdio_utf8()
    configure_logging("web")

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8082"))

    logger.info(
        "Web process starting host=%s port=%s",
        host,
        port,
        extra={"event": "service.starting"},
    )

    try:
        try:
            ensure_database_tables()
        except Exception:
            # Best-effort only; never hide the original startup failure.
            try:
                record_error(
                    "web",
                    error_code="DB_STARTUP_FAILED",
                    error_summary="Database startup failed",
                )
            except Exception:
                logger.exception(
                    "Web DB startup failure monitoring update failed",
                    extra={"event": "database.operation_failed"},
                )
            raise

        # last_success_at for web = last successful DB readiness.
        try:
            record_success(
                "web",
                metrics={"last_success_kind": "db_ready"},
            )
        except Exception:
            logger.exception(
                "Web DB readiness monitoring update failed",
                extra={"event": "database.operation_failed"},
            )

        ensure_test_access()

        # Entering the real web serve lifecycle (uvicorn about to run).
        try:
            record_startup("web")
        except Exception:
            logger.exception(
                "Web startup monitoring update failed",
                extra={"event": "database.operation_failed"},
            )

        logger.info(
            "Web server starting at http://%s:%s",
            host,
            port,
            extra={"event": "service.started"},
        )

        # log_config=None keeps Timex shared logging (web.app.log / web.access.log).
        uvicorn.run(
            "web.app:app",
            host=host,
            port=port,
            reload=False,
            log_config=None,
        )
    except KeyboardInterrupt:
        logger.info(
            "Web process stopping",
            extra={"event": "service.stopping"},
        )
    except Exception:
        logger.critical(
            "Web process failed",
            exc_info=True,
            extra={"event": "service.stopping"},
        )
        raise


if __name__ == "__main__":
    main()
