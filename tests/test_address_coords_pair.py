"""
Focused tests for complete coordinate pairs.

Covers:
- create with both/neither coordinates
- create with only one side rejected
- update both / clear both / single-sided / omitted
- model CHECK constraint exists
- migration is idempotent and fails safely on partial data
"""
import math

import pytest
from sqlalchemy import text as sa_text

from models.employee_address import EmployeeAddress
from web.services.address_service import (
    AddressServiceError, create_address, update_address,
)
from database.init_db import (
    migrate_employee_address_coords_pair,
    migrate_employee_address_nan_check,
)

from .conftest import test_engine


def _make_addr(db, user_id, **overrides):
    defaults = dict(
        address_type="HOME",
        residence_status="owner",
        province="Tehran",
        city="Tehran",
        postal_code="1234567890",
        address_text="خیابان آزادی، تهران",
        is_primary=False,
    )
    defaults.update(overrides)
    return create_address(db, user_id=user_id, **defaults)


def _has_pair_check():
    with test_engine.connect() as conn:
        return conn.execute(sa_text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'ck_employee_address_coords_pair' "
            "AND conrelid = 'employee_addresses'::regclass")).scalar()


# ---------------------------------------------------------------------------
# Service: create
# ---------------------------------------------------------------------------

def test_create_with_both_coords(db, make_user):
    """Both coordinates are stored."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666601",
                      latitude=35.6892, longitude=51.3890)
    assert float(addr.latitude) == 35.6892
    assert float(addr.longitude) == 51.3890


def test_create_with_neither_coords(db, make_user):
    """Both NULL is valid."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666602")
    assert addr.latitude is None
    assert addr.longitude is None


@pytest.mark.parametrize("kwargs", [
    {"latitude": 35.6892},
    {"longitude": 51.3890},
])
def test_create_single_sided_rejected(db, make_user, kwargs):
    """Exactly one coordinate is rejected."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="با هم"):
        _make_addr(db, user["user_id"], postal_code="6666666603", **kwargs)


# ---------------------------------------------------------------------------
# Service: update (_UNSET-aware)
# ---------------------------------------------------------------------------

def test_update_both_coords(db, make_user):
    """Setting both coordinates works."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666604")
    updated = update_address(db, user["user_id"], addr.id,
                             latitude=36.2972, longitude=59.6067)
    assert float(updated.latitude) == 36.2972
    assert float(updated.longitude) == 59.6067


def test_update_both_none_clears_pair(db, make_user):
    """Both None clears the pair."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666605",
                      latitude=35.6892, longitude=51.3890)
    updated = update_address(db, user["user_id"], addr.id,
                             latitude=None, longitude=None)
    assert updated.latitude is None
    assert updated.longitude is None


def test_update_single_value_with_stored_pair(db, make_user):
    """Changing one side while the other stays stored is consistent."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666606",
                      latitude=35.6892, longitude=51.3890)
    updated = update_address(db, user["user_id"], addr.id, latitude=36.0)
    assert float(updated.latitude) == 36.0
    assert float(updated.longitude) == 51.3890


def test_update_single_clear_with_stored_pair_rejected(db, make_user):
    """Clearing one side while omitting the other is rejected."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666607",
                      latitude=35.6892, longitude=51.3890)
    with pytest.raises(AddressServiceError, match="با هم"):
        update_address(db, user["user_id"], addr.id, latitude=None)
    db.expire_all()
    kept = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert float(kept.latitude) == 35.6892
    assert float(kept.longitude) == 51.3890


def test_update_omitted_preserves_pair(db, make_user):
    """Omitting both coordinates preserves the stored pair."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666608",
                      latitude=35.6892, longitude=51.3890)
    updated = update_address(db, user["user_id"], addr.id, province="Fars")
    assert float(updated.latitude) == 35.6892
    assert float(updated.longitude) == 51.3890


# ---------------------------------------------------------------------------
# Model CHECK + migration
# ---------------------------------------------------------------------------

def test_pair_check_constraint_exists(db):
    """The pair CHECK is registered in metadata and in the database."""
    from models import Base
    table = Base.metadata.tables["employee_addresses"]
    names = {c.name for c in table.constraints
             if getattr(c, "name", None)}
    assert "ck_employee_address_coords_pair" in names
    assert _has_pair_check() is not None


