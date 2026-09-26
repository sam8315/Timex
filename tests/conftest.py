"""
Shared fixtures for Timex web-panel tests.

- Uses an isolated PostgreSQL database (timex_test_db by default) so the
  development database is never touched.
- Overrides the FastAPI `get_db` dependency so every HTTP request in tests
  talks to the test database.
- Writes a machine-readable summary of every pytest run to
  log/test_status.json (consumed by the admin dashboard banner).
"""
import itertools
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import jdatetime
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Test-only cryptographic secrets; production must provide real values via the environment.
os.environ.setdefault("WEB_SECRET_KEY", "test-web-secret-key-32-chars-minimum-0001")
os.environ.setdefault("WEB_SESSION_MIDDLEWARE_SECRET_KEY", "test-session-secret-key-32-chars-0002")

from config.settings import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

TEST_DB_NAME = os.getenv("TEST_DB_NAME", "timex_test_db")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", TEST_DB_NAME):
    raise ValueError("TEST_DB_NAME must contain only letters, numbers and underscores")

TEST_DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
)
LOG_DIR = ROOT / "log"
TEST_STATUS_PATH = LOG_DIR / "test_status.json"
TEST_RUNNING_MARKER = LOG_DIR / "test_status.running"


def _status_path() -> Path:
    override = os.getenv("TIMEX_TEST_STATUS_PATH")
    return Path(override) if override else TEST_STATUS_PATH


def _running_marker() -> Path:
    override = os.getenv("TIMEX_TEST_RUNNING_MARKER")
    return Path(override) if override else TEST_RUNNING_MARKER

USER_PASSWORD = "TestPass123"


# ---------------------------------------------------------------------------
# Test database bootstrap (runs once at collection import time)
# ---------------------------------------------------------------------------
def _ensure_test_database() -> None:
    import psycopg2

    conn = psycopg2.connect(
        dbname="postgres",
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)
            )
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        conn.close()


_ensure_test_database()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False
)

import models  # noqa: F401,E402  (register every mapped table)
from models import Base  # noqa: E402
from database.init_db import (  # noqa: E402
    migrate_employee_address_city_id,
    migrate_employee_address_history,
    migrate_employee_address_coords_pair,
    migrate_employee_address_nan_check,
    migrate_employee_address_range_check,
)
from sqlalchemy import text as _sql_text

# ---------------------------------------------------------------------------
# Legacy-schema migration (explicit, conditional)
# ---------------------------------------------------------------------------
# `create_all` only creates missing tables; it does not add columns to tables
# that already exist. Test databases may therefore contain schemas from an
# older branch. Detect stale tables by required columns and rebuild only the
# affected test-only tables before `create_all`.
from sqlalchemy import inspect as _sa_inspect  # noqa: E402


def _column_names(conn, table: str) -> set:
    if table not in _sa_inspect(conn).get_table_names():
        return set()
    return {c["name"] for c in _sa_inspect(conn).get_columns(table)}


def _drop_tables_if_exist(conn, *tables: str) -> None:
    existing = set(_sa_inspect(conn).get_table_names())
    for table in tables:
        if table in existing:
            conn.execute(_sql_text(f'DROP TABLE "{table}" CASCADE'))
    conn.commit()


