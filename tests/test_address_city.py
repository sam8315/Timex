"""
Focused tests for Phase 6: city_id normalization against cities master data.

Covers:
- city_id column registration + FK to cities.id
- multiple addresses with/without city_id
- valid active city accepted
- nonexistent city rejected
- inactive city rejected for new/update selection
- explicit None clears city_id
- omitted city_id preserves existing value
- admin/user forms load active cities (inactive hidden)
- existing address without city_id remains valid and editable
"""
import pytest
from sqlalchemy import inspect as sa_inspect

from models import Base
from models.city import City
from models.employee_address import EmployeeAddress
from web.services.address_service import (
    AddressServiceError, create_address, update_address,
)

from .conftest import login_as, test_engine

HTML_ACCEPT = {"Accept": "text/html"}


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


def _active_city(db, name="Tehran"):
    city = db.query(City).filter(
        City.name == name, City.is_active == True).first()
    assert city is not None, f"seeded active city {name!r} missing"
    return city


def _make_inactive_city(db, suffix):
    city = City(name=f"GhostInactive{suffix}", province="GhostProv",
                latitude=0.0, longitude=0.0, is_active=False)
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


def _cleanup_city(db, city):
    try:
        db.query(EmployeeAddress).filter(
            EmployeeAddress.city_id == city.id).delete(
                synchronize_session=False)
        db.query(City).filter(City.id == city.id).delete(
            synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_city_id_column_registered():
    """city_id is registered, nullable and indexed in metadata."""
    col = Base.metadata.tables["employee_addresses"].columns["city_id"]
    assert col.nullable is True
    assert col.index is True


def test_city_id_column_exists_in_db(db):
    """The nullable column exists in the test database."""
    cols = {c["name"]: c
            for c in sa_inspect(db.bind).get_columns("employee_addresses")}
    assert "city_id" in cols
    assert cols["city_id"]["nullable"] is True


def test_fk_to_cities(db):
    """city_id references cities.id."""
    fks = sa_inspect(db.bind).get_foreign_keys("employee_addresses")
    assert any(
        f["referred_table"] == "cities"
        and f["referred_columns"] == ["id"]
        and "city_id" in f["constrained_columns"]
        for f in fks
    )


# ---------------------------------------------------------------------------
# Service validation
# ---------------------------------------------------------------------------

def test_create_with_active_city(db, make_user):
    """Active city_id is accepted and resolves via relationship."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="1111111111",
                      city_id=city.id)
    assert addr.city_id == city.id
    db.expire_all()
    loaded = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert loaded.city_ref is not None
    assert loaded.city_ref.name == city.name


def test_create_without_city_id(db, make_user):
    """city_id stays NULL when omitted (existing records stay valid)."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="2222222222")
    assert addr.city_id is None


def test_create_nonexistent_city_rejected(db, make_user):
    """Unknown city_id is rejected."""
    user = make_user(role="user", balance_al=None)
    with pytest.raises(AddressServiceError, match="شهر یافت نشد"):
        _make_addr(db, user["user_id"], city_id=999999999)


def test_create_inactive_city_rejected(db, make_user):
    """Inactive city cannot be newly selected."""
    user = make_user(role="user", balance_al=None)
    ghost = _make_inactive_city(db, "New")
    try:
        with pytest.raises(AddressServiceError, match="غیرفعال"):
            _make_addr(db, user["user_id"], city_id=ghost.id)
    finally:
        _cleanup_city(db, ghost)


def test_update_associate_city(db, make_user):
    """An address without city_id can later be associated."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="3333333333")
    assert addr.city_id is None

    updated = update_address(db, user["user_id"], addr.id, city_id=city.id)
    assert updated.city_id == city.id


def test_update_omitted_preserves_city_id(db, make_user):
    """Omitting city_id keeps the existing value (_UNSET)."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="4444444444",
                      city_id=city.id)

    updated = update_address(db, user["user_id"], addr.id, notes="n")
    assert updated.city_id == city.id
    assert updated.notes == "n"


def test_update_none_clears_city_id(db, make_user):
    """Explicit None clears city_id."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="5555555555",
                      city_id=city.id)

    updated = update_address(db, user["user_id"], addr.id, city_id=None)
    assert updated.city_id is None


def test_update_inactive_city_rejected(db, make_user):
    """Switching to an inactive city is rejected; old value kept."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="6666666666",
                      city_id=city.id)
    ghost = _make_inactive_city(db, "Upd")
    try:
        with pytest.raises(AddressServiceError, match="غیرفعال"):
            update_address(db, user["user_id"], addr.id, city_id=ghost.id)
        db.expire_all()
        assert db.query(EmployeeAddress).filter(
            EmployeeAddress.id == addr.id).one().city_id == city.id
    finally:
        _cleanup_city(db, ghost)


