"""
Focused tests for the EmployeeAddress service layer (Phase 2).

Covers:
- list addresses
- get address
- create address
- update address
- delete address
- set primary address
- replacing an existing primary address
- nonexistent address
- cross-user access protection
- multiple addresses for one user
- address history fields (valid_from / valid_to)
"""
from datetime import date

import pytest

from models.employee_address import EmployeeAddress
from web.services.address_service import (
    AddressServiceError,
    list_addresses,
    get_address,
    create_address,
    update_address,
    delete_address,
    set_primary_address,
    get_primary_address,
    _UNSET,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_addr(db, user_id, **overrides):
    """Create and return an address via the service."""
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


# ---------------------------------------------------------------------------
# List addresses
# ---------------------------------------------------------------------------

def test_list_addresses_empty(db, make_user):
    """User with no addresses returns empty list."""
    user = make_user(role="user", balance_al=None)
    result = list_addresses(db, user["user_id"])
    assert result == []


def test_list_addresses_returns_all(db, make_user):
    """All addresses for a user are returned."""
    user = make_user(role="user", balance_al=None)
    _create_addr(db, user["user_id"], address_type="HOME", postal_code="1111111111")
    _create_addr(db, user["user_id"], address_type="WORK", postal_code="2222222222")
    result = list_addresses(db, user["user_id"])
    assert len(result) == 2


def test_list_addresses_ordered_by_primary_then_created(db, make_user):
    """Primary address appears first."""
    user = make_user(role="user", balance_al=None)
    _create_addr(db, user["user_id"], is_primary=False, postal_code="1111111111")
    _create_addr(db, user["user_id"], is_primary=True, postal_code="2222222222")
    _create_addr(db, user["user_id"], is_primary=False, postal_code="3333333333")
    result = list_addresses(db, user["user_id"])
    assert result[0].is_primary is True
    assert result[0].postal_code == "2222222222"


def test_list_addresses_nonexistent_user_raises(db):
    """Listing addresses for a nonexistent user raises AddressServiceError."""
    with pytest.raises(AddressServiceError, match="کاربر یافت نشد"):
        list_addresses(db, "NONEXISTENT-USER")


# ---------------------------------------------------------------------------
# Get address
# ---------------------------------------------------------------------------

def test_get_address_by_id(db, make_user):
    """Retrieve a single address by ID."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111")
    result = get_address(db, user["user_id"], addr.id)
    assert result.id == addr.id
    assert result.postal_code == "1111111111"


def test_get_address_nonexistent_raises(db, make_user):
    """Getting a nonexistent address raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        get_address(db, user["user_id"], 999999)


def test_get_address_cross_user_denied(db, make_user):
    """User A cannot retrieve User B's address by knowing the ID."""
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user_b["user_id"], postal_code="1111111111")
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        get_address(db, user_a["user_id"], addr.id)


# ---------------------------------------------------------------------------
# Create address
# ---------------------------------------------------------------------------

def test_create_address_basic(db, make_user):
    """Creating a valid address stores it correctly."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111")
    assert addr.id is not None
    assert addr.user_id == user["user_id"]
    assert addr.address_type == "HOME"
    assert addr.postal_code == "1111111111"


def test_create_address_with_district_optional(db, make_user):
    """District is optional — can be None."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", district=None)
    assert addr.district is None


def test_create_address_invalid_type_raises(db, make_user):
    """Invalid address_type raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="نوع آدرس نامعتبر"):
        _create_addr(db, user["user_id"], address_type="INVALID")


def test_create_address_invalid_residence_status_raises(db, make_user):
    """Invalid residence_status raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="وضعیت اقامت نامعتبر"):
        _create_addr(db, user["user_id"], residence_status="invalid")


def test_create_address_invalid_postal_code_raises(db, make_user):
    """Invalid postal code raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="کد پستی"):
        _create_addr(db, user["user_id"], postal_code="123")


def test_create_address_invalid_latitude_raises(db, make_user):
    """Latitude outside range raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="عرض جغرافیایی"):
        _create_addr(db, user["user_id"], latitude=91)


def test_create_address_invalid_longitude_raises(db, make_user):
    """Longitude outside range raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="طول جغرافیایی"):
        _create_addr(db, user["user_id"], longitude=181)


def test_create_address_invalid_date_range_raises(db, make_user):
    """valid_to before valid_from raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="تاریخ پایان"):
        _create_addr(
            db, user["user_id"],
            valid_from=date(2024, 6, 1),
            valid_to=date(2024, 5, 1),
        )