with test_engine.connect() as _conn:
    tl_cols = _column_names(_conn, "travel_leave_details")
    current_tl = {
        "final_travel_days", "manual_override", "jalali_year",
        "destination_latitude_snapshot", "destination_longitude_snapshot",
    }
    if tl_cols and not current_tl.issubset(tl_cols):
        _drop_tables_if_exist(_conn, "travel_leave_details")

    city_cols = _column_names(_conn, "cities")
    city_required = {
        "id", "name", "province", "latitude", "longitude",
        "is_active", "created_at", "updated_at",
    }
    if city_cols:
        if "active" in city_cols and "is_active" not in city_cols:
            _conn.execute(_sql_text(
                "ALTER TABLE cities RENAME COLUMN active TO is_active"
            ))
            _conn.commit()
            city_cols = _column_names(_conn, "cities")

        if not city_required.issubset(city_cols):
            _drop_tables_if_exist(_conn, "cities", "employee_service_locations")

    policy_cols = _column_names(_conn, "travel_leave_policies")
    rule_cols = _column_names(_conn, "travel_leave_policy_rules")
    quota_cols = _column_names(_conn, "travel_leave_quota_settings")

    policy_required = {
        "id", "contract_type_code", "is_enabled", "distance_method",
        "description", "created_at", "updated_at",
    }
    rule_required = {
        "id", "policy_id", "min_km", "max_km", "travel_days",
        "description", "is_active", "created_at", "updated_at",
    }
    quota_required = {
        "id", "policy_id", "marital_status", "annual_max_usage",
        "description", "parameter_key", "parameter_value",
        "created_at", "updated_at",
    }

    stale_policy_schema = (
        policy_cols and not policy_required.issubset(policy_cols)
    )
    stale_rule_schema = (
        rule_cols and not rule_required.issubset(rule_cols)
    )
    stale_quota_schema = (
        quota_cols and not quota_required.issubset(quota_cols)
    )
    if stale_policy_schema or stale_rule_schema or stale_quota_schema:
        _drop_tables_if_exist(
            _conn,
            "travel_leave_policy_rules",
            "travel_leave_quota_settings",
            "travel_leave_policies",
        )

Base.metadata.create_all(bind=test_engine)

