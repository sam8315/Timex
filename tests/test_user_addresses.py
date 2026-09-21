"""
Focused tests for Phase 4: employee's own address UI on /profile.

Covers:
- /profile loads addresses
- empty state
- add form rendered
- edit form rendered with existing values
- primary badge
- add / update / set-primary / delete through own-user routes
- clearing optional fields via own-user update route
- another user's address cannot be manipulated through user routes
"""
from datetime import date

from models.employee_address import EmployeeAddress
from web.services.address_service import create_address

from .conftest import login_as

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


def _login(client, creds):
    login_as(client, creds["national_code"])


def _profile(client):
    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200, resp.status_code
    return resp.text


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_profile_loads_addresses(client, db, make_user):
    """Own addresses are listed on /profile."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_addr(db, me["user_id"], postal_code="1111111111",
               address_text="نشانی کاربری یکتا ۱")
    _make_addr(db, me["user_id"], postal_code="2222222222",
               address_type="WORK", address_text="نشانی کاربری یکتا ۲")

    body = _profile(client)
    assert "آدرس‌های من" in body
    assert "1111111111" in body
    assert "2222222222" in body
    assert "نشانی کاربری یکتا ۱" in body
    assert "نشانی کاربری یکتا ۲" in body


def test_profile_does_not_show_other_users_addresses(client, db, make_user):
    """Another user's addresses must not leak into /profile."""
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_addr(db, other["user_id"], postal_code="9999999999",
               address_text="نشانی محرمانه کاربر دیگر")

    body = _profile(client)
    assert "9999999999" not in body
    assert "نشانی محرمانه کاربر دیگر" not in body


def test_profile_empty_state(client, db, make_user):
    """Empty state message + visible add button."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    body = _profile(client)
    assert "هیچ آدرسی برای شما ثبت نشده است" in body
    assert "افزودن آدرس" in body
    assert "addAddressModal" in body


def test_profile_add_form_rendered(client, db, make_user):
    """Add modal contains all fields, options and Jalali hints."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    body = _profile(client)
    assert "/profile/addresses/add" in body
    for name in ["address_type", "residence_status", "province", "city",
                 "district", "postal_code", "address_text", "is_primary",
                 "gnaf_id", "latitude", "longitude", "valid_from",
                 "valid_to", "notes"]:
        assert f'name="{name}"' in body, name
    assert "منزل" in body
    assert "محل کار" in body
    assert "مالک" in body
    assert "مستأجر" in body
    assert "1405/06/30" in body
    assert 'pattern="[0-9]{10}"' in body


def test_profile_edit_form_rendered(client, db, make_user):
    """Edit modal pre-fills existing values including Jalali dates."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, me["user_id"], postal_code="3333333333",
                      province="Isfahan", city="Kashan", district="Markazi",
                      valid_from=date(2024, 3, 20))

    body = _profile(client)
    assert f"editAddressModal-{addr.id}" in body
    assert f"/profile/addresses/{addr.id}/update" in body
    assert 'value="Isfahan"' in body
    assert 'value="Kashan"' in body
    assert 'value="Markazi"' in body
    assert 'value="3333333333"' in body
    assert "1403/01/01" in body


def test_profile_primary_badge(client, db, make_user):
    """Primary shows ⭐ اصلی; set-primary only for the other row."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    primary = _make_addr(db, me["user_id"], postal_code="1111111111",
                         is_primary=True)
    other = _make_addr(db, me["user_id"], postal_code="2222222222",
                       address_type="WORK", is_primary=False)

    body = _profile(client)
    assert "⭐ اصلی" in body
    assert f"/profile/addresses/{other.id}/set-primary" in body
    assert f"/profile/addresses/{primary.id}/set-primary" not in body


# ---------------------------------------------------------------------------
# Own-user routes
# ---------------------------------------------------------------------------

