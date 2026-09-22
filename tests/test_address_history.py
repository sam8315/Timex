"""
Focused tests for the employee address audit trail.

Covers:
- create records one CREATE row with full snapshot
- update records one UPDATE row with the previous snapshot
- no-op update records nothing
- delete records one DELETE row with the final snapshot
- multiple updates produce ordered rows
- city_id and primary changes are captured
- errors leave no history rows (same-transaction writes)
- cross-user protection through existing routes
"""
import pytest

from models.employee_address import EmployeeAddress
from models.employee_address_history import EmployeeAddressHistory
from decimal import Decimal
from web.services.address_service import (
    AddressServiceError,
    create_address,
    update_address,
    delete_address,
    set_primary_address,
)

from .conftest import login_as


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


def _history(db, address_id):
    return db.query(EmployeeAddressHistory).filter(
        EmployeeAddressHistory.address_id == address_id).order_by(
            EmployeeAddressHistory.id.asc()).all()


# ---------------------------------------------------------------------------
# CREATE / UPDATE / DELETE rows
# ---------------------------------------------------------------------------

def test_create_records_create_row(db, make_user):
    """One CREATE row with full snapshot and actor."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="1111111111",
                      changed_by=user["user_id"])

    rows = _history(db, addr.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "CREATE"
    assert row.user_id == user["user_id"]
    assert row.changed_by_user_id == user["user_id"]
    assert row.changed_at is not None
    assert row.address_type == "HOME"
    assert row.residence_status == "owner"
    assert row.province == "Tehran"
    assert row.city == "Tehran"
    assert row.postal_code == "1111111111"
    assert row.address == "خیابان آزادی، تهران"
    assert row.is_primary is False


def test_update_records_old_snapshot(db, make_user):
    """UPDATE row contains the previous state, not the new one."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="2222222222",
                      changed_by=user["user_id"])

    update_address(db, user["user_id"], addr.id, province="Fars",
                   changed_by="ADMIN-1")

    rows = _history(db, addr.id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE"]
    assert rows[1].province == "Tehran"  # old value
    assert rows[1].changed_by_user_id == "ADMIN-1"


def test_noop_update_records_nothing(db, make_user):
    """An update that changes nothing creates no history row."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="3333333333")

    update_address(db, user["user_id"], addr.id, province="Tehran")
    update_address(db, user["user_id"], addr.id)
    assert len(_history(db, addr.id)) == 1


def test_delete_records_final_snapshot(db, make_user):
    """DELETE row contains the final state before removal."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="4444444444",
                      province="Fars", changed_by=user["user_id"])
    addr_id = addr.id

    delete_address(db, user["user_id"], addr_id, changed_by="ADMIN-2")

    rows = _history(db, addr_id)
    assert [r.action for r in rows] == ["CREATE", "DELETE"]
    assert rows[1].province == "Fars"
    assert rows[1].postal_code == "4444444444"
    assert rows[1].changed_by_user_id == "ADMIN-2"


