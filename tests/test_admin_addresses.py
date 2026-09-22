"""
Focused tests for Phase 3: ADMIN address UI on /admin/profile/{target_user_id}.

Covers:
- admin profile loads addresses (list passed to template)
- add form is rendered
- edit form is rendered with existing values
- primary badge rendered correctly
- empty state rendered
- add / update / set-primary / delete via admin routes
- Jalali date input converted to Gregorian
- optional fields can be cleared via update route
- cross-user access protection
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


def _login_super(client, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    return super_u


def _profile(client, target_user_id):
    resp = client.get(f"/admin/profile/{target_user_id}", headers=HTML_ACCEPT)
    assert resp.status_code == 200, resp.status_code
    return resp.text


# ---------------------------------------------------------------------------
# Profile renders addresses
# ---------------------------------------------------------------------------

def test_admin_profile_loads_addresses(client, db, make_user):
    """Address list is passed to the template and rendered."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_addr(db, target["user_id"], postal_code="1111111111",
               address_text="نشانی یکتای تستی ۱")
    _make_addr(db, target["user_id"], postal_code="2222222222",
               address_type="WORK", address_text="نشانی یکتای تستی ۲")

    body = _profile(client, target["user_id"])
    assert "آدرس‌ها" in body
    assert "1111111111" in body
    assert "2222222222" in body
    assert "نشانی یکتای تستی ۱" in body
    assert "نشانی یکتای تستی ۲" in body


def test_admin_profile_empty_state(client, db, make_user):
    """Empty state message + visible add button when no address exists."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    body = _profile(client, target["user_id"])
    assert "هیچ آدرسی برای این کارمند ثبت نشده است" in body
    assert "افزودن آدرس" in body
    assert "adminAddAddressModal" in body


def test_admin_profile_add_form_rendered(client, db, make_user):
    """Add modal contains all required fields and select options."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    body = _profile(client, target["user_id"])
    # form action
    assert f"/admin/profile/{target['user_id']}/addresses/add" in body
    # all field names
    for name in ["address_type", "residence_status", "province", "city",
                 "district", "postal_code", "address_text", "is_primary",
                 "gnaf_id", "latitude", "longitude", "valid_from",
                 "valid_to", "notes"]:
        assert f'name="{name}"' in body, name
    # select options (Phase 3 Persian labels)
    assert "منزل" in body
    assert "محل کار" in body
    assert "مالک" in body
    assert "مستأجر" in body
    assert "منزل خانواده/پدری" in body
    assert "مسکن سازمانی" in body
    # Jalali placeholder
    assert "1405/06/30" in body
    # postal code client-side validation
    assert 'pattern="[0-9]{10}"' in body


def test_admin_profile_edit_form_rendered(client, db, make_user):
    """Edit modal is rendered with existing values."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="3333333333",
                      province="Isfahan", city="Kashan", district="Markazi",
                      valid_from=date(2024, 3, 20), valid_to=date(2024, 11, 21))

    body = _profile(client, target["user_id"])
    # edit modal id + update action
    assert f"adminEditAddressModal-{addr.id}" in body
    assert f"/admin/profile/{target['user_id']}/addresses/{addr.id}/update" in body
    # existing values pre-filled
    assert 'value="Isfahan"' in body
    assert 'value="Kashan"' in body
    assert 'value="Markazi"' in body
    assert 'value="3333333333"' in body
    # Jalali dates pre-filled (2024-03-20 => 1403/01/01)
    assert "1403/01/01" in body


def test_admin_profile_primary_badge(client, db, make_user):
    """Primary address shows ⭐ اصلی; set-primary only for non-primary."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    primary = _make_addr(db, target["user_id"], postal_code="1111111111",
                         is_primary=True)
    other = _make_addr(db, target["user_id"], postal_code="2222222222",
                       address_type="WORK", is_primary=False)

    body = _profile(client, target["user_id"])
    assert "⭐ اصلی" in body
    # set-primary action exists for the non-primary row…
    assert (f"/admin/profile/{target['user_id']}/addresses/"
            f"{other.id}/set-primary") in body
    # …but not for the primary row
    assert (f"/admin/profile/{target['user_id']}/addresses/"
            f"{primary.id}/set-primary") not in body