def test_multiple_addresses_with_without_city_id(db, make_user):
    """One user can mix linked and unlinked addresses."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    _make_addr(db, user["user_id"], postal_code="1111111111",
               city_id=city.id, is_primary=False)
    _make_addr(db, user["user_id"], postal_code="2222222222",
               address_type="WORK", is_primary=False)
    rows = db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == user["user_id"]).all()
    assert len(rows) == 2
    assert {r.city_id for r in rows} == {city.id, None}


# ---------------------------------------------------------------------------
# Forms load active cities
# ---------------------------------------------------------------------------

def test_admin_form_loads_active_cities(client, db, make_user):
    """Admin add/edit selects list active cities as «province — city»."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    target = make_user(role="user", balance_al=None)
    city = _active_city(db)
    ghost = _make_inactive_city(db, "Frm")
    try:
        resp = client.get(f"/admin/profile/{target['user_id']}",
                          headers=HTML_ACCEPT)
        assert resp.status_code == 200
        body = resp.text
        assert 'name="city_id"' in body
        assert f'value="{city.id}"' in body
        assert f"{city.province} — {city.name}" in body
        assert f"GhostInactiveFrm" not in body
    finally:
        _cleanup_city(db, ghost)


def test_user_form_loads_active_cities(client, db, make_user):
    """User add form lists active cities; inactive hidden."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _active_city(db)
    ghost = _make_inactive_city(db, "Usr")
    try:
        resp = client.get("/profile", headers=HTML_ACCEPT)
        assert resp.status_code == 200
        body = resp.text
        assert 'name="city_id"' in body
        assert f'value="{city.id}"' in body
        assert "GhostInactiveUsr" not in body
    finally:
        _cleanup_city(db, ghost)


def test_edit_form_preselects_city_id(client, db, make_user):
    """Edit modal preselects the linked city; snapshot matches master."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _active_city(db)
    addr = _make_addr(db, me["user_id"], postal_code="7777777777",
                      city="TehranCustom", city_id=city.id)

    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert f'value="{city.id}"' in body
    # conflicting submitted text was replaced by the master snapshot
    assert f'value="{city.name}"' in body
    assert 'value="TehranCustom"' not in body


def test_edit_form_keeps_manual_snapshot_without_link(client, db, make_user):
    """Without city_id the manual text snapshot is shown as-is."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    _make_addr(db, me["user_id"], postal_code="7777777778",
               city="TehranCustom")

    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert 'value="TehranCustom"' in resp.text


# ---------------------------------------------------------------------------
# Routes store city_id (backend authoritative)
# ---------------------------------------------------------------------------

def _addr_form(city_id="", postal_code="8888888888"):
    return {
        "address_type": "HOME", "residence_status": "owner",
        "province": "Tehran", "city": "Tehran", "district": "",
        "postal_code": postal_code, "address_text": "x",
        "latitude": "", "longitude": "",
        "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
        "city_id": city_id,
    }


def test_admin_add_route_with_city_id(client, db, make_user):
    """Admin add stores the selected city_id."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    target = make_user(role="user", balance_al=None)
    city = _active_city(db)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/add",
        data=_addr_form(city_id=str(city.id), postal_code="8888888881"),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "8888888881").one()
    assert row.city_id == city.id


def test_admin_add_route_rejects_bad_city(client, db, make_user):
    """Admin add with unknown city fails without storing."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/add",
        data=_addr_form(city_id="999999999", postal_code="8888888882"),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "8888888882").first() is None


def test_user_add_route_with_city_id(client, db, make_user):
    """User add stores the selected city_id."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _active_city(db)

    resp = client.post(
        "/profile/addresses/add",
        data=_addr_form(city_id=str(city.id), postal_code="8888888883"),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "8888888883").one()
    assert row.city_id == city.id
    assert row.user_id == me["user_id"]


def test_user_update_route_clears_city_id(client, db, make_user):
    """User update with empty city_id clears the link, keeps snapshot."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _active_city(db)
    addr = _make_addr(db, me["user_id"], postal_code="8888888884",
                      city="Tehran", city_id=city.id)

    resp = client.post(
        f"/profile/addresses/{addr.id}/update",
        data=_addr_form(city_id="", postal_code="8888888884"),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert row.city_id is None
    assert row.city == "Tehran"


# ---------------------------------------------------------------------------
# city_id authoritative snapshot (server-side, JS-independent)
# ---------------------------------------------------------------------------

def test_create_city_overrides_conflicting_text(db, make_user):
    """Create with city_id + conflicting texts stores the master snapshot."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="9999999901",
                      province="WrongProv", city="WrongCity",
                      city_id=city.id)
    assert addr.city_id == city.id
    assert addr.province == city.province
    assert addr.city == city.name


