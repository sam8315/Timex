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
from datetime import datetime, timedelta
from pathlib import Path

import jdatetime
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

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
from sqlalchemy import text as _sql_text

# ---------------------------------------------------------------------------
# Legacy-schema migration (explicit, conditional)
# ---------------------------------------------------------------------------
# Prior branches (PR #14) created `travel_leave_details` with an incompatible
# schema. `create_all` never alters existing tables, so a legacy table would
# silently differ. We detect it by missing current columns and drop ONLY that
# table; `create_all` below rebuilds it from the model. Fresh databases are
# unaffected (the table doesn't exist yet).
from sqlalchemy import inspect as _sa_inspect  # noqa: E402


def _column_names(conn, table: str) -> set:
    if table not in _sa_inspect(conn).get_table_names():
        return set()
    return {c["name"] for c in _sa_inspect(conn).get_columns(table)}


with test_engine.connect() as _conn:
    # PR-14 travel_leave_details → drop only when its schema is stale.
    tl_cols = _column_names(_conn, "travel_leave_details")
    current_tl = {
        "final_travel_days", "manual_override", "jalali_year",
        "destination_latitude_snapshot", "destination_longitude_snapshot",
    }
    if tl_cols and not current_tl.issubset(tl_cols):
        _conn.execute(_sql_text("DROP TABLE travel_leave_details CASCADE"))
        _conn.commit()

    # Legacy cities table used `active` before the model renamed it to
    # `is_active`; fix in place so the model and seeds agree.
    city_cols = _column_names(_conn, "cities")
    if "active" in city_cols and "is_active" not in city_cols:
        _conn.execute(_sql_text("ALTER TABLE cities RENAME COLUMN active TO is_active"))
        _conn.commit()

Base.metadata.create_all(bind=test_engine)

# Phase 7: HL columns on a pre-existing leave_requests table
# (idempotent; fresh tables already carry these columns via the model)
with test_engine.connect() as _conn:
    _conn.execute(_sql_text("""
        ALTER TABLE leave_requests
        ADD COLUMN IF NOT EXISTS start_time TIME,
        ADD COLUMN IF NOT EXISTS end_time TIME
    """))
    _conn.commit()


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
    """Seed cities and travel leave policy rules for tests (idempotent)."""
    from models.city import City
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

        if session.query(TravelLeavePolicyRule).count() == 0:
            session.add_all([
                TravelLeavePolicyRule(min_km=0.0, max_km=199.99, travel_days=0,
                                      description="Below 200 km", is_active=1),
                TravelLeavePolicyRule(min_km=200.0, max_km=500.0, travel_days=1,
                                      description="200-500 km", is_active=1),
                TravelLeavePolicyRule(min_km=500.01, max_km=1500.0, travel_days=2,
                                      description="501-1500 km", is_active=1),
                TravelLeavePolicyRule(min_km=1500.01, max_km=99999.0, travel_days=3,
                                      description="Above 1500 km", is_active=1),
            ])
            session.commit()

        if session.query(TravelLeaveQuotaSetting).count() == 0:
            session.add(TravelLeaveQuotaSetting(
                annual_max_usage=3,
                description="Max travel leave uses per Jalali year",
                parameter_key="annual_max_usage",
                parameter_value="3",
            ))
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
        # متن خطاها (مخصوصاً خطاهای setup) برای عیب‌یابی روی سرور ریموت
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
        # Never break the test suite because of status reporting.
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
    """Factory creating isolated user+employee rows (cleaned up afterwards)."""
    from models.employee import Employee
    from models.leave_balance import LeaveBalance
    from models.employee_region import EmployeeRegion
    from models.user import User
    from web.security import hash_password

    created_uids = []

    def _make(role="user", balance_al=30, department="4",
              web_enabled=True, region_code="NORMAL"):
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
        db.add(
            Employee(
                user_id=user_id,
                national_code=national_code,
                first_name="تست",
                last_name=str(n),
                department=department,
                is_active=True,
                region_code=region_code,
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