with test_engine.connect() as _conn:
    _conn.execute(_sql_text("""
        ALTER TABLE leave_requests
        ADD COLUMN IF NOT EXISTS start_time TIME,
        ADD COLUMN IF NOT EXISTS end_time TIME
    """))
    _conn.execute(_sql_text("""
        ALTER TABLE employee_addresses
        ALTER COLUMN district DROP NOT NULL
    """))
    _conn.execute(_sql_text("""
        ALTER TABLE employee_addresses
        ADD COLUMN IF NOT EXISTS city_id INTEGER
    """))
    _conn.execute(_sql_text("""
        CREATE INDEX IF NOT EXISTS ix_employee_addresses_city_id
        ON employee_addresses (city_id)
    """))
    _conn.execute(_sql_text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'employee_addresses_city_id_fkey'
            ) THEN
                ALTER TABLE employee_addresses
                ADD CONSTRAINT employee_addresses_city_id_fkey
                FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE RESTRICT;
            END IF;
        END
        $$;
    """))
    _conn.commit()

# Audit history must not be cascade-deleted: drop the legacy user_id FK
# on the persistent test table using the real startup migration.
migrate_employee_address_history(bind_engine=test_engine)
# Coordinate pairs must be complete: add the CHECK using the real migration
# (the persistent test database holds no partial-coordinate rows).
migrate_employee_address_coords_pair(bind_engine=test_engine)
# NaN coordinates must be rejected at the DB level.
migrate_employee_address_nan_check(bind_engine=test_engine)
# Coordinate ranges must be enforced at the DB level.
migrate_employee_address_range_check(bind_engine=test_engine)


def _seed_regions() -> None:
    from models.region import Region

    defaults = [
        ("NORMAL", "عادی", "منطقه عادی بدون شرایط خاص", 30, 1),
        ("GRADE_1", "درجه یک", "منطقه بد آب و هوا درجه یک", 35, 2),
        ("GRADE_2", "درجه دو", "منطقه بد آب و هوا درجه دو", 40, 3),
        ("GRADE_3", "درجه سه", "منطقه بد آب و هوا درجه سه", 45, 4),
    ]
    session = TestingSessionLocal()
    try:
        for code, name, desc, days, order in defaults:
            if not session.query(Region).filter(Region.code == code).first():
                session.add(
                    Region(
                        code=code,
                        name=name,
                        description=desc,
                        default_annual_leave_days=days,
                        is_active=True,
                        sort_order=order,
                    )
                )
        session.commit()
    finally:
        session.close()


_seed_regions()


def _seed_travel_leave_data() -> None:
    """Seed cities and contract-scoped travel leave policies (idempotent)."""
    from models.city import City
    from models.contract import CONTRACT_TYPES
    from models.travel_leave_policy import TravelLeavePolicy
    from models.travel_leave_policy_rules import (
        TravelLeavePolicyRule,
        TravelLeaveQuotaSetting,
    )

    session = TestingSessionLocal()
    try:
        if session.query(City).count() == 0:
            session.add_all([
                City(name="Tehran", province="Tehran", latitude=35.6892, longitude=51.3890),
                City(name="Mashhad", province="Razavi Khorasan", latitude=36.2972, longitude=59.6067),
                City(name="Isfahan", province="Isfahan", latitude=32.6546, longitude=51.6680),
                City(name="Shiraz", province="Fars", latitude=29.5918, longitude=52.5836),
                City(name="Tabriz", province="East Azerbaijan", latitude=38.0800, longitude=46.2919),
            ])
            session.commit()

        for contract_type_code in CONTRACT_TYPES:
            policy = session.query(TravelLeavePolicy).filter(
                TravelLeavePolicy.contract_type_code == contract_type_code
            ).first()
            if not policy:
                policy = TravelLeavePolicy(
                    contract_type_code=contract_type_code,
                    is_enabled=True,
                    distance_method="geographic",
                    description="Test travel leave policy",
                )
                session.add(policy)
                session.flush()

            if not policy.rules:
                session.add_all([
                    TravelLeavePolicyRule(
                        policy_id=policy.id,
                        min_km=0.0,
                        max_km=199.99,
                        travel_days=0,
                        description="Below 200 km",
                        is_active=1,
                    ),
                    TravelLeavePolicyRule(
                        policy_id=policy.id,
                        min_km=200.0,
                        max_km=500.0,
                        travel_days=1,
                        description="200-500 km",
                        is_active=1,
                    ),
                    TravelLeavePolicyRule(
                        policy_id=policy.id,
                        min_km=500.01,
                        max_km=1500.0,
                        travel_days=2,
                        description="501-1500 km",
                        is_active=1,
                    ),
                    TravelLeavePolicyRule(
                        policy_id=policy.id,
                        min_km=1500.01,
                        max_km=99999.0,
                        travel_days=3,
                        description="Above 1500 km",
                        is_active=1,
                    ),
                ])

            if not policy.quota_settings:
                session.add_all([
                    TravelLeaveQuotaSetting(
                        policy_id=policy.id,
                        marital_status="S",
                        annual_max_usage=3,
                        description="Max travel leave uses per Jalali year",
                        parameter_key="annual_max_usage",
                        parameter_value="3",
                    ),
                    TravelLeaveQuotaSetting(
                        policy_id=policy.id,
                        marital_status="M",
                        annual_max_usage=3,
                        description="Max travel leave uses per Jalali year",
                        parameter_key="annual_max_usage",
                        parameter_value="3",
                    ),
                ])

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_seed_travel_leave_data()


# ---------------------------------------------------------------------------
# pytest run-status hook (feeds the admin dashboard banner)
# ---------------------------------------------------------------------------
_session_start = None


def pytest_sessionstart(session):
    global _session_start
    _session_start = time.monotonic()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    try:
        stats = terminalreporter.stats or {}
        passed = len(stats.get("passed", []))
        failed = len(stats.get("failed", []))
        errors = len(stats.get("error", []))
        skipped = len(stats.get("skipped", []))
        failed_tests = [r.nodeid for r in stats.get("failed", [])]
        failed_tests += [r.nodeid for r in stats.get("error", [])]
        error_details = []
        for r in stats.get("error", [])[:3]:
            try:
                text = str(getattr(r, "longreprtext",
                                   getattr(r, "longrepr", "")))
            except Exception:
                text = ""
            text = text.strip().splitlines()
            error_details.append("\n".join(text[-12:])[:1500])
        total = passed + failed + errors + skipped
        duration = (
            round(time.monotonic() - _session_start, 2)
            if _session_start
            else 0.0
        )
        now = datetime.now()
        try:
            ran_at_j = jdatetime.datetime.fromgregorian(datetime=now).strftime(
                "%Y/%m/%d %H:%M"
            )
        except Exception:
            ran_at_j = now.strftime("%Y-%m-%d %H:%M")
        payload = {
            "ran_at": now.isoformat(timespec="seconds"),
            "ran_at_j": ran_at_j,
            "duration_s": duration,
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "success": bool(total > 0 and failed == 0 and errors == 0
                            and exitstatus == 0),
            "failed_tests": failed_tests[:20],
            "error_details": error_details,
            "args": [str(a) for a in (config.args or [])],
        }
        status_path = _status_path()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = status_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_path.replace(status_path)
        try:
            _running_marker().unlink(missing_ok=True)
        except OSError:
            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_seq_base = int(time.time() * 1000) % 100000000
_seq = itertools.count(_seq_base)


@pytest.fixture()
def db():
    """Direct test-DB session (for seeding and assertions)."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_test_db():
    """Clean up test database before and after each test."""
    from models.user import User
    from models.employee import Employee
    from models.employee_phone import EmployeePhone
    from models.password_reset import PasswordResetRequest
    
    session = TestingSessionLocal()
    try:
        session.query(PasswordResetRequest).delete()
        session.query(EmployeePhone).delete()
        session.query(Employee).delete()
        session.query(User).delete()
        session.commit()
    finally:
        session.close()
    
    yield
    
    session = TestingSessionLocal()
    try:
        session.query(PasswordResetRequest).delete()
        session.query(EmployeePhone).delete()
        session.query(Employee).delete()
        session.query(User).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def client():
    """HTTP client with get_db overridden to the test database."""
    from fastapi.testclient import TestClient

    from web.app import app
    from web.dependencies import get_db

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, follow_redirects=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db):
    """Factory creating isolated user+employee+contract rows."""
    from models.contract import Contract
    from models.employee import Employee
    from models.leave_balance import LeaveBalance
    from models.employee_region import EmployeeRegion
    from models.user import User
    from web.security import hash_password

    created_uids = []

    def _make(
            role="user",
            balance_al=30,
            department="4",
            web_enabled=True,
            region_code="NORMAL",
            contract_type_code="4",
            create_employee=True,
    ):
        n = next(_seq)
        user_id = f"TEST-{n}"
        national_code = str(9000000000 + (n % 99999999)).zfill(10)[-10:]
        user = User(
            user_id=user_id,
            name=f"Test User {n}",
            password_hash=hash_password(USER_PASSWORD),
            must_change_password=False,
            role=role,
            web_enabled=web_enabled,
        )
        db.add(user)

        # Attendance-policy tests create their own Employee row so they can
        # control department/policy resolution. Other tests need the standard
        # Employee fixture for authentication and Travel Leave integration.
        if create_employee:
            db.add(
                Employee(
                    user_id=user_id,
                    national_code=national_code,
                    first_name="تست",
                    last_name=str(n),
                    department=department,
                    is_active=True,
                    marital_status="S",
                    region_code=region_code,
                )
            )

        db.add(
            Contract(
                user_id=user_id,
                contract_type_code=contract_type_code,
                start_date=date(2020, 1, 1),
                end_date=None,
                annual_leave_days=30,
                sick_leave_days=0,
                service_deduction_days=0,
            )
        )

        if balance_al is not None:
            year_j = jdatetime.date.today().year
            db.add(
                LeaveBalance(
                    user_id=user_id, year=year_j,
                    leave_type="AL", balance=balance_al,
                )
            )
        db.commit()
        created_uids.append(user_id)
        return {
            "user_id": user_id,
            "national_code": national_code,
            "password": USER_PASSWORD,
            "role": role,
        }

    yield _make

    for uid in created_uids:
        try:
            db.query(EmployeeRegion).filter(
                EmployeeRegion.user_id == uid).delete()
            db.query(User).filter(User.user_id == uid).delete()
            db.commit()
        except Exception:
            db.rollback()
    # Remove policy rows created by policy tests is handled inside those tests.


def login_as(client, national_code, password=USER_PASSWORD):
    """Log in through the real /login endpoint (keeps session cookies)."""
    return client.post(
        "/login",
        data={"national_code": national_code, "password": password},
        follow_redirects=False,
    )


def jalali_range(days_from_now_start=3, span=2):
    """Return (from_str, to_str) Jalali date strings safely in the future."""
    today_j = jdatetime.date.today()
    start = today_j + timedelta(days=days_from_now_start)
    end = start + timedelta(days=span)
    return start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d")
