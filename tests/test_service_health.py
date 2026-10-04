"""
Phase 1 tests for Service Monitoring storage (service_health).

Validates:
- model / table registration and PostgreSQL creation
- one row per service (web / adms / bale)
- CHECK validation for service_name / process_state / health_state
- nullable error fields and metrics blob
- idempotent seed_service_health
"""
import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from database.init_db import seed_service_health
from models import Base, ServiceHealth
from models.service_health import HEALTH_STATES, PROCESS_STATES, SERVICE_NAMES
from tests.conftest import TestingSessionLocal, test_engine


@pytest.fixture(autouse=True)
def _clean_service_health():
    """Isolate Phase 1 rows without touching shared conftest cleanup."""
    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = TestingSessionLocal()
    try:
        session.query(ServiceHealth).delete()
        session.commit()
    finally:
        session.close()


def test_table_registered_in_metadata():
    assert "service_health" in Base.metadata.tables
    assert ServiceHealth.__tablename__ == "service_health"


def test_table_created_in_test_db():
    inspector = sa_inspect(test_engine)
    assert "service_health" in inspector.get_table_names()


def test_required_columns_exist():
    columns = {
        c["name"] for c in sa_inspect(test_engine).get_columns("service_health")
    }
    required = {
        "service_name",
        "process_state",
        "health_state",
        "started_at",
        "last_heartbeat_at",
        "last_success_at",
        "last_error_at",
        "last_error_code",
        "last_error_summary",
        "metrics",
        "created_at",
        "updated_at",
    }
    assert required.issubset(columns)


def test_service_name_is_primary_key():
    pk_cols = sa_inspect(test_engine).get_pk_constraint("service_health")[
        "constrained_columns"
    ]
    assert pk_cols == ["service_name"]


@pytest.mark.parametrize("service_name", SERVICE_NAMES)
def test_each_service_can_be_stored(db, service_name):
    row = ServiceHealth(
        service_name=service_name,
        process_state="running",
        health_state="healthy",
    )
    db.add(row)
    db.commit()

    stored = db.get(ServiceHealth, service_name)
    assert stored is not None
    assert stored.service_name == service_name
    assert stored.process_state == "running"
    assert stored.health_state == "healthy"


def test_invalid_service_name_rejected(db):
    db.add(
        ServiceHealth(
            service_name="invalid",
            process_state="unknown",
            health_state="unknown",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("process_state", PROCESS_STATES)
def test_valid_process_states_accepted(db, process_state):
    row = ServiceHealth(
        service_name="web",
        process_state=process_state,
        health_state="unknown",
    )
    db.add(row)
    db.commit()
    assert db.get(ServiceHealth, "web").process_state == process_state


def test_invalid_process_state_rejected(db):
    db.add(
        ServiceHealth(
            service_name="web",
            process_state="crashed",
            health_state="unknown",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("health_state", HEALTH_STATES)
def test_valid_health_states_accepted(db, health_state):
    row = ServiceHealth(
        service_name="adms",
        process_state="unknown",
        health_state=health_state,
    )
    db.add(row)
    db.commit()
    assert db.get(ServiceHealth, "adms").health_state == health_state


def test_invalid_health_state_rejected(db):
    db.add(
        ServiceHealth(
            service_name="bale",
            process_state="unknown",
            health_state="critical",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_error_fields_and_metrics_nullable(db):
    row = ServiceHealth(
        service_name="bale",
        process_state="stopped",
        health_state="offline",
    )
    db.add(row)
    db.commit()

    stored = db.get(ServiceHealth, "bale")
    assert stored.last_error_code is None
    assert stored.last_error_summary is None
    assert stored.last_error_at is None
    assert stored.metrics is None
    assert stored.started_at is None
    assert stored.last_heartbeat_at is None
    assert stored.last_success_at is None


def test_error_summary_and_metrics_storage(db):
    row = ServiceHealth(
        service_name="web",
        process_state="running",
        health_state="degraded",
        last_error_code="db_timeout",
        last_error_summary="Database connection timed out",
        metrics='{"latency_ms": 120}',
    )
    db.add(row)
    db.commit()

    stored = db.get(ServiceHealth, "web")
    assert stored.last_error_code == "db_timeout"
    assert stored.last_error_summary == "Database connection timed out"
    assert stored.metrics == '{"latency_ms": 120}'


def test_seed_service_health_idempotent(db):
    seed_service_health(bind_engine=test_engine)
    seed_service_health(bind_engine=test_engine)

    rows = db.query(ServiceHealth).order_by(ServiceHealth.service_name).all()
    names = [r.service_name for r in rows]
    assert names == sorted(SERVICE_NAMES)
    assert all(r.process_state == "unknown" for r in rows)
    assert all(r.health_state == "unknown" for r in rows)


def test_seed_does_not_overwrite_existing_state(db):
    db.add(
        ServiceHealth(
            service_name="web",
            process_state="running",
            health_state="healthy",
            last_error_summary="keep-me",
        )
    )
    db.commit()

    seed_service_health(bind_engine=test_engine)

    stored = db.get(ServiceHealth, "web")
    assert stored.process_state == "running"
    assert stored.health_state == "healthy"
    assert stored.last_error_summary == "keep-me"
    # Remaining services still get initial rows
    assert db.get(ServiceHealth, "adms") is not None
    assert db.get(ServiceHealth, "bale") is not None


def test_one_row_per_service_enforced(db):
    db.add(
        ServiceHealth(
            service_name="web",
            process_state="running",
            health_state="healthy",
        )
    )
    db.commit()

    db.add(
        ServiceHealth(
            service_name="web",
            process_state="stopped",
            health_state="offline",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