def test_multiple_updates_ordered(db, make_user):
    """Each real change appends one ordered UPDATE row."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="5555555555")

    update_address(db, user["user_id"], addr.id, province="Fars")
    update_address(db, user["user_id"], addr.id, province="Gilan")
    update_address(db, user["user_id"], addr.id, province="Gilan")  # no-op

    rows = _history(db, addr.id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE", "UPDATE"]
    assert [r.province for r in rows] == ["Tehran", "Tehran", "Fars"]
    assert [r.id for r in rows] == sorted(r.id for r in rows)


# ---------------------------------------------------------------------------
# city_id / primary capture
# ---------------------------------------------------------------------------

def test_city_id_changes_captured(db, make_user):
    """Linking then clearing city_id records old link values."""
    from models.city import City
    user = make_user(role="user", balance_al=None)
    tehran = db.query(City).filter(
        City.name == "Tehran", City.is_active == True).first()
    addr = _make_addr(db, user["user_id"], postal_code="6666666666")

    update_address(db, user["user_id"], addr.id, city_id=tehran.id)
    update_address(db, user["user_id"], addr.id, city_id=None)

    rows = _history(db, addr.id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE", "UPDATE"]
    assert rows[1].city_id is None
    assert rows[2].city_id == tehran.id


def test_primary_changes_captured(db, make_user):
    """set_primary records UPDATE rows for unset + set addresses."""
    user = make_user(role="user", balance_al=None)
    first = _make_addr(db, user["user_id"], postal_code="1111111111",
                       is_primary=True)
    second = _make_addr(db, user["user_id"], postal_code="2222222222",
                        address_type="WORK", is_primary=False)

    set_primary_address(db, user["user_id"], second.id,
                        changed_by=user["user_id"])

    first_rows = _history(db, first.id)
    second_rows = _history(db, second.id)
    assert [r.action for r in first_rows] == ["CREATE", "UPDATE"]
    assert first_rows[1].is_primary is True  # old state before unset
    assert [r.action for r in second_rows] == ["CREATE", "UPDATE"]
    assert second_rows[1].is_primary is False  # old state before set
    assert second_rows[1].changed_by_user_id == user["user_id"]


# ---------------------------------------------------------------------------
# Errors leave no rows / cross-user protection
# ---------------------------------------------------------------------------

def test_error_leaves_no_history(db, make_user):
    """Failed validation rolls back without orphan history rows."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError):
        _make_addr(db, user["user_id"], postal_code="bad")
    assert db.query(EmployeeAddressHistory).filter(
        EmployeeAddressHistory.user_id == user["user_id"]).count() == 0

    addr = _make_addr(db, user["user_id"], postal_code="7777777777")
    with pytest.raises(AddressServiceError):
        update_address(db, user["user_id"], addr.id, address_type="BAD")
    assert len(_history(db, addr.id)) == 1

    with pytest.raises(AddressServiceError):
        delete_address(db, user["user_id"], 999999999)
    assert db.query(EmployeeAddressHistory).filter(
        EmployeeAddressHistory.user_id == user["user_id"]).count() == 1


def test_cross_user_routes_do_not_touch_history(client, db, make_user):
    """User A cannot affect user B's address history via user routes."""
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    addr = _make_addr(db, other["user_id"], postal_code="8888888888")

    base = {
        "address_type": "HOME", "residence_status": "owner",
        "province": "Tehran", "city": "Tehran", "district": "",
        "postal_code": "8888888888", "address_text": "x",
        "latitude": "", "longitude": "",
        "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
    }
    client.post(f"/profile/addresses/{addr.id}/update", data=base,
                follow_redirects=False)
    client.post(f"/profile/addresses/{addr.id}/delete",
                follow_redirects=False)
    client.post(f"/profile/addresses/{addr.id}/set-primary",
                follow_redirects=False)

    rows = _history(db, addr.id)
    assert len(rows) == 1
    assert rows[0].action == "CREATE"
    assert all(r.changed_by_user_id != me["user_id"] for r in rows)


# ---------------------------------------------------------------------------
# Audit retention (append-only: deletions never remove history)
# ---------------------------------------------------------------------------

def test_history_user_id_has_no_fk(db):
    """History carries no FK so deletions cannot cascade into it."""
    from sqlalchemy import inspect as sa_inspect
    fks = sa_inspect(db.bind).get_foreign_keys("employee_address_history")
    assert fks == []


def test_delete_address_keeps_history(db, make_user):
    """All CREATE/UPDATE/DELETE rows survive address deletion."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9999999951")
    update_address(db, user["user_id"], addr.id, province="Fars")
    addr_id, uid = addr.id, user["user_id"]
    delete_address(db, uid, addr_id)

    rows = _history(db, addr_id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE", "DELETE"]
    # still queryable by the stored user_id
    by_user = db.query(EmployeeAddressHistory).filter(
        EmployeeAddressHistory.user_id == uid).all()
    assert len(by_user) == 3


def test_delete_user_keeps_history(db, make_user):
    """Deleting the user (existing cascade mechanism) keeps history."""
    from models.employee_address import EmployeeAddress
    from models.user import User

    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9999999952",
                      province="Gilan")
    update_address(db, user["user_id"], addr.id, province="Fars")
    addr_id, uid = addr.id, user["user_id"]

    db.query(User).filter(User.user_id == uid).delete(
        synchronize_session=False)
    db.commit()

    # addresses are still cascade-deleted ...
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr_id).first() is None
    # ... but the audit trail remains queryable by stored user_id
    rows = _history(db, addr_id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE"]
    assert all(r.user_id == uid for r in rows)
    assert rows[1].province == "Gilan"  # snapshot preserved


def test_operations_unaffected_by_fk_removal(db, make_user):
    """Create/update/delete roundtrip still records a full trail."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9999999953",
                      changed_by=user["user_id"])
    update_address(db, user["user_id"], addr.id, city="Rasht",
                   changed_by=user["user_id"])
    addr_id = addr.id
    delete_address(db, user["user_id"], addr_id,
                   changed_by=user["user_id"])

    rows = _history(db, addr_id)
    assert [r.action for r in rows] == ["CREATE", "UPDATE", "DELETE"]
    assert rows[0].city == "Tehran"
    assert rows[1].city == "Tehran"
    assert rows[2].city == "Rasht"
    assert all(r.changed_by_user_id == user["user_id"] for r in rows)