def test_user_add_address(client, db, make_user):
    """POST add stores the address for the logged-in user."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    resp = client.post(
        "/profile/addresses/add",
        data={
            "address_type": "WORK",
            "residence_status": "tenant",
            "province": "Tehran",
            "city": "Tehran",
            "district": "",
            "postal_code": "4444444444",
            "address_text": "نشانی محل کار",
            "latitude": "",
            "longitude": "",
            "valid_from": "1403/01/01",
            "valid_to": "",
            "notes": "",
            "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/profile" in resp.headers["location"]

    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == me["user_id"],
        EmployeeAddress.postal_code == "4444444444",
    ).one()
    assert row.address_type == "WORK"
    assert row.valid_from == date(2024, 3, 20)
    assert row.valid_to is None


def test_user_update_address(client, db, make_user):
    """POST update changes own address fields."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, me["user_id"], postal_code="5555555555",
                      province="Tehran")

    resp = client.post(
        f"/profile/addresses/{addr.id}/update",
        data={
            "address_type": "HOME",
            "residence_status": "owner",
            "province": "Isfahan",
            "city": "Kashan",
            "district": "",
            "postal_code": "5555555555",
            "address_text": "خیابان آزادی، تهران",
            "latitude": "",
            "longitude": "",
            "valid_from": "",
            "valid_to": "",
            "notes": "",
            "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.expire_all()
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert row.province == "Isfahan"
    assert row.city == "Kashan"


def test_user_update_clears_optional_fields(client, db, make_user):
    """Empty optionals clear stored values through the user route."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(
        db, me["user_id"], postal_code="6666666666",
        district="Markazi", latitude=35.0, longitude=51.0,
        notes="note", gnaf_id="G1",
        valid_from=date(2024, 3, 20), valid_to=date(2024, 11, 21),
    )

    resp = client.post(
        f"/profile/addresses/{addr.id}/update",
        data={
            "address_type": "HOME",
            "residence_status": "owner",
            "province": "Tehran",
            "city": "Tehran",
            "district": "",
            "postal_code": "6666666666",
            "address_text": "خیابان آزادی، تهران",
            "latitude": "",
            "longitude": "",
            "valid_from": "",
            "valid_to": "",
            "notes": "",
            "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.expire_all()
    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one()
    assert row.district is None
    assert row.latitude is None
    assert row.longitude is None
    assert row.notes is None
    assert row.gnaf_id is None
    assert row.valid_from is None
    assert row.valid_to is None


def test_user_set_primary(client, db, make_user):
    """Set-primary switches the primary flag."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    first = _make_addr(db, me["user_id"], postal_code="1111111111",
                       is_primary=True)
    second = _make_addr(db, me["user_id"], postal_code="2222222222",
                        address_type="WORK", is_primary=False)

    resp = client.post(
        f"/profile/addresses/{second.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == first.id).one().is_primary is False
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == second.id).one().is_primary is True


def test_user_delete(client, db, make_user):
    """Delete removes own address."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, me["user_id"], postal_code="7777777777")

    resp = client.post(
        f"/profile/addresses/{addr.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).first() is None


def test_user_cannot_touch_other_users_address(client, db, make_user):
    """Scoped service blocks cross-user update/delete/set-primary."""
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    addr = _make_addr(db, other["user_id"], postal_code="8888888888")

    base = {
        "address_type": "HOME",
        "residence_status": "owner",
        "province": "Hacked",
        "city": "Tehran",
        "district": "",
        "postal_code": "8888888888",
        "address_text": "x",
        "latitude": "",
        "longitude": "",
        "valid_from": "",
        "valid_to": "",
        "notes": "",
        "gnaf_id": "",
    }
    resp = client.post(f"/profile/addresses/{addr.id}/update", data=base,
                       follow_redirects=False)
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one().province == "Tehran"

    resp = client.post(f"/profile/addresses/{addr.id}/delete",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).first() is not None

    resp = client.post(f"/profile/addresses/{addr.id}/set-primary",
                       follow_redirects=False)
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).one().is_primary is False