# ---------------------------------------------------------------------------
# Admin routes: add / update / set-primary / delete
# ---------------------------------------------------------------------------

def test_admin_add_address_jalali_dates(client, db, make_user):
    """POST add with Jalali dates stores Gregorian equivalents."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/add",
        data={
            "address_type": "HOME",
            "residence_status": "tenant",
            "province": "Tehran",
            "city": "Tehran",
            "district": "",
            "postal_code": "4444444444",
            "address_text": "نشانی jalali",
            "latitude": "35.6892",
            "longitude": "51.3890",
            "valid_from": "1403/01/01",
            "valid_to": "1403/12/29",
            "notes": "",
            "gnaf_id": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"/admin/profile/{target['user_id']}" in resp.headers["location"]

    row = db.query(EmployeeAddress).filter(
        EmployeeAddress.user_id == target["user_id"],
        EmployeeAddress.postal_code == "4444444444",
    ).one()
    assert row.valid_from == date(2024, 3, 20)
    assert row.residence_status == "tenant"
    assert float(row.latitude) == 35.6892


def test_admin_update_clears_optional_fields(client, db, make_user):
    """Empty optional inputs clear stored values (sentinel fix)."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(
        db, target["user_id"], postal_code="5555555555",
        district="Markazi", latitude=35.0, longitude=51.0,
        notes="keep?", gnaf_id="G1",
        valid_from=date(2024, 3, 20), valid_to=date(2024, 11, 21),
    )

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/{addr.id}/update",
        data={
            "address_type": "HOME",
            "residence_status": "owner",
            "province": "Tehran",
            "city": "Tehran",
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
    assert row.district is None
    assert row.latitude is None
    assert row.longitude is None
    assert row.notes is None
    assert row.gnaf_id is None
    assert row.valid_from is None
    assert row.valid_to is None
    # required fields kept
    assert row.province == "Tehran"
    assert row.postal_code == "5555555555"


def test_admin_set_primary_via_route(client, db, make_user):
    """Set-primary replaces the existing primary."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    first = _make_addr(db, target["user_id"], postal_code="1111111111",
                       is_primary=True)
    second = _make_addr(db, target["user_id"], postal_code="2222222222",
                        address_type="WORK", is_primary=False)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/{second.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == first.id).one().is_primary is False
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == second.id).one().is_primary is True


def test_admin_delete_via_route(client, db, make_user):
    """Delete removes the address."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    addr = _make_addr(db, target["user_id"], postal_code="6666666666")

    resp = client.post(
        f"/admin/profile/{target['user_id']}/addresses/{addr.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr.id).first() is None


def test_admin_cross_user_protection(client, db, make_user):
    """Scoped service blocks operating on another user's address."""
    _login_super(client, make_user)
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    addr_b = _make_addr(db, user_b["user_id"], postal_code="7777777777")

    # delete with wrong target_user_id must not remove the row
    resp = client.post(
        f"/admin/profile/{user_a['user_id']}/addresses/{addr_b.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr_b.id).first() is not None

    # update with wrong target_user_id must not change the row
    resp = client.post(
        f"/admin/profile/{user_a['user_id']}/addresses/{addr_b.id}/update",
        data={
            "address_type": "HOME",
            "residence_status": "owner",
            "province": "Hacked",
            "city": "Tehran",
            "district": "",
            "postal_code": "7777777777",
            "address_text": "x",
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
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr_b.id).one().province == "Tehran"

    # set-primary with wrong target_user_id must not flip the flag
    resp = client.post(
        f"/admin/profile/{user_a['user_id']}/addresses/{addr_b.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeAddress).filter(
        EmployeeAddress.id == addr_b.id).one().is_primary is False
