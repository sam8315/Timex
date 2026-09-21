"""
Focused tests for the Phase 6 data-safety fixes.

Covers:
- existing-DB migration creates city_id index + RESTRICT FK when missing
- migration is idempotent and preserves existing city_id data
- inactive linked city appears in edit forms, marked and preselected
- saving without changing the selection preserves an inactive city_id
- explicitly selecting the empty option clears city_id
- new association with an inactive city is still rejected
"""
import re

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text

from database.init_db import migrate_employee_address_city_id
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


def _schema_state():
    insp = sa_inspect(test_engine)
    indexes = {i["name"] for i in insp.get_indexes("employee_addresses")}
    fks = insp.get_foreign_keys("employee_addresses")
    city_fks = [
        f for f in fks
        if f.get("referred_table") == "cities"
        and f.get("referred_columns") == ["id"]
        and "city_id" in (f.get("constrained_columns") or [])
    ]
    return indexes, city_fks


def _make_dedicated_city(db, tag):
    city = City(name=f"PreserveCity{tag}", province=f"PreserveProv{tag}",
                latitude=10.0, longitude=20.0, is_active=True)
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


def _deactivate(db, city):
    db.query(City).filter(City.id == city.id).update({"is_active": False})
    db.commit()


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


def _addr_form(city_id="", postal_code="9000000001"):
    return {
        "address_type": "HOME", "residence_status": "owner",
        "province": "Tehran", "city": "Tehran", "district": "",
        "postal_code": postal_code, "address_text": "x",
        "latitude": "", "longitude": "",
        "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
        "city_id": city_id,
    }


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_creates_index_and_fk_when_missing(db):
    """Dropped index/FK are recreated by the migration."""
    with test_engine.connect() as conn:
        conn.execute(sa_text(
            'ALTER TABLE employee_addresses '
            'DROP CONSTRAINT IF EXISTS employee_addresses_city_id_fkey'))
        conn.execute(sa_text(
            'DROP INDEX IF EXISTS ix_employee_addresses_city_id'))
        conn.commit()

    indexes, city_fks = _schema_state()
    assert "ix_employee_addresses_city_id" not in indexes
    assert city_fks == []

    migrate_employee_address_city_id(bind_engine=test_engine)

    indexes, city_fks = _schema_state()
    assert "ix_employee_addresses_city_id" in indexes
    assert len(city_fks) == 1
    assert city_fks[0]["name"] == "employee_addresses_city_id_fkey"
    # verify ON DELETE RESTRICT via the pg catalog (confdeltype 'r')
    with test_engine.connect() as conn:
        ondel = conn.execute(sa_text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conname = 'employee_addresses_city_id_fkey'")).scalar()
    assert ondel == "r"


def test_migration_idempotent_and_preserves_data(db, make_user):
    """Repeated runs keep a single index/FK and do not touch city_id data."""
    user = make_user(role="user", balance_al=None)
    tehran = db.query(City).filter(
        City.name == "Tehran", City.is_active == True).first()
    addr = _make_addr(db, user["user_id"], postal_code="9000000002",
                      city_id=tehran.id)

    migrate_employee_address_city_id(bind_engine=test_engine)
    migrate_employee_address_city_id(bind_engine=test_engine)

    indexes, city_fks = _schema_state()
    assert "ix_employee_addresses_city_id" in indexes
    assert len(city_fks) == 1

    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one().city_id == tehran.id


# ---------------------------------------------------------------------------
# Inactive linked city in edit forms
# ---------------------------------------------------------------------------

def test_admin_edit_form_shows_inactive_linked_selected(
        client, db, make_user):
    """Linked inactive city is shown, marked غیرفعال and preselected."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    target = make_user(role="user", balance_al=None)
    city = _make_dedicated_city(db, "Adm")
    ghost = _make_dedicated_city(db, "GhostAdm")
    _make_addr(db, target["user_id"], postal_code="9000000003",
               city_id=city.id)
    _deactivate(db, city)
    _deactivate(db, ghost)
    try:
        resp = client.get(f"/admin/profile/{target['user_id']}",
                          headers=HTML_ACCEPT)
        assert resp.status_code == 200
        body = resp.text
        # linked inactive city rendered, marked and selected
        assert re.search(
            rf'value="{city.id}"[^>]*selected', body)
        assert f"غیرفعال — {city.province} — {city.name}" in body
        # unrelated inactive cities are NOT in the selectable list
        assert "PreserveCityGhostAdm" not in body
    finally:
        _cleanup_city(db, city)
        _cleanup_city(db, ghost)


def test_user_edit_form_shows_inactive_linked_selected(
        client, db, make_user):
    """Same behavior on the user's own /profile page."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _make_dedicated_city(db, "Usr")
    _make_addr(db, me["user_id"], postal_code="9000000004",
               city_id=city.id)
    _deactivate(db, city)
    try:
        resp = client.get("/profile", headers=HTML_ACCEPT)
        assert resp.status_code == 200
        body = resp.text
        assert re.search(
            rf'value="{city.id}"[^>]*selected', body)
        assert f"غیرفعال — {city.province} — {city.name}" in body
    finally:
        _cleanup_city(db, city)


# ---------------------------------------------------------------------------
# Saving preserves / clears
# ---------------------------------------------------------------------------

def test_admin_save_preserves_inactive_city_id(client, db, make_user):
    """Submitting the retained inactive id keeps the link."""
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    target = make_user(role="user", balance_al=None)
    city = _make_dedicated_city(db, "AdmKeep")
    addr = _make_addr(db, target["user_id"], postal_code="9000000005",
                      city_id=city.id)
    _deactivate(db, city)
    try:
        form = _addr_form(city_id=str(city.id), postal_code="9000000005")
        resp = client.post(
            f"/admin/profile/{target['user_id']}/addresses/{addr.id}/update",
            data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" not in resp.headers["location"]
        db.expire_all()
        assert db.query(EmployeeAddress).filter(
            EmployeeAddress.id == addr.id).one().city_id == city.id
    finally:
        _cleanup_city(db, city)


def test_user_save_preserves_inactive_city_id(client, db, make_user):
    """Same preservation through the user's own update route."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _make_dedicated_city(db, "UsrKeep")
    addr = _make_addr(db, me["user_id"], postal_code="9000000006",
                      city_id=city.id)
    _deactivate(db, city)
    try:
        form = _addr_form(city_id=str(city.id), postal_code="9000000006")
        resp = client.post(
            f"/profile/addresses/{addr.id}/update",
            data=form, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" not in resp.headers["location"]
        db.expire_all()
        assert db.query(EmployeeAddress).filter(
            EmployeeAddress.id == addr.id).one().city_id == city.id
    finally:
        _cleanup_city(db, city)


def test_explicit_empty_clears_inactive_link(client, db, make_user):
    """Choosing the empty option clears city_id but keeps the snapshot."""
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    city = _make_dedicated_city(db, "Clr")
    addr = _make_addr(db, me["user_id"], postal_code="9000000007",
                      city="Tehran", city_id=city.id)
    _deactivate(db, city)
    try:
        form = _addr_form(city_id="", postal_code="9000000007")
        resp = client.post(
            f"/profile/addresses/{addr.id}/update",
            data=form, follow_redirects=False)
        assert resp.status_code == 302
        db.expire_all()
        row = db.query(EmployeeAddress).filter(
            EmployeeAddress.id == addr.id).one()
        assert row.city_id is None
        assert row.city == "Tehran"
    finally:
        _cleanup_city(db, city)


def test_new_assoc_with_inactive_city_still_rejected(db, make_user):
    """Associating a different inactive city on edit stays rejected."""
    user = make_user(role="user", balance_al=None)
    ghost = _make_dedicated_city(db, "NewAssoc")
    addr = _make_addr(db, user["user_id"], postal_code="9000000008")
    _deactivate(db, ghost)
    try:
        with pytest.raises(AddressServiceError, match="غیرفعال"):
            update_address(db, user["user_id"], addr.id, city_id=ghost.id)
        db.expire_all()
        assert db.query(EmployeeAddress).filter(
            EmployeeAddress.id == addr.id).one().city_id is None
    finally:
        _cleanup_city(db, ghost)