def test_create_city_null_keeps_manual_snapshot(db, make_user):
    """Create without city_id stores validated manual texts."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9999999902",
                      province="Gilan", city="Rasht")
    assert addr.city_id is None
    assert addr.province == "Gilan"
    assert addr.city == "Rasht"


def test_update_changed_city_refreshes_snapshot(db, make_user):
    """Changed city_id replaces the snapshot from the new master row."""
    user = make_user(role="user", balance_al=None)
    tehran = _active_city(db, "Tehran")
    mashhad = _active_city(db, "Mashhad")
    addr = _make_addr(db, user["user_id"], postal_code="9999999903",
                      city_id=tehran.id)
    assert addr.city == tehran.name

    updated = update_address(
        db, user["user_id"], addr.id, city_id=mashhad.id,
        province="WrongProv", city="WrongCity")
    assert updated.city_id == mashhad.id
    assert updated.province == mashhad.province
    assert updated.city == mashhad.name


def test_update_same_inactive_city_preserves_snapshot(db, make_user):
    """Retained inactive link keeps the stored snapshot untouched."""
    user = make_user(role="user", balance_al=None)
    city = City(name="PreserveSnapCity", province="PreserveSnapProv",
                latitude=11.0, longitude=22.0, is_active=True)
    db.add(city)
    db.commit()
    db.refresh(city)
    addr = _make_addr(db, user["user_id"], postal_code="9999999904",
                      city_id=city.id)
    stored_province, stored_city = addr.province, addr.city
    assert stored_province == "PreserveSnapProv"
    db.query(City).filter(City.id == city.id).update({"is_active": False})
    db.commit()
    try:
        updated = update_address(
            db, user["user_id"], addr.id, city_id=city.id,
            province="WrongProv", city="WrongCity")
        assert updated.city_id == city.id
        assert updated.province == stored_province
        assert updated.city == stored_city
    finally:
        _cleanup_city(db, city)


def test_crafted_post_cannot_break_snapshot(client, db, make_user):
    """Inconsistent city_id/province/city POST is corrected server-side."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _active_city(db)
    addr = _make_addr(db, me["user_id"], postal_code="9999999905")

    resp = client.post(
        f"/profile/addresses/{addr.id}/update",
        data=_addr_form(city_id=str(city.id), postal_code="9999999905") | {
            "province": "HackedProv", "city": "HackedCity"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert row.city_id == city.id
    assert row.province == city.province
    assert row.city == city.name
    assert "Hacked" not in (row.province + row.city)


# ---------------------------------------------------------------------------
# Omitted city_id never splits the linked snapshot
# ---------------------------------------------------------------------------

def test_omitted_city_id_ignores_conflicting_texts(db, make_user):
    """Linked + omitted + conflicting texts => all three unchanged."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="9999999911",
                      city_id=city.id)

    updated = update_address(
        db, user["user_id"], addr.id,
        province="WrongProv", city="WrongCity")
    assert updated.city_id == city.id
    assert updated.province == city.province
    assert updated.city == city.name


def test_omitted_city_id_inactive_link_unchanged(db, make_user):
    """Inactive link + omitted + conflicting texts => all three unchanged."""
    user = make_user(role="user", balance_al=None)
    city = City(name="OmitSnapCity", province="OmitSnapProv",
                latitude=13.0, longitude=24.0, is_active=True)
    db.add(city)
    db.commit()
    db.refresh(city)
    addr = _make_addr(db, user["user_id"], postal_code="9999999912",
                      city_id=city.id)
    stored = (addr.province, addr.city)
    db.query(City).filter(City.id == city.id).update({"is_active": False})
    db.commit()
    try:
        updated = update_address(
            db, user["user_id"], addr.id,
            province="WrongProv", city="WrongCity")
        assert updated.city_id == city.id
        assert (updated.province, updated.city) == stored
    finally:
        _cleanup_city(db, city)


def test_omitted_city_id_null_link_updates_manual(db, make_user):
    """NULL link + omitted + valid texts => manual snapshot updated."""
    user = make_user(role="user", balance_al=None)
    addr = _make_addr(db, user["user_id"], postal_code="9999999913")

    updated = update_address(
        db, user["user_id"], addr.id,
        province="Gilan", city="Rasht")
    assert updated.city_id is None
    assert updated.province == "Gilan"
    assert updated.city == "Rasht"


def test_omitted_city_id_with_empty_texts_no_failure(db, make_user):
    """Linked + omitted + empty texts => snapshot kept, no error."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="9999999914",
                      city_id=city.id)

    updated = update_address(
        db, user["user_id"], addr.id, province="", city=None)
    assert updated.city_id == city.id
    assert updated.province == city.province
    assert updated.city == city.name


def test_explicit_none_then_manual_snapshot(db, make_user):
    """Explicit None clears the link; submitted texts become the snapshot."""
    user = make_user(role="user", balance_al=None)
    city = _active_city(db)
    addr = _make_addr(db, user["user_id"], postal_code="9999999915",
                      city_id=city.id)

    updated = update_address(
        db, user["user_id"], addr.id, city_id=None,
        province="Gilan", city="Rasht")
    assert updated.city_id is None
    assert updated.province == "Gilan"
    assert updated.city == "Rasht"
