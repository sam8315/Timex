"""
Focused tests for the EmployeeAddress model foundation (Phase 1).

Validates:
- table/model registration
- FK relationship to users.user_id
- important DB-level constraints
- nullable geographic fields
- multiple addresses per employee
"""
from datetime import date

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from models import Base
from models.employee_address import EmployeeAddress
from tests.conftest import test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_address(
    user_id,
    address_type="HOME",
    residence_status="owner",
    province="Tehran",
    city="Tehran",
    district="Central",
    postal_code="1234567890",
    address="خیابان آزادی، تهران",
    is_primary=True,
    latitude=None,
    longitude=None,
    valid_from=None,
    valid_to=None,
    notes=None,
    gnaf_id=None,
):
    return EmployeeAddress(
        user_id=user_id,
        address_type=address_type,
        residence_status=residence_status,
        province=province,
        city=city,
        district=district,
        postal_code=postal_code,
        address=address,
        is_primary=is_primary,
        latitude=latitude,
        longitude=longitude,
        valid_from=valid_from,
        valid_to=valid_to,
        notes=notes,
        gnaf_id=gnaf_id,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_table_registered_in_metadata():
    """employee_addresses must be registered in Base.metadata."""
    assert "employee_addresses" in Base.metadata.tables


def test_table_created_in_test_db():
    """The table must actually exist in the test database after create_all."""
    inspector = sa_inspect(test_engine)
    assert "employee_addresses" in inspector.get_table_names()


def test_required_columns_exist(db):
    """All required and optional columns must be present."""
    columns = {
        c["name"]
        for c in sa_inspect(db.bind).get_columns("employee_addresses")
    }
    required = {
        "id", "user_id", "address_type", "residence_status", "province",
        "city", "district", "postal_code", "address", "is_primary",
        "gnaf_id", "latitude", "longitude", "valid_from", "valid_to", "notes",
    }
    assert required.issubset(columns)


# ---------------------------------------------------------------------------
# FK relationship
# ---------------------------------------------------------------------------

def test_fk_relationship_to_user(db, make_user):
    """EmployeeAddress links to users.user_id with CASCADE delete."""
    user = make_user(role="user", balance_al=None)
    addr = _make_address(user["user_id"])
    db.add(addr)
    db.commit()

    assert addr.id is not None
    assert addr.user_id == user["user_id"]

    # Verify FK constraint on user_id -> users.user_id
    fks = sa_inspect(db.bind).get_foreign_keys("employee_addresses")
    assert any(
        f["referred_table"] == "users"
        and f["referred_columns"] == ["user_id"]
        and "user_id" in f["constrained_columns"]
        for f in fks
    )


def test_cascade_delete_on_user_removal(db, make_user):
    """Deleting a user should cascade-delete their addresses."""
    from models.user import User

    user = make_user(role="user", balance_al=None)
    addr = _make_address(user["user_id"])
    db.add(addr)
    db.commit()
    addr_id = addr.id

    db.query(User).filter(User.user_id == user["user_id"]).delete(
        synchronize_session=False
    )
    db.commit()

    assert db.query(EmployeeAddress).filter(EmployeeAddress.id == addr_id).first() is None


# ---------------------------------------------------------------------------
# Multiple addresses / is_primary
# ---------------------------------------------------------------------------

def test_multiple_addresses_per_user(db, make_user):
    """One user can have multiple addresses."""
    user = make_user(role="user", balance_al=None)
    db.add_all([
        _make_address(user["user_id"], address_type="HOME", is_primary=True,
                       postal_code="1111111111"),
        _make_address(user["user_id"], address_type="WORK", is_primary=False,
                       postal_code="2222222222"),
    ])
    db.commit()

    count = db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user["user_id"]
    ).count()
    assert count == 2