def test_create_address_with_valid_date_range(db, make_user):
    """valid_to >= valid_from is accepted."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(
        db, user["user_id"],
        postal_code="1111111111",
        valid_from=date(2024, 1, 1),
        valid_to=date(2024, 12, 31),
    )
    assert addr.valid_from == date(2024, 1, 1)
    assert addr.valid_to == date(2024, 12, 31)


def test_create_address_is_primary_unsets_previous(db, make_user):
    """Setting is_primary=True unsets the previous primary."""
    user = make_user(role="user", balance_al=None)
    first = _create_addr(db, user["user_id"], is_primary=True, postal_code="1111111111")
    second = _create_addr(db, user["user_id"], is_primary=True, postal_code="2222222222")

    db.expire_all()
    first_reloaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == first.id).one()
    second_reloaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == second.id).one()

    assert first_reloaded.is_primary is False
    assert second_reloaded.is_primary is True


def test_create_address_nonexistent_user_raises(db):
    """Creating an address for a nonexistent user raises AddressServiceError."""
    with pytest.raises(AddressServiceError, match="کاربر یافت نشد"):
        create_address(
            db=db,
            user_id="NONEXISTENT",
            address_type="HOME",
            residence_status="owner",
            province="Tehran",
            city="Tehran",
            postal_code="1234567890",
            address_text="test",
        )


# ---------------------------------------------------------------------------
# Update address
# ---------------------------------------------------------------------------

def test_update_address_fields(db, make_user):
    """Updating specific fields changes only those fields."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", province="Tehran")

    updated = update_address(
        db, user["user_id"], addr.id,
        postal_code="9999999999",
        province="Isfahan",
    )
    assert updated.postal_code == "9999999999"
    assert updated.province == "Isfahan"
    assert updated.city == "Tehran"  # unchanged


def test_update_address_validates_type(db, make_user):
    """Updating with invalid address_type raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"])
    with pytest.raises(AddressServiceError, match="نوع آدرس نامعتبر"):
        update_address(db, user["user_id"], addr.id, address_type="BAD")


def test_update_address_validates_date_range(db, make_user):
    """Updating with inverted date range raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"])
    with pytest.raises(AddressServiceError, match="تاریخ پایان"):
        update_address(
            db, user["user_id"], addr.id,
            valid_from=date(2024, 6, 1),
            valid_to=date(2024, 5, 1),
        )


def test_update_address_nonexistent_raises(db, make_user):
    """Updating a nonexistent address raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        update_address(db, user["user_id"], 999999, province="New")


def test_update_address_cross_user_denied(db, make_user):
    """User A cannot update User B's address."""
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user_b["user_id"])
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        update_address(db, user_a["user_id"], addr.id, province="Hacked")


# ---------------------------------------------------------------------------
# Delete address
# ---------------------------------------------------------------------------

def test_delete_address(db, make_user):
    """Deleting an address removes it."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"])
    delete_address(db, user["user_id"], addr.id)
    assert db.query(EmployeeAddress).filter(EmployeeAddress.id == addr.id).first() is None


def test_delete_address_nonexistent_raises(db, make_user):
    """Deleting a nonexistent address raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        delete_address(db, user["user_id"], 999999)


def test_delete_address_cross_user_denied(db, make_user):
    """User A cannot delete User B's address."""
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user_b["user_id"])
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        delete_address(db, user_a["user_id"], addr.id)


# ---------------------------------------------------------------------------
# Set primary
# ---------------------------------------------------------------------------

def test_set_primary_address(db, make_user):
    """Setting an address as primary updates the flag."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], is_primary=False)
    result = set_primary_address(db, user["user_id"], addr.id)
    assert result.is_primary is True


def test_set_primary_replaces_existing_primary(db, make_user):
    """Setting a new primary unsets the old one."""
    user = make_user(role="user", balance_al=None)
    first = _create_addr(db, user["user_id"], is_primary=True, postal_code="1111111111")
    second = _create_addr(db, user["user_id"], is_primary=False, postal_code="2222222222")

    set_primary_address(db, user["user_id"], second.id)

    db.expire_all()
    first_reloaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == first.id).one()
    second_reloaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == second.id).one()

    assert first_reloaded.is_primary is False
    assert second_reloaded.is_primary is True


def test_set_primary_nonexistent_raises(db, make_user):
    """Setting a nonexistent address as primary raises AddressServiceError."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        set_primary_address(db, user["user_id"], 999999)


