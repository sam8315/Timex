"""
Focused UI/route tests for Phase 6: Admin bank-account UI on
/admin/profile/{target_user_id}.

Covers:
- section renders + list data
- empty state
- add / edit forms (fields, bank select, prefill)
- badges (primary / active / verification)
- create / update / delete / set-primary / activate / deactivate / verification
- validation error flash via ?error=
- permission denial (403) on admin bank POSTs
- inactive account: no set-primary action
- sensitive fields masked in list, full value only in edit form
"""
from database.init_db import seed_banks
from models.bank import Bank
from models.employee_bank_account import EmployeeBankAccount
from web.services.bank_account_service import create_bank_account

from .conftest import login_as, test_engine

HTML_ACCEPT = {"Accept": "text/html"}

VALID_CARD = "6037990000000006"
VALID_SHEBA = "IR940180000000000001234567"
INVALID_CARD = "6037990000000007"


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


def _login_super(client, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    return super_u


def _profile(client, target_user_id):
    resp = client.get(
        f"/admin/profile/{target_user_id}", headers=HTML_ACCEPT
    )
    assert resp.status_code == 200, resp.status_code
    return resp.text


# ---------------------------------------------------------------------------
# Render / list / empty state / forms
# ---------------------------------------------------------------------------

def test_admin_profile_renders_bank_section(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_acc(
        db, target["user_id"],
        account_number="1111111111",
        card_number=VALID_CARD,
        sheba=VALID_SHEBA,
        is_primary=True,
    )

    body = _profile(client, target["user_id"])
    assert "حساب‌های بانکی" in body
    assert "1111111111" in body
    assert f"/admin/profile/{target['user_id']}/bank-accounts/add" in body
    assert "adminAddBankAccountModal" in body
    # badges
    assert "⭐ اصلی" in body
    assert "فعال" in body
    assert "در انتظار بررسی" in body


def test_admin_profile_empty_state(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    body = _profile(client, target["user_id"])
    assert "هیچ حساب بانکی برای این کاربر ثبت نشده است" in body
    assert "افزودن حساب بانکی" in body
    assert "adminAddBankAccountModal" in body


def test_admin_profile_add_form_fields_and_bank_select(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)

    body = _profile(client, target["user_id"])
    assert f"/admin/profile/{target['user_id']}/bank-accounts/add" in body
    for name in [
        "bank_id", "account_number", "branch_name", "branch_code",
        "card_number", "sheba", "account_type", "account_title",
        "description", "is_primary", "is_active",
    ]:
        assert f'name="{name}"' in body, name
    # bank option present (from banks table, not hard-coded JS)
    assert f'<option value="{bank_id}">' in body
    # no JS checksum duplication
    assert "luhn" not in body.lower()
    assert "mod97" not in body.lower()


def test_admin_profile_edit_form_prefilled(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(
        db, target["user_id"],
        account_number="5555555555",
        branch_name="شعبه مرکزی",
        card_number=VALID_CARD,
        sheba=VALID_SHEBA,
    )

    body = _profile(client, target["user_id"])
    assert f"adminEditBankAccountModal-{acc.id}" in body
    assert (
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/update"
        in body
    )
    assert 'value="5555555555"' in body
    assert 'value="شعبه مرکزی"' in body
    # Phase 7: full card/sheba must NOT appear in initial page source
    assert f'value="{VALID_CARD}"' not in body
    assert f'value="{VALID_SHEBA}"' not in body
    assert VALID_CARD not in body
    assert VALID_SHEBA not in body
    # masked placeholders / list masks present
    assert "************0006" in body
    # JS prefill from existing admin GET API on modal open
    assert f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}" in body
    assert 'name="card_number"' in body
    assert 'name="sheba"' in body


def test_list_masks_sensitive_fields(client, db, make_user):
    """Full card/sheba must not appear anywhere in rendered profile HTML."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_acc(db, target["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA)

    body = _profile(client, target["user_id"])
    # sheba last-4 mask present
    assert "************4567" in body or "**************4567" in body
    # full values absent from page source entirely
    assert VALID_CARD not in body
    assert VALID_SHEBA not in body
    # card last-4 mask present
    assert "0006" in body


def test_verification_badges_and_info(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], account_number="1111111111")
    # mark verified via service path
    from web.services.bank_account_service import change_verification_status
    change_verification_status(
        db, target["user_id"], acc.id, "verified",
        changed_by="admin", note="تأیید شد",
    )

    body = _profile(client, target["user_id"])
    assert "تأیید شده" in body
    assert "تأیید شد" in body
    assert f"adminBankVerifyModal-{acc.id}" in body
    assert (
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification"
        in body
    )
    # Jalali-ish timestamp label (server formats)
    assert "آخرین بررسی" in body


def test_inactive_account_hides_set_primary(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], is_active=False, is_primary=False)

    body = _profile(client, target["user_id"])
    assert "غیرفعال" in body
    assert (
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-primary"
        not in body
    )
    # activate action available
    assert (
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-active"
        in body
    )


def test_active_non_primary_has_set_primary(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], is_active=True, is_primary=False)

    body = _profile(client, target["user_id"])
    assert (
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-primary"
        in body
    )


# ---------------------------------------------------------------------------
# Mutations via admin bank routes (as submitted by UI forms)
# ---------------------------------------------------------------------------

def test_admin_create_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={
            "bank_id": str(bank_id),
            "account_number": "1111111111",
            "card_number": VALID_CARD,
            "sheba": VALID_SHEBA,
            "is_primary": "true",
            "is_active": "true",
            "branch_name": "شعبه تست",
            "account_title": "علی رضایی",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert f"/admin/profile/{target['user_id']}" in loc
    assert "success=" in loc

    row = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == target["user_id"]
    ).one()
    assert row.account_number == "1111111111"
    assert row.is_primary is True
    assert row.bank_name  # snapshot set by service

    # title comes from the target's Employee record, not the posted value
    from models.employee import Employee
    emp = db.query(Employee).filter(
        Employee.user_id == target["user_id"]).one()
    assert row.account_title == emp.full_name

    body = _profile(client, target["user_id"])
    assert "1111111111" in body
    assert "شعبه تست" in body
    assert "علی رضایی" not in body
    assert f"به نام: {emp.full_name}" in body


def test_admin_update_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], account_number="1111111111")

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/update",
        data={
            "bank_id": str(acc.bank_id),
            "account_number": "2222222222",
            "branch_name": "شعبه جدید",
            "card_number": VALID_CARD,
            "sheba": VALID_SHEBA,
            "account_type": "جاری",
            "account_title": "عنوان",
            "description": "توضیح",
            "branch_code": "123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.account_number == "2222222222"
    assert kept.branch_name == "شعبه جدید"
    assert kept.account_type == "جاری"
    assert kept.card_number == VALID_CARD
    assert kept.verification_status == "unverified"
    # client-sent account_title ignored; re-derived from Employee on update
    from models.employee import Employee
    emp = db.query(Employee).filter(
        Employee.user_id == target["user_id"]).one()
    assert kept.account_title == emp.full_name
    assert kept.account_title != "عنوان"


def test_admin_delete_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"])

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).first() is None


def test_admin_set_primary_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    first = _make_acc(db, target["user_id"], account_number="1111111111",
                      is_primary=True)
    second = _make_acc(db, target["user_id"], account_number="2222222222")

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{second.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == first.id
    ).one().is_primary is False
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == second.id
    ).one().is_primary is True


def test_admin_activate_deactivate_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], is_active=True)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-active",
        data={"active": "false"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one().is_active is False

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-active",
        data={"active": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one().is_active is True


def test_admin_verification_from_form(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"])

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/verification",
        data={"status": "rejected", "note": "شماره حساب نادرست"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert kept.verification_status == "rejected"
    assert kept.verification_note == "شماره حساب نادرست"
    assert kept.verified_by is not None

    body = _profile(client, target["user_id"])
    assert "رد شده" in body
    assert "شماره حساب نادرست" in body


# ---------------------------------------------------------------------------
# Errors / permissions
# ---------------------------------------------------------------------------

def test_validation_error_shown_as_flash(client, db, make_user):
    """Invalid card → redirect with ?error= containing Persian service message."""
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "1111111111",
            "card_number": INVALID_CARD,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert f"/admin/profile/{target['user_id']}" in loc
    assert "error=" in loc

    # follow redirect: flash renders on profile page
    follow = client.get(loc, headers=HTML_ACCEPT)
    assert follow.status_code == 200
    assert "چک‌سام" in follow.text
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == target["user_id"]
    ).first() is None


def test_inactive_set_primary_error_flash(client, db, make_user):
    _login_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    acc = _make_acc(db, target["user_id"], is_active=False)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/{acc.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_permission_denied_without_edit_profile(client, db, make_user):
    """role=admin lacks edit_profile → admin bank POST returns 403."""
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)

    resp = client.post(
        f"/admin/profile/{target['user_id']}/bank-accounts/add",
        data={"bank_id": str(bank_id), "account_number": "1111111111"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_permission_denied_list_json(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    target = make_user(role="user", balance_al=None)

    resp = client.get(
        f"/admin/profile/{target['user_id']}/bank-accounts"
    )
    assert resp.status_code == 403


def test_non_admin_profile_denied(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    login_as(client, me["national_code"])
    resp = client.get(
        f"/admin/profile/{me['user_id']}", headers=HTML_ACCEPT
    )
    # require_admin on profile route (or redirect) — not a 200 bank section
    assert resp.status_code in (403, 302, 307)
    if resp.status_code == 200:
        assert "حساب‌های بانکی" not in resp.text


def test_unauthorized_profile_redirect(client, db):
    resp = client.get(
        "/admin/profile/X/bank-accounts", follow_redirects=False
    )
    assert resp.status_code == 307