def test_single_primary_per_user(db, make_user):
    """Only one is_primary=True address per user is allowed."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], postal_code="1111111111"))
    db.commit()

    db.add(_make_address(
        user["user_id"], address_type="WORK", postal_code="2222222222"
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_multiple_non_primary_allowed(db, make_user):
    """Multiple non-primary addresses per user are allowed."""
    user = make_user(role="user", balance_al=None)
    db.add_all([
        _make_address(user["user_id"], is_primary=False, postal_code="1111111111"),
        _make_address(user["user_id"], address_type="WORK",
                       is_primary=False, postal_code="2222222222"),
    ])
    db.commit()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user["user_id"]
    ).count() == 2


# ---------------------------------------------------------------------------
# Validation / constraints
# ---------------------------------------------------------------------------

def test_invalid_postal_code_rejected(db, make_user):
    """postal_code must be exactly 10 digits."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], postal_code="12345"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_non_digit_postal_code_rejected(db, make_user):
    """postal_code with letters is rejected."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], postal_code="ABCDEFGHIJ"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_valid_postal_code_accepted(db, make_user):
    """A 10-digit postal_code is accepted."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], postal_code="1111111111"))
    db.commit()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "1111111111"
    ).count() == 1


def test_invalid_latitude_rejected(db, make_user):
    """latitude outside -90..90 is rejected."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], latitude=91))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_longitude_rejected(db, make_user):
    """longitude outside -180..180 is rejected."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(user["user_id"], longitude=181))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_null_geographic_fields(db, make_user):
    """latitude and longitude can both be NULL."""
    user = make_user(role="user", balance_al=None)
    addr = _make_address(user["user_id"])
    db.add(addr)
    db.commit()

    db.expire_all()
    loaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == addr.id).one()
    assert loaded.latitude is None
    assert loaded.longitude is None


def test_valid_latitude_longitude_accepted(db, make_user):
    """Valid latitude/longitude values are accepted."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(
        user["user_id"], latitude=35.6892, longitude=51.3890,
        postal_code="3333333333",
    ))
    db.commit()

    db.expire_all()
    loaded = db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user["user_id"]
    ).first()
    assert float(loaded.latitude) == 35.6892
    assert float(loaded.longitude) == 51.3890


def test_validity_range_rejects_inverted(db, make_user):
    """valid_to earlier than valid_from is rejected."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(
        user["user_id"], postal_code="4444444444",
        valid_from=date(2024, 6, 1), valid_to=date(2024, 5, 1),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_validity_range_accepts_null_dates(db, make_user):
    """NULL valid_to with valid_from present is allowed."""
    user = make_user(role="user", balance_al=None)
    db.add(_make_address(
        user["user_id"], postal_code="5555555555",
        valid_from=date(2024, 1, 1), valid_to=None,
    ))
    db.commit()
    assert db.query(EmployeeAddress).count() >= 1


def test_invalid_address_type_rejected(db, make_user):
    """An unknown address_type is rejected by the CHECK constraint."""
    user = make_user(role="user", balance_al=None)
    addr = _make_address(user["user_id"])
    addr.address_type = "INVALID"
    db.add(addr)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_address_type_normalization(db, make_user):
    """Lowercase address_type is upper-cased by the validator."""
    user = make_user(role="user", balance_al=None)
    addr = _make_address(user["user_id"], address_type="home")
    db.add(addr)
    db.commit()
    db.expire_all()
    assert db.query(EmployeeAddress).filter(EmployeeAddress.id == addr.id).one().address_type == "HOME"


def test_residence_status_values(db, make_user):
    """All valid residence_status values are accepted."""
    user = make_user(role="user", balance_al=None)
    statuses = ["owner", "tenant", "family", "org_housing", "provided", "other", "unknown"]
    for i, status in enumerate(statuses):
        db.add(_make_address(
            user["user_id"], postal_code=f"{1000000000 + i:010d}",
            residence_status=status, is_primary=False,
        ))
    db.commit()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user["user_id"]
    ).count() == len(statuses)
