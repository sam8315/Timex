"""
Focused tests for Phase 5: interactive map picker (Leaflet, no geocoding).

Verifies (without browser automation):
- map picker markup + shared helper wired into admin and user pages
- existing coordinates are passed to the edit form
- empty coordinates remain empty (no fake marker values)
- add/edit routes still accept coordinate values
- invalid coordinates are rejected by service validation
- user/admin flows remain scoped (permission + ownership)
"""
import re

from models.employee_address import EmployeeAddress
from web.services.address_service import (
    AddressServiceError, create_address,
)

from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}
MAP_HINT = "برای ثبت موقعیت، روی نقشه کلیک کنید یا نشانگر را جابه‌جا کنید."
GEO_LABEL = "استفاده از موقعیت فعلی"


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


def _login(client, creds):
    return login_as(client, creds["national_code"])


# ---------------------------------------------------------------------------
# Shared helper script (served statically, no browser needed)
# ---------------------------------------------------------------------------

def test_map_helper_script_served(client):
    """Shared JS helper is served and uses OSM tiles + modal-safe init."""
    resp = client.get("/static/js/address_map.js")
    assert resp.status_code == 200
    body = resp.text
    assert "tile.openstreetmap.org/{z}/{x}/{y}.png" in body
    assert "© OpenStreetMap contributors" in body
    assert "invalidateSize" in body
    assert "shown.bs.modal" in body
    assert "draggable" in body
    assert "getCurrentPosition" in body
    # no geocoding / search integration
    assert "nominatim" not in body.lower()
    assert "geocod" not in body.lower()


def test_map_helper_normalizes_persian_arabic_numerals(client):
    """parseNum() normalizes Persian/Arabic digits and ٫ like the backend."""
    import re
    resp = client.get("/static/js/address_map.js")
    assert resp.status_code == 200
    body = resp.text
    # digit tables + Persian decimal separator are present ...
    assert "۰۱۲۳۴۵۶۷۸۹" in body
    assert "٠١٢٣٤٥٦٧٨٩" in body
    assert "٫" in body
    # ... and parseNum() actually applies the normalization ...
    block = re.search(
        r"function parseNum\(text\) \{(.*?)\n    \}", body, re.S)
    assert block is not None
    assert "normalizeNumText" in block.group(1)
    # ... while keeping the existing ASCII/comma handling
    assert "replace(',', '.')" in body
    # no geocoding / search integration
    assert "nominatim" not in body.lower()
    assert "geocod" not in body.lower()


# ---------------------------------------------------------------------------
# Admin page wiring
# ---------------------------------------------------------------------------

def test_admin_profile_map_elements(client, db, make_user):
    """Admin add/edit modals contain map, synced inputs and hint."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="1111111111",
                      latitude=35.6892, longitude=51.3890)

    resp = client.get(f"/admin/profile/{target['user_id']}",
                      headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    # Leaflet + shared helper (no inline map-logic duplication)
    assert "leaflet@1.9.4/dist/leaflet.css" in body
    assert "leaflet@1.9.4/dist/leaflet.js" in body
    assert "/static/js/address_map.js" in body
    # add modal picker
    assert 'id="adminAddMap"' in body
    assert 'id="adminAddLat"' in body
    assert 'id="adminAddLng"' in body
    assert 'id="adminAddGeo"' in body
    # edit modal picker for the existing address
    assert f'id="adminEditMap-{addr.id}"' in body
    assert f'id="adminEditLat-{addr.id}"' in body
    assert f'id="adminEditLng-{addr.id}"' in body
    # hint + geolocation button
    assert MAP_HINT in body
    assert GEO_LABEL in body
    # existing coordinates pre-filled for the map to load
    # (NUMERIC(10,7) renders padded, e.g. 35.6892000)
    assert re.search(r'value="35\.6892\d*"', body)
    assert re.search(r'value="51\.389\d*"', body)


def test_admin_edit_modal_empty_coords_stay_empty(client, db, make_user):
    """Edit modal without coords renders empty inputs (no fake values)."""
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="2222222222")

    resp = client.get(f"/admin/profile/{target['user_id']}",
                      headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert f'id="adminEditMap-{addr.id}"' in body
    assert re.search(
        rf'id="adminEditLat-{addr.id}"[^>]*value=""', body, re.S)
    assert re.search(
        rf'id="adminEditLng-{addr.id}"[^>]*value=""', body, re.S)


# ---------------------------------------------------------------------------
# User page wiring
# ---------------------------------------------------------------------------

def test_user_profile_map_elements(client, db, make_user):
    """User add/edit modals contain map, synced inputs and hint."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, me["user_id"], postal_code="3333333333",
                      latitude=36.2972, longitude=59.6067)

    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert "leaflet@1.9.4/dist/leaflet.css" in body
    assert "leaflet@1.9.4/dist/leaflet.js" in body
    assert "/static/js/address_map.js" in body
    assert 'id="userAddMap"' in body
    assert 'id="userAddLat"' in body
    assert 'id="userAddLng"' in body
    assert f'id="userEditMap-{addr.id}"' in body
    assert f'id="userEditLat-{addr.id}"' in body
    assert MAP_HINT in body
    assert GEO_LABEL in body
    assert re.search(r'value="36\.2972\d*"', body)