def test_set_primary_cross_user_denied(db, make_user):
    """User A cannot set User B's address as primary."""
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user_b["user_id"])
    with pytest.raises(AddressServiceError, match="آدرس یافت نشد"):
        set_primary_address(db, user_a["user_id"], addr.id)


# ---------------------------------------------------------------------------
# Get primary address
# ---------------------------------------------------------------------------

def test_get_primary_address(db, make_user):
    """get_primary_address returns the primary address."""
    user = make_user(role="user", balance_al=None)
    _create_addr(db, user["user_id"], is_primary=False, postal_code="1111111111")
    primary = _create_addr(db, user["user_id"], is_primary=True, postal_code="2222222222")

    result = get_primary_address(db, user["user_id"])
    assert result is not None
    assert result.id == primary.id


def test_get_primary_address_none_when_no_primary(db, make_user):
    """Returns None when no primary address exists."""
    user = make_user(role="user", balance_al=None)
    _create_addr(db, user["user_id"], is_primary=False)
    assert get_primary_address(db, user["user_id"]) is None


def test_get_primary_address_none_when_no_addresses(db, make_user):
    """Returns None when user has no addresses."""
    user = make_user(role="user", balance_al=None)
    assert get_primary_address(db, user["user_id"]) is None


# ---------------------------------------------------------------------------
# Address history fields
# ---------------------------------------------------------------------------

def test_address_history_valid_from_to(db, make_user):
    """valid_from and valid_to are stored and retrievable."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(
        db, user["user_id"],
        postal_code="1111111111",
        valid_from=date(2023, 1, 1),
        valid_to=date(2023, 12, 31),
    )
    assert addr.valid_from == date(2023, 1, 1)
    assert addr.valid_to == date(2023, 12, 31)


def test_address_history_null_dates(db, make_user):
    """valid_from and valid_to can both be None."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111")
    assert addr.valid_from is None
    assert addr.valid_to is None


def test_address_history_update_dates(db, make_user):
    """History dates can be updated after creation."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(
        db, user["user_id"],
        postal_code="1111111111",
        valid_from=date(2023, 1, 1),
        valid_to=date(2023, 12, 31),
    )
    updated = update_address(
        db, user["user_id"], addr.id,
        valid_from=date(2024, 1, 1),
        valid_to=date(2024, 12, 31),
    )
    assert updated.valid_from == date(2024, 1, 1)
    assert updated.valid_to == date(2024, 12, 31)


# ---------------------------------------------------------------------------
# Multiple addresses for one user
# ---------------------------------------------------------------------------

def test_multiple_addresses_crud(db, make_user):
    """Full CRUD lifecycle with multiple addresses."""
    user = make_user(role="user", balance_al=None)
    a1 = _create_addr(db, user["user_id"], address_type="HOME", postal_code="1111111111", is_primary=True)
    a2 = _create_addr(db, user["user_id"], address_type="WORK", postal_code="2222222222", is_primary=False)
    a3 = _create_addr(db, user["user_id"], address_type="MAILING", postal_code="3333333333", is_primary=False)

    all_addrs = list_addresses(db, user["user_id"])
    assert len(all_addrs) == 3

    # Update second address
    update_address(db, user["user_id"], a2.id, city="Mashhad")
    updated = get_address(db, user["user_id"], a2.id)
    assert updated.city == "Mashhad"

    # Set third as primary
    set_primary_address(db, user["user_id"], a3.id)
    primary = get_primary_address(db, user["user_id"])
    assert primary.id == a3.id

    # Delete first address
    delete_address(db, user["user_id"], a1.id)
    remaining = list_addresses(db, user["user_id"])
    assert len(remaining) == 2
    assert all(a.id != a1.id for a in remaining)


# ---------------------------------------------------------------------------
# District nullable
# ---------------------------------------------------------------------------

def test_district_nullable(db, make_user):
    """district column accepts NULL values (Phase 1 fix)."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", district=None)
    db.expire_all()
    loaded = db.query(EmployeeAddress).filter(EmployeeAddress.id == addr.id).one()
    assert loaded.district is None


# ---------------------------------------------------------------------------
# Address type normalization
# ---------------------------------------------------------------------------

def test_address_type_uppercase_normalization(db, make_user):
    """address_type is normalized to uppercase."""
    user = make_user(role="user", balance_al=None)
    addr = create_address(
        db=db,
        user_id=user["user_id"],
        address_type="home",
        residence_status="owner",
        province="Tehran",
        city="Tehran",
        postal_code="1111111111",
        address_text="test",
    )
    assert addr.address_type == "HOME"


# ---------------------------------------------------------------------------
# Sentinel: _UNSET vs None distinction
# ---------------------------------------------------------------------------

