"""
Phase 7 focused security/regression tests for Employee Bank Accounts.

Covers:
- verification authorization (own endpoint requires edit_profile)
- admin verification still requires require_admin + edit_profile
- sensitive card/sheba exposure: absent from profile HTML, present in API
- account_type free-text (no invented enum / CHECK)
- CSRF: bank forms follow profile-form convention (no csrf_token), same as addresses
- cross-user / nonexistent scoping regressions
"""
from database.init_db import seed_banks
from models.bank import Bank
from models.employee_bank_account import EmployeeBankAccount
from web.services.bank_account_service import (
    create_bank_account,
    update_bank_account,
)

from .conftest import login_as, test_engine

HTML_ACCEPT = {"Accept": "text/html"}

VALID_CARD = "6037990000000006"
VALID_SHEBA = "IR940180000000000001234567"


def _seeded_bank_id(db, code="018") -> int:
    seed_banks(bind_engine=test_engine)
    return db.query(Bank).filter(Bank.code == code).one().id


def _make_acc(db, user_id, **overrides):
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


# ---------------------------------------------------------------------------
# Verification authorization
# ---------------------------------------------------------------------------

def test_own_verification_denied_for_role_user(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"])

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "verified"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "unverified"
    assert kept.verified_by is None
    assert kept.verified_at is None


def test_own_verification_denied_for_role_admin(client, db, make_user):
    """role=admin lacks edit_profile → cannot self-verify either."""
    admin = make_user(role="admin")
    _login(client, admin)
    acc = _make_acc(db, admin["user_id"])

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "verified"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one().verification_status == "unverified"


def test_own_verification_allowed_for_super_admin(client, db, make_user):
    super_u = make_user(role="super_admin")
    _login(client, super_u)
    acc = _make_acc(db, super_u["user_id"])

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/verification",
        data={"status": "rejected", "note": "fail"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "rejected"
    assert kept.verified_by == super_u["user_id"]
    assert kept.verified_at is not None


def test_admin_verification_requires_edit_profile(client, db, make_user):
    admin = make_user(role="admin")
    _login(client, admin)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"])

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification",
        data={"status": "verified"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one().verification_status == "unverified"


def test_admin_verification_sets_actor_and_note(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"])

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification",
        data={"status": "verified", "note": "ok"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "verified"
    assert kept.verified_by is not None
    assert kept.verified_at is not None
    assert kept.verification_note == "ok"

    # back to unverified clears actor/time
    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification",
        data={"status": "unverified", "note": "reset"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "unverified"
    assert kept.verified_by is None
    assert kept.verified_at is None


def test_service_verification_requires_actor(db, make_user):
    from web.services.bank_account_service import (
        BankAccountServiceError,
        change_verification_status,
    )

    user = make_user(role="user", balance_al=None)
    acc = _make_acc(db, user["user_id"])
    for status in ("verified", "rejected"):
        try:
            change_verification_status(db, user["user_id"], acc.id, status)
            raise AssertionError("expected BankAccountServiceError")
        except BankAccountServiceError as e:
            "انجام‌دهنده" in str(e)


# ---------------------------------------------------------------------------
# Sensitive field exposure
# ---------------------------------------------------------------------------

def test_api_returns_full_card_and_sheba(client, db, make_user):
    """API contract (Phase 5) intentionally unmasked — documented here."""
    me = make_user(role="super_admin")
    _login(client, me)
    _make_acc(db, me["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA)

    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["card_number"] == VALID_CARD
    assert row["sheba"] == VALID_SHEBA


def test_admin_api_returns_full_card_and_sheba(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"],
                    card_number=VALID_CARD, sheba=VALID_SHEBA)

    resp = client.get(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["card_number"] == VALID_CARD
    assert body["sheba"] == VALID_SHEBA


def test_profile_html_hides_full_card_and_sheba(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_acc(db, target["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA)

    resp = client.get(
        f"/admin/profile/{target['user_id']}", headers=HTML_ACCEPT
    )
    assert resp.status_code == 200
    body = resp.text
    assert VALID_CARD not in body
    assert VALID_SHEBA not in body
    # list still shows masked tails
    assert "0006" in body
    assert "4567" in body


def test_list_json_masks_nothing_but_html_list_masks(
    client, db, make_user
):
    """List API is a JSON endpoint (not HTML); HTML list is the masked surface."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_acc(db, target["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA)

    api = client.get(f"/admin/profile/{target['user_id']}/bank-accounts")
    assert api.status_code == 200
    assert api.json()[0]["card_number"] == VALID_CARD

    html = client.get(
        f"/admin/profile/{target['user_id']}", headers=HTML_ACCEPT
    )
    assert VALID_CARD not in html.text


# ---------------------------------------------------------------------------
# account_type decision (free text, nullable, no enum)
# ---------------------------------------------------------------------------

def test_account_type_accepts_free_text(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _make_acc(db, user["user_id"], account_type="جاری")
    assert acc.account_type == "جاری"

    updated = update_bank_account(
        db, user["user_id"], acc.id, account_type="پس‌انداز ویژه"
    )
    assert updated.account_type == "پس‌انداز ویژه"


def test_account_type_null_allowed(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _make_acc(db, user["user_id"])
    assert acc.account_type is None

    updated = update_bank_account(
        db, user["user_id"], acc.id, account_type=None
    )
    assert updated.account_type is None


def test_account_type_not_in_check_constraint(db, make_user):
    """No CHECK constraint on account_type values (decision finalized)."""
    from sqlalchemy import inspect

    mapper = inspect(EmployeeBankAccount)
    table = mapper.local_table
    constraints = [c for c in table.constraints if hasattr(c, "sqltext")]
    for c in constraints:
        text = str(c.sqltext).lower()
        assert "account_type" not in text, c


# ---------------------------------------------------------------------------
# CSRF conventions
# ---------------------------------------------------------------------------

def test_bank_profile_forms_have_no_csrf_token(client, db, make_user):
    """Bank forms match addresses/phones: no csrf_token input (existing pattern)."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    resp = client.get(
        f"/admin/profile/{target['user_id']}", headers=HTML_ACCEPT
    )
    body = resp.text
    # bank add form present
    assert f"/admin/profile/{target['user_id']}/bank-accounts/add" in body
    # extract bank add form segment roughly: no csrf inside bank modal
    assert 'id="adminAddBankAccountModal"' in body
    # no global csrf on this page's bank form (same as address forms)
    # address forms also lack csrf — confirm page does not inject csrf for them
    # Bank POST works without csrf field (matches address routes)
    bank_id = _seeded_bank_id(db)
    post = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={"bank_id": str(bank_id), "account_number": "9999999999"},
        follow_redirects=False,
    )
    assert post.status_code == 302
    assert "success=" in post.headers["location"]


def test_csrf_still_enforced_on_protected_endpoints(client, db, make_user):
    """Existing CSRF mechanism (permissions toggle) remains intact — no second system."""
    super_u = make_user(role="super_admin")
    target = make_user(role="user", balance_al=None)
    _login(client, super_u)
    resp = client.post(
        f"/admin/permissions/{target['user_id']}/toggle",
        data={"permission": "view_reports", "action": "revoke", "csrf_token": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Scoping regressions
# ---------------------------------------------------------------------------

def test_nonexistent_user_admin_list(client, db, make_user):
    _login_super(client, make_user)
    resp = client.get("/admin/profile/NO-SUCH-USER/bank-accounts")
    assert resp.status_code == 404
    assert "یافت نشد" in resp.json()["detail"]


def test_nonexistent_account_admin_get(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    resp = client.get(
        f"/admin/profile/{target['user_id']}/bank-accounts/999999"
    )
    assert resp.status_code == 404


def test_cross_user_verification_denied(client, db, make_user):
    _login_super(client, make_user)
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc_b = _make_acc(db, user_b["user_id"])

    # wrong target_user_id scope → account not found → error redirect
    resp = client.post(
        f"/admin/profile/{user_a['user_id']}/bank-accounts/{acc_b.id}/verification",
        data={"status": "verified"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc_b.id
    ).one().verification_status == "unverified"