# ---------------------------------------------------------------------------
# Coordinate audit-history coverage
# ---------------------------------------------------------------------------

def test_create_stores_coords_in_history(db, make_user):
    """CREATE history row captures latitude and longitude."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9000000101",
                        latitude=Decimal("35.6892"),
                        longitude=Decimal("51.3890"),
                        changed_by=user["user_id"])

    rows = _history(db, addr.id)
    assert len(rows) == 1
    assert rows[0].action == "CREATE"
    assert rows[0].latitude == Decimal("35.6892")
    assert rows[0].longitude == Decimal("51.3890")


def test_update_stores_old_coords_in_history(db, make_user):
    """UPDATE history row stores previous latitude/longitude, not new."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9000000102",
                        latitude=Decimal("35.6892"),
                        longitude=Decimal("51.3890"),
                        changed_by=user["user_id"])

    update_address(db, user["user_id"], addr.id,
                   latitude=Decimal("36.2972"),
                   longitude=Decimal("59.6067"),
                   changed_by=user["user_id"])

    rows = _history(db, addr.id)
    assert len(rows) == 2
    assert rows[1].action == "UPDATE"
    assert rows[1].latitude == Decimal("35.6892")
    assert rows[1].longitude == Decimal("51.3890")


def test_update_clearing_coords_stores_old_pair(db, make_user):
    """Clearing both coordinates stores the previous pair in UPDATE history."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9000000103",
                        latitude=Decimal("35.6892"),
                        longitude=Decimal("51.3890"),
                        changed_by=user["user_id"])

    update_address(db, user["user_id"], addr.id,
                   latitude=None, longitude=None,
                   changed_by=user["user_id"])

    rows = _history(db, addr.id)
    assert len(rows) == 2
    assert rows[1].action == "UPDATE"
    assert rows[1].latitude == Decimal("35.6892")
    assert rows[1].longitude == Decimal("51.3890")
    # current address should have NULL coords
    db.expire_all()
    refreshed = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert refreshed.latitude is None
    assert refreshed.longitude is None


def test_update_one_coord_stores_complete_old_pair(db, make_user):
    """Changing one coordinate stores the complete previous pair."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9000000104",
                        latitude=Decimal("35.6892"),
                        longitude=Decimal("51.3890"),
                        changed_by=user["user_id"])

    update_address(db, user["user_id"], addr.id,
                   latitude=Decimal("36.0"),
                   changed_by=user["user_id"])

    rows = _history(db, addr.id)
    assert len(rows) == 2
    assert rows[1].action == "UPDATE"
    assert rows[1].latitude == Decimal("35.6892")
    assert rows[1].longitude == Decimal("51.3890")
    # verify the new value is stored on the address
    db.expire_all()
    refreshed = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert refreshed.latitude == Decimal("36.0")
    assert refreshed.longitude == Decimal("51.3890")


def test_noop_coord_update_no_extra_history(db, make_user):
    """A no-op coordinate update creates no extra history row."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9000000105",
                        latitude=Decimal("35.6892"),
                        longitude=Decimal("51.3890"),
                        changed_by=user["user_id"])

    history_count_before = len(_history(db, addr.id))
    update_address(db, user["user_id"], addr.id,
                   latitude=Decimal("35.6892"),
                   longitude=Decimal("51.3890"),
                   changed_by=user["user_id"])
    history_count_after = len(_history(db, addr.id))

    assert history_count_before == history_count_after
    assert history_count_after == 1
    assert _history(db, addr.id)[0].action == "CREATE"
