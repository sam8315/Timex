"""
Focused API/permission tests for Employee Bank Accounts (Phase 5).

Covers:
- authorized list / get (own + admin)
- create / update / delete
- set Primary / activate / deactivate
- verification status
- unauthorized access (307)
- cross-user access rejection (404)
- permission denial (403)
- validation / service error → HTTP mapping (302 ?error= / 404 detail)
- sensitive fields present per existing API conventions (no masking standard)
"""
from database.init_db import seed_banks
from models.bank import Bank
from models.employee_bank_account import EmployeeBankAccount
from web.services.bank_account_service import create_bank_account

from .conftest import login_as, test_engine

VALID_CARD = "6037990000000006"
VALID_CARD_ZEROS = "0000111122223337"
VALID_SHEBA = "IR940180000000000001234567"
INVALID_CARD_LUHN = "6037990000000007"
INVALID_SHEBA_MOD97 = "IR940180000000000001234560"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seeded_bank_id(db, code="018") -> int:
    seed_banks(bind_engine=test_engine)
    return db.query(Bank).filter(Bank.code == code).one().id


def _create_acc(db, user_id, **overrides):
    defaults = dict(
        bank_id=_seeded_bank_id(db),
        account_number="12345678901234567890",
        is_primary=False,
        is_active=True,
    )
    defaults.update(overrides)
    return create_bank_account(db, user_id=user_id, **defaults)


def _login(client, creds):
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302


def _login_super(client, make_user):
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    return super_u


from urllib.parse import unquote


def _assert_error_redirect(resp, fragment=None):
    assert resp.status_code == 302
    loc = unquote(resp.headers["location"])
    assert "error=" in loc
    if fragment:
        assert fragment in loc


def _assert_success_redirect(resp):
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Unauthorized (no session)
# ---------------------------------------------------------------------------

def test_list_requires_auth(client):
    resp = client.get("/profile/bank-accounts", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/login"


def test_create_requires_auth(client):
    resp = client.post(
        "/profile/bank-accounts/add",
        data={"bank_id": "1", "account_number": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 307


def test_admin_list_requires_auth(client):
    resp = client.get(
        "/admin/profile/X/bank-accounts", follow_redirects=False
    )
    assert resp.status_code == 307


# ---------------------------------------------------------------------------
# Authorized list / get
# ---------------------------------------------------------------------------

def test_authorized_list_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _create_acc(db, me["user_id"], account_number="1111111111", is_primary=True)
    _create_acc(db, me["user_id"], account_number="2222222222")

    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["is_primary"] is True
    assert data[0]["account_number"] == "1111111111"


def test_authorized_list_empty(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_authorized_get_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], account_number="1111111111")
    resp = client.get(f"/profile/bank-accounts/{acc.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == acc.id
    assert body["account_number"] == "1111111111"
    assert body["verification_status"] == "unverified"


def test_list_exposes_sensitive_fields_without_masking(client, db, make_user):
    """Existing APIs do not mask bank identifiers; fields are present as strings."""
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _create_acc(
        db, me["user_id"],
        card_number=VALID_CARD,
        sheba=VALID_SHEBA,
    )
    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["card_number"] == VALID_CARD
    assert row["sheba"] == VALID_SHEBA
    assert row["account_number"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    bank_id = _seeded_bank_id(db)
    resp = client.post(
        "/profile/bank-accounts/add",
        data={
            "bank_id": str(bank_id),
            "account_number": "1111111111",
            "card_number": VALID_CARD,
            "sheba": VALID_SHEBA,
            "is_primary": "true",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    rows = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == me["user_id"]
    ).all()
    assert len(rows) == 1
    assert rows[0].card_number == VALID_CARD
    assert rows[0].is_primary is True


def test_create_invalid_card_maps_to_error_redirect(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        "/profile/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
            "card_number": INVALID_CARD_LUHN,
        },
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "چک‌سام")


def test_create_invalid_sheba_maps_to_error_redirect(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        "/profile/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
            "sheba": INVALID_SHEBA_MOD97,
        },
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "چک‌سام")


def test_create_validation_does_not_touch_verification(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        "/profile/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
            "card_number": VALID_CARD,
        },
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    row = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == me["user_id"]
    ).one()
    assert row.verification_status == "unverified"
    assert row.verified_at is None
    assert row.verified_by is None
    assert row.verification_note is None


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------

def test_update_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], account_number="1111111111")
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/update",
        data={
            "account_number": "1111111111",
            "branch_name": "Branch New",
            "card_number": VALID_CARD,
        },
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.branch_name == "Branch New"
    assert kept.card_number == VALID_CARD
    assert kept.verification_status == "unverified"


def test_update_rejects_invalid_card(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], card_number=VALID_CARD)
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/update",
        data={
            "account_number": acc.account_number,
            "card_number": INVALID_CARD_LUHN,
        },
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "چک‌سام")
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.card_number == VALID_CARD


def test_delete_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"])
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/delete",
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).first() is None


def test_delete_missing_maps_to_error(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        "/profile/bank-accounts/999999/delete",
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "حساب بانکی یافت نشد")


# ---------------------------------------------------------------------------
# Primary / active
# ---------------------------------------------------------------------------

def test_set_primary_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    a1 = _create_acc(db, me["user_id"], account_number="1111111111", is_primary=True)
    a2 = _create_acc(db, me["user_id"], account_number="2222222222")
    resp = client.post(
        f"/profile/bank-accounts/{a2.id}/set-primary",
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == a1.id
    ).one().is_primary is False
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == a2.id
    ).one().is_primary is True


def test_set_primary_inactive_maps_to_error(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], is_active=False)
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-primary",
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "حساب غیرفعال نمی‌تواند اصلی باشد")