def test_update_unset_keeps_existing_value(db, make_user):
    """Omitting a param (default _UNSET) keeps existing value."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", province="Tehran", district="Central")

    updated = update_address(db, user["user_id"], addr.id)  # no params => all _UNSET
    assert updated.province == "Tehran"
    assert updated.district == "Central"
    assert updated.postal_code == "1111111111"


def test_update_none_clears_optional_field(db, make_user):
    """Passing None explicitly clears an optional field."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", district="Central")

    updated = update_address(db, user["user_id"], addr.id, district=None)
    assert updated.district is None


def test_update_none_clears_latitude_longitude(db, make_user):
    """Passing None clears latitude/longitude."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", latitude=35.6892, longitude=51.3890)

    updated = update_address(db, user["user_id"], addr.id, latitude=None, longitude=None)
    assert updated.latitude is None
    assert updated.longitude is None


def test_update_none_clears_valid_dates(db, make_user):
    """Passing None clears valid_from/valid_to."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111",
                        valid_from=date(2024, 1, 1), valid_to=date(2024, 12, 31))

    updated = update_address(db, user["user_id"], addr.id, valid_from=None, valid_to=None)
    assert updated.valid_from is None
    assert updated.valid_to is None


def test_update_none_clears_notes_gnaf(db, make_user):
    """Passing None clears notes and gnaf_id."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", notes="Some note", gnaf_id="GNAF123")

    updated = update_address(db, user["user_id"], addr.id, notes=None, gnaf_id=None)
    assert updated.notes is None
    assert updated.gnaf_id is None


def test_update_value_overrides_unset(db, make_user):
    """Passing an explicit value overrides the _UNSET default."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111", province="Tehran")

    updated = update_address(db, user["user_id"], addr.id, province="Isfahan")
    assert updated.province == "Isfahan"
    # Other fields unchanged
    assert updated.city == "Tehran"
    assert updated.postal_code == "1111111111"


def test_update_keep_dates_when_not_passed(db, make_user):
    """valid_from/valid_to keep existing values when not passed."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111",
                        valid_from=date(2024, 1, 1), valid_to=date(2024, 12, 31))

    updated = update_address(db, user["user_id"], addr.id, province="Isfahan")
    assert updated.valid_from == date(2024, 1, 1)
    assert updated.valid_to == date(2024, 12, 31)
    assert updated.province == "Isfahan"


# ---------------------------------------------------------------------------
# Required fields (province / city / address_text match NOT NULL rules)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,label", [
    ("province", "استان"),
    ("city", "شهر"),
    ("address_text", "آدرس کامل"),
])
@pytest.mark.parametrize("bad", [None, "", "   "])
def test_create_rejects_empty_required_field(db, make_user, field, label, bad):
    """create rejects None/empty/whitespace for required fields."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match=label):
        _create_addr(db, user["user_id"], **{field: bad})


@pytest.mark.parametrize("field", ["province", "city", "address_text"])
@pytest.mark.parametrize("bad", [None, "", "   "])
def test_update_rejects_empty_required_field(db, make_user, field, bad):
    """update rejects None/empty for required fields; old value kept."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111")
    with pytest.raises(AddressServiceError):
        update_address(db, user["user_id"], addr.id, **{field: bad})
    db.expire_all()
    kept = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert kept.province == "Tehran"
    assert kept.city == "Tehran"
    assert kept.address == "خیابان آزادی، تهران"


def test_update_omitted_required_fields_preserved(db, make_user):
    """Omitting required fields keeps existing values."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(db, user["user_id"], postal_code="1111111111",
                        province="Fars", city="Shiraz",
                        address_text="نشانی ثابت")

    updated = update_address(db, user["user_id"], addr.id, notes="new note")
    assert updated.province == "Fars"
    assert updated.city == "Shiraz"
    assert updated.address == "نشانی ثابت"
    assert updated.notes == "new note"


def test_update_optional_fields_still_clearable(db, make_user):
    """Optional clearing behavior is unchanged by required validation."""
    user = make_user(role="user", balance_al=None)
    addr = _create_addr(
        db, user["user_id"], postal_code="1111111111",
        district="Markazi", notes="note", gnaf_id="G1")

    updated = update_address(
        db, user["user_id"], addr.id,
        district=None, notes="", gnaf_id=None)
    assert updated.district is None
    assert updated.notes is None
    assert updated.gnaf_id is None
    # required snapshots untouched
    assert updated.province == "Tehran"
    assert updated.city == "Tehran"
    assert updated.address == "خیابان آزادی، تهران"