def test_migration_idempotent_and_preserves_data(db, make_user):
    """Repeated runs keep one CHECK and do not touch coordinate data."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="6666666609",
                      latitude=35.6892, longitude=51.3890)

    migrate_employee_address_coords_pair(bind_engine=test_engine)
    migrate_employee_address_coords_pair(bind_engine=test_engine)

    with test_engine.connect() as conn:
        count = conn.execute(sa_text(
            "SELECT COUNT(*) FROM pg_constraint "
            "WHERE conname = 'ck_employee_address_coords_pair'")).scalar()
    assert count == 1
    db.expire_all()
    kept = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert float(kept.latitude) == 35.6892
    assert float(kept.longitude) == 51.3890


def test_migration_creates_check_when_missing(db):
    """A missing CHECK is added by the migration."""
    # DDL on the test session itself (avoids self-deadlock, see history).
    db.execute(sa_text(
        "ALTER TABLE employee_addresses "
        "DROP CONSTRAINT IF EXISTS ck_employee_address_coords_pair"))
    db.commit()
    assert _has_pair_check() is None

    migrate_employee_address_coords_pair(bind_engine=test_engine)
    assert _has_pair_check() is not None


def test_migration_fails_safely_on_partial_data(db, make_user):
    """Partial rows block the migration without being modified."""
    user = make_user(role="user", balance_al=None)
    db.execute(sa_text(
        "ALTER TABLE employee_addresses "
        "DROP CONSTRAINT IF EXISTS ck_employee_address_coords_pair"))
    db.commit()
    db.execute(sa_text(
        "INSERT INTO employee_addresses "
        "(user_id, address_type, residence_status, province, city, "
        " postal_code, address, is_primary, latitude, longitude) "
        "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
        " '6666666610', 'x', false, 35.6892, NULL)"),
        {"uid": user["user_id"]})
    db.commit()
    try:
        with pytest.raises(RuntimeError, match="manually"):
            migrate_employee_address_coords_pair(bind_engine=test_engine)
        # row untouched, constraint still absent
        row = db.query(EmployeeAddress).filter(
            EmployeeAddress.postal_code == "6666666610").one()
        assert float(row.latitude) == 35.6892
        assert row.longitude is None
        assert _has_pair_check() is None
    finally:
        db.query(EmployeeAddress).filter(
            EmployeeAddress.postal_code == "6666666610").delete(
                synchronize_session=False)
        db.commit()
        migrate_employee_address_coords_pair(bind_engine=test_engine)
        assert _has_pair_check() is not None


def test_migration_ignores_same_named_constraint_elsewhere(db):
    """A same-named CHECK on another table must not fool the migration."""
    db.execute(sa_text(
        "ALTER TABLE employee_addresses "
        "DROP CONSTRAINT IF EXISTS ck_employee_address_coords_pair"))
    db.commit()
    db.execute(sa_text(
        "CREATE TABLE tmp_pair_check_probe ("
        "id INTEGER, "
        "CONSTRAINT ck_employee_address_coords_pair CHECK (id > 0))"))
    db.commit()
    try:
        # scoped check still reports the constraint as missing here ...
        assert _has_pair_check() is None
        migrate_employee_address_coords_pair(bind_engine=test_engine)
        # ... and the migration adds it to employee_addresses regardless
        assert _has_pair_check() is not None
    finally:
        db.execute(sa_text("DROP TABLE IF EXISTS tmp_pair_check_probe"))
        db.commit()
        migrate_employee_address_coords_pair(bind_engine=test_engine)
        assert _has_pair_check() is not None


# ---------------------------------------------------------------------------
# DB-level NaN rejection (Phase 21 / 22)
# ---------------------------------------------------------------------------

def test_db_rejects_nan_latitude(db, make_user):
    """Direct DB insertion of NaN latitude is rejected by CHECK."""
    from sqlalchemy import exc as sa_exc
    user = make_user(role="user", balance_al=None)
    with pytest.raises(sa_exc.DatabaseError):
        db.execute(sa_text(
            "INSERT INTO employee_addresses "
            "(user_id, address_type, residence_status, province, city, "
            "postal_code, address, is_primary, latitude, longitude) "
            "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
            "'1234567890', 'test', false, 'NaN', NULL)"
        ), {"uid": user["user_id"]})
        db.commit()


def test_db_rejects_nan_longitude(db, make_user):
    """Direct DB insertion of NaN longitude is rejected by CHECK."""
    from sqlalchemy import exc as sa_exc
    user = make_user(role="user", balance_al=None)
    with pytest.raises(sa_exc.DatabaseError):
        db.execute(sa_text(
            "INSERT INTO employee_addresses "
            "(user_id, address_type, residence_status, province, city, "
            "postal_code, address, is_primary, latitude, longitude) "
            "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
            "'1234567891', 'test', false, NULL, 'NaN')"
        ), {"uid": user["user_id"]})
        db.commit()


def test_db_accepts_null_coordinates(db, make_user):
    """NULL coordinates remain valid via the DB CHECK."""
    user = make_user(role="user", balance_al=None)
    db.execute(sa_text(
        "INSERT INTO employee_addresses "
        "(user_id, address_type, residence_status, province, city, "
        "postal_code, address, is_primary, latitude, longitude) "
        "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
        "'1234567892', 'test', false, NULL, NULL)"
    ), {"uid": user["user_id"]})
    db.commit()
    count = db.execute(sa_text(
        "SELECT COUNT(*) FROM employee_addresses "
        "WHERE postal_code = '1234567892'"
    )).scalar_one()
    assert count == 1


def test_db_accepts_valid_finite_pair(db, make_user):
    """Valid finite coordinate pairs remain valid via the DB CHECK."""
    user = make_user(role="user", balance_al=None)
    db.execute(sa_text(
        "INSERT INTO employee_addresses "
        "(user_id, address_type, residence_status, province, city, "
        "postal_code, address, is_primary, latitude, longitude) "
        "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
        "'1234567893', 'test', false, 35.6892, 51.3890)"
    ), {"uid": user["user_id"]})
    db.commit()
    count = db.execute(sa_text(
        "SELECT COUNT(*) FROM employee_addresses "
        "WHERE postal_code = '1234567893'"
    )).scalar_one()
    assert count == 1


def test_migration_detects_existing_nan(db, make_user):
    """Migration fails clearly when NaN rows exist; rows are not modified."""
    user = make_user(role="user", balance_al=None)
    # Drop ALL coordinate constraints to allow NaN insertion for testing
    for c in [
        "ck_employee_address_latitude_range",
        "ck_employee_address_longitude_range",
        "ck_employee_address_coords_pair",
        "ck_employee_address_latitude_not_nan",
        "ck_employee_address_longitude_not_nan",
    ]:
        db.execute(sa_text(
            f"ALTER TABLE employee_addresses "
            f"DROP CONSTRAINT IF EXISTS {c}"))
    db.commit()
    db.execute(sa_text(
        "INSERT INTO employee_addresses "
        "(user_id, address_type, residence_status, province, city, "
        " postal_code, address, is_primary, latitude, longitude) "
        "VALUES (:uid, 'HOME', 'owner', 'Tehran', 'Tehran', "
        " '7777777777', 'x', false, 'NaN', 51.0)"),
        {"uid": user["user_id"]})
    db.commit()
    try:
        with pytest.raises(RuntimeError, match="NaN"):
            migrate_employee_address_nan_check(bind_engine=test_engine)
        # row untouched
        row = db.query(EmployeeAddress).filter(
            EmployeeAddress.postal_code == "7777777777").one()
        assert math.isnan(float(row.latitude))
        assert float(row.longitude) == 51.0
        # constraints still absent
        with test_engine.connect() as conn:
            lat_check = conn.execute(sa_text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'ck_employee_address_latitude_not_nan'")).scalar()
            lon_check = conn.execute(sa_text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'ck_employee_address_longitude_not_nan'")).scalar()
        assert lat_check is None
        assert lon_check is None
    finally:
        db.query(EmployeeAddress).filter(
            EmployeeAddress.postal_code == "7777777777").delete(
                synchronize_session=False)
        db.commit()
        # restore constraints so other tests are not affected
        migrate_employee_address_nan_check(bind_engine=test_engine)
        assert _has_nan_check("ck_employee_address_latitude_not_nan")
        assert _has_nan_check("ck_employee_address_longitude_not_nan")


def test_migration_nan_is_idempotent(db):
    """Repeated migration runs are safe once constraints exist."""
    migrate_employee_address_nan_check(bind_engine=test_engine)
    migrate_employee_address_nan_check(bind_engine=test_engine)
    with test_engine.connect() as conn:
        lat_count = conn.execute(sa_text(
            "SELECT COUNT(*) FROM pg_constraint "
            "WHERE conname = 'ck_employee_address_latitude_not_nan'")).scalar_one()
        lon_count = conn.execute(sa_text(
            "SELECT COUNT(*) FROM pg_constraint "
            "WHERE conname = 'ck_employee_address_longitude_not_nan'")).scalar_one()
    assert lat_count == 1
    assert lon_count == 1


def _has_nan_check(name: str):
    with test_engine.connect() as conn:
        return conn.execute(sa_text(
            f"SELECT 1 FROM pg_constraint "
            f"WHERE conname = '{name}' "
            f"AND conrelid = 'employee_addresses'::regclass")).scalar()