def test_deactivate_primary_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], is_primary=True, is_active=True)
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-active",
        data={"active": "false"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.is_active is False
    assert kept.is_primary is True


def test_activate_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"], is_active=False)
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-active",
        data={"active": "true"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one().is_active is True


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def test_verification_status_change_own(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"])
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "verified", "note": "ok"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "verified"
    assert kept.verified_by == me["user_id"]
    assert kept.verified_at is not None
    assert kept.verification_note == "ok"


def test_verification_invalid_status_maps_to_error(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"])
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "pending"},
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "وضعیت تأیید نامعتبر است")


def test_verification_rejected_then_unverified_clears_stamps(
    client, db, make_user
):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _create_acc(db, me["user_id"])
    client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "rejected", "note": "bad"},
        follow_redirects=False,
    )
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "unverified", "note": "reset"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "unverified"
    assert kept.verified_at is None
    assert kept.verified_by is None


# ---------------------------------------------------------------------------
# Cross-user scoping
# ---------------------------------------------------------------------------

def test_get_other_user_account_denied(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    foreign = _create_acc(db, other["user_id"])
    resp = client.get(f"/profile/bank-accounts/{foreign.id}")
    assert resp.status_code == 404
    assert "حساب بانکی یافت نشد" in resp.json()["detail"]


def test_update_other_user_account_denied(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    foreign = _create_acc(db, other["user_id"])
    resp = client.post(
        f"/profile/bank-accounts/{foreign.id}/update",
        data={"account_number": "9999999999", "branch_name": "Hacked"},
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "حساب بانکی یافت نشد")
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == foreign.id
    ).one()
    assert kept.branch_name is None


def test_delete_other_user_account_denied(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    foreign = _create_acc(db, other["user_id"])
    resp = client.post(
        f"/profile/bank-accounts/{foreign.id}/delete",
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "حساب بانکی یافت نشد")
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == foreign.id
    ).first() is not None


def test_list_does_not_leak_other_users(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    _create_acc(db, other["user_id"], account_number="9999999999")
    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Non-admin → admin routes
# ---------------------------------------------------------------------------

def test_non_admin_cannot_list_admin_bank_accounts(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.get(f"/admin/profile/{me['user_id']}/bank-accounts")
    assert resp.status_code == 403


def test_non_admin_cannot_create_admin_bank_account(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        f"/admin/profile/{me['user_id']}/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin permission denial (edit_profile not held by role=admin)
# ---------------------------------------------------------------------------

def test_admin_without_edit_profile_denied_list(client, db, make_user):
    admin = make_user(role="admin")
    target = make_user(role="user", balance_al=None)
    _login(client, admin)
    resp = client.get(
        f"/admin/profile/{target['user_id']}/bank-accounts"
    )
    assert resp.status_code == 403


def test_admin_without_edit_profile_denied_create(client, db, make_user):
    admin = make_user(role="admin")
    target = make_user(role="user", balance_al=None)
    _login(client, admin)
    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_super_admin_authorized_list(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _create_acc(db, target["user_id"], account_number="1111111111")
    resp = client.get(f"/admin/profile/{target['user_id']}/bank-accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["account_number"] == "1111111111"


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------

def test_admin_create(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
            "card_number": VALID_CARD,
            "is_primary": "true",
        },
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    row = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == target["user_id"]
    ).one()
    assert row.is_primary is True
    assert row.card_number == VALID_CARD


def test_admin_get(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _create_acc(db, target["user_id"])
    resp = client.get(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}"
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == acc.id


def test_admin_update_delete_set_primary_set_active(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    a1 = _create_acc(db, target["user_id"], account_number="1111111111",
                     is_primary=True)
    a2 = _create_acc(db, target["user_id"], account_number="2222222222")
    base = f"/admin/profile/{target['user_id']}/bank-accounts"

    resp = client.post(
        f"{base}/{a2.id}/set-primary", follow_redirects=False
    )
    _assert_success_redirect(resp)

    resp = client.post(
        f"{base}/{a1.id}/set-active",
        data={"active": "false"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)

    resp = client.post(
        f"{base}/{a2.id}/update",
        data={"account_number": "2222222222", "branch_name": "Admin Branch"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)

    db.expire_all()
    kept_a2 = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == a2.id
    ).one()
    assert kept_a2.is_primary is True
    assert kept_a2.branch_name == "Admin Branch"
    kept_a1 = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == a1.id
    ).one()
    assert kept_a1.is_active is False

    resp = client.post(f"{base}/{a1.id}/delete", follow_redirects=False)
    _assert_success_redirect(resp)
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == a1.id
    ).first() is None


def test_admin_verification(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _create_acc(db, target["user_id"])
    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification",
        data={"status": "verified", "note": "admin ok"},
        follow_redirects=False,
    )
    _assert_success_redirect(resp)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "verified"
    assert kept.verification_note == "admin ok"
    assert kept.verified_by is not None


def test_admin_cross_user_account_not_in_wrong_scope(client, db, make_user):
    """Admin listing target A must not return accounts of user B."""
    _login_super(client, make_user)
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    _create_acc(db, user_b["user_id"], account_number="9999999999")
    resp = client.get(f"/admin/profile/{user_a['user_id']}/bank-accounts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_admin_get_foreign_account_under_wrong_target_404(
    client, db, make_user
):
    _login_super(client, make_user)
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc_b = _create_acc(db, user_b["user_id"])
    resp = client.get(
        f"/admin/profile/{user_a['user_id']}/bank-accounts/{acc_b.id}"
    )
    assert resp.status_code == 404


def test_missing_bank_maps_to_error_redirect(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    resp = client.post(
        "/profile/bank-accounts/add",
        data={"bank_id": "999999", "account_number": "1"},
        follow_redirects=False,
    )
    _assert_error_redirect(resp, "بانک یافت نشد")