def test_user_edit_modal_empty_coords_stay_empty(client, db, make_user):
    """User edit modal without coords renders empty inputs."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, me["user_id"], postal_code="4444444444")

    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert re.search(
        rf'id="userEditLat-{addr.id}"[^>]*value=""', body, re.S)
    assert re.search(
        rf'id="userEditLng-{addr.id}"[^>]*value=""', body, re.S)


# ---------------------------------------------------------------------------
# Routes still accept / reject coordinates (service remains authoritative)
# ---------------------------------------------------------------------------

def test_user_add_route_accepts_coords(client, db, make_user):
    """Coordinates posted from the picker are stored with full precision."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    resp = client.post(
        "/profile/addresses/add",
        data={
            "address_type": "HOME", "residence_status": "owner",
            "province": "Tehran", "city": "Tehran", "district": "",
            "postal_code": "5555555555", "address_text": "نقشه",
            "latitude": "35.6892001", "longitude": "51.3890002",
            "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "5555555555").one()
    assert float(row.latitude) == 35.6892001
    assert float(row.longitude) == 51.3890002


def test_user_add_route_rejects_invalid_coords(client, db, make_user):
    """Out-of-range coordinates are rejected; nothing is stored."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    resp = client.post(
        "/profile/addresses/add",
        data={
            "address_type": "HOME", "residence_status": "owner",
            "province": "Tehran", "city": "Tehran", "district": "",
            "postal_code": "6666666666", "address_text": "نامعتبر",
            "latitude": "91", "longitude": "51",
            "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "6666666666").first() is None


def test_service_rejects_invalid_coords(db, make_user):
    """Service validation stays authoritative for map-submitted values."""
    user = make_user(role="user", balance_al=None)
    import pytest
    with pytest.raises(AddressServiceError):
        _make_addr(db, user["user_id"], latitude=200, longitude=10)
    with pytest.raises(AddressServiceError):
        _make_addr(db, user["user_id"], latitude=35, longitude=-200)


# ---------------------------------------------------------------------------
# Scoping intact after Phase 5
# ---------------------------------------------------------------------------

def test_admin_add_requires_edit_profile(client, db, make_user):
    """Plain admin (no edit_profile) is still blocked from admin routes."""
    adm = make_user(role="admin")
    _login(client, adm)
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/add",
        data={
            "address_type": "HOME", "residence_status": "owner",
            "province": "Tehran", "city": "Tehran", "district": "",
            "postal_code": "7777777777", "address_text": "x",
            "latitude": "", "longitude": "",
            "valid_from": "", "valid_to": "", "notes": "", "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.postal_code == "7777777777").first() is None


def test_user_cannot_set_primary_of_other_user(client, db, make_user):
    """User map flows stay scoped to the logged-in user."""
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, other["user_id"], postal_code="8888888888")

    resp = client.post(f"/profile/addresses/{addr.id}/set-primary",
                       follow_redirects=False)
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one().is_primary is False
