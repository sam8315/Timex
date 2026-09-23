"""
Focused UI/route tests for Phase 10: user bank-account UI on /profile.

Covers:
- /profile renders bank-account section
- empty state
- account list
- add form
- edit form (masked card/sheba, no full values in initial HTML)
- delete / set-primary / activate / deactivate via own-user routes
- verification status displayed, no verification controls
- own GET API used for edit prefill (no Luhn/MOD-97 in JS)
- user cannot affect another user's account
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


def _login(client, creds):
    login_as(client, creds["national_code"])


def _profile(client) -> str:
    resp = client.get("/profile", headers=HTML_ACCEPT)
    assert resp.status_code == 200, resp.status_code
    return resp.text


# ---------------------------------------------------------------------------
# Rendering / list / empty state / forms
# ---------------------------------------------------------------------------

def test_profile_renders_bank_section(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_acc(
        db, me["user_id"],
        account_number="1111111111",
        card_number=VALID_CARD,
        sheba=VALID_SHEBA,
        is_primary=True,
    )

    body = _profile(client)
    assert "حساب‌های بانکی" in body
    assert "1111111111" in body
    assert "/profile/bank-accounts/add" in body
    assert "addBankAccountModal" in body
    # badges
    assert "⭐ اصلی" in body
    assert "فعال" in body
    assert "در انتظار بررسی" in body


def test_profile_empty_state(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)

    body = _profile(client)
    assert "هیچ حساب بانکی برای شما ثبت نشده است" in body
    assert "افزودن حساب بانکی" in body
    assert "addBankAccountModal" in body


def test_profile_does_not_show_other_users_accounts(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_acc(db, other["user_id"], account_number="9999999999")

    body = _profile(client)
    assert "9999999999" not in body


def test_profile_add_form_fields_and_bank_select(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    bank_id = _seeded_bank_id(db)

    body = _profile(client)
    assert "/profile/bank-accounts/add" in body
    for name in [
        "bank_id", "account_number", "branch_name", "branch_code",
        "card_number", "sheba", "account_type", "account_title",
        "description", "is_primary", "is_active",
    ]:
        assert f'name="{name}"' in body, name
    assert f'<option value="{bank_id}">' in body
    # Persian labels
    for label in ["بانک", "شماره حساب", "نام شعبه", "کد شعبه",
                  "شماره کارت", "شماره شبا", "نوع حساب", "صاحب حساب", "توضیحات"]:
        assert label in body, label
    # no JS checksum duplication
    assert "luhn" not in body.lower()
    assert "mod97" not in body.lower()


def test_profile_edit_form_masked_no_full_values(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(
        db, me["user_id"],
        account_number="5555555555",
        branch_name="شعبه مرکزی",
        card_number=VALID_CARD,
        sheba=VALID_SHEBA,
    )

    body = _profile(client)
    assert f"editBankAccountModal-{acc.id}" in body
    assert f"/profile/bank-accounts/{acc.id}/update" in body
    assert 'value="5555555555"' in body
    assert 'value="شعبه مرکزی"' in body
    # full card/sheba must NOT appear in initial page source
    assert f'value="{VALID_CARD}"' not in body
    assert f'value="{VALID_SHEBA}"' not in body
    assert VALID_CARD not in body
    assert VALID_SHEBA not in body
    # masked placeholders present
    assert "************0006" in body
    # JS prefill from own-user GET API on modal open
    assert f"/profile/bank-accounts/{acc.id}" in body
    assert 'name="card_number"' in body
    assert 'name="sheba"' in body


def test_list_masks_sensitive_fields(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_acc(db, me["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA)

    body = _profile(client)
    assert "************0006" in body or "0006" in body
    assert VALID_CARD not in body
    assert VALID_SHEBA not in body


def test_verification_status_displayed_no_controls(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], account_number="1111111111")
    from web.services.bank_account_service import change_verification_status
    change_verification_status(
        db, me["user_id"], acc.id, "verified",
        changed_by="admin", note="تأیید شد",
    )

    body = _profile(client)
    # status badge shown
    assert "تأیید شده" in body
    # NO verification controls for normal user
    assert "verification" not in body.lower() or f"/profile/bank-accounts/{acc.id}/verification" not in body
    assert f"/profile/bank-accounts/{acc.id}/verification" not in body
    # no admin verification modal
    assert "BankVerifyModal" not in body
    assert "تأیید/رد" not in body


def test_inactive_hides_set_primary(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], is_active=False, is_primary=False)

    body = _profile(client)
    assert "غیرفعال" in body
    assert f"/profile/bank-accounts/{acc.id}/set-primary" not in body
    assert f"/profile/bank-accounts/{acc.id}/set-active" in body


def test_active_non_primary_has_set_primary(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], is_active=True, is_primary=False)

    body = _profile(client)
    assert f"/profile/bank-accounts/{acc.id}/set-primary" in body


# ---------------------------------------------------------------------------
# Mutations via own-user routes (as submitted by UI forms)
# ---------------------------------------------------------------------------

def test_user_create_from_form(client, db, make_user):
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
            "branch_name": "شعبه تست",
            "account_title": "علی رضایی",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert "/profile" in loc
    assert "success=" in loc

    row = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == me["user_id"]
    ).one()
    assert row.account_number == "1111111111"
    assert row.is_primary is True
    # client-sent account_title is ignored; value comes from Employee
    from models.employee import Employee
    emp = db.query(Employee).filter(
        Employee.user_id == me["user_id"]).one()
    assert row.account_title == emp.full_name
    assert row.account_title != "علی رضایی"


def test_user_update_from_form(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], account_number="1111111111")

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/update",
        data={
            "bank_id": str(_seeded_bank_id(db)),
            "account_number": "2222222222",
            "branch_name": "شعبه جدید",
            "branch_code": "042",
            "account_type": "جاری",
            "account_title": "عنوان جدید",
            "description": "توضیح",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.refresh(acc)
    assert acc.account_number == "2222222222"
    assert acc.branch_name == "شعبه جدید"
    assert acc.branch_code == "042"
    assert acc.account_type == "جاری"
    # client-sent account_title is ignored; server re-derives from Employee
    from models.employee import Employee
    emp = db.query(Employee).filter(
        Employee.user_id == me["user_id"]).one()
    assert acc.account_title == emp.full_name
    assert acc.description == "توضیح"


def test_user_delete_from_form(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"])

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).first() is None


def test_user_set_primary_from_form(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    first = _make_acc(db, me["user_id"], account_number="111", is_primary=True)
    second = _make_acc(db, me["user_id"], account_number="222", is_primary=False)

    resp = client.post(
        f"/profile/bank-accounts/{second.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.refresh(first)
    db.refresh(second)
    assert first.is_primary is False
    assert second.is_primary is True


def test_user_activate_deactivate_from_form(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], is_active=True, is_primary=False)

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-active",
        data={"active": "false"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(acc)
    assert acc.is_active is False

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-active",
        data={"active": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(acc)
    assert acc.is_active is True


def test_validation_error_flash(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    bank_id = _seeded_bank_id(db)

    resp = client.post(
        "/profile/bank-accounts/add",
        data={
            "bank_id": str(bank_id),
            "account_number": "1111111111",
            "card_number": INVALID_CARD,
            "is_primary": "true",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    follow = client.get(resp.headers["location"], headers=HTML_ACCEPT)
    assert follow.status_code == 200
    assert "چک‌سام" in follow.text
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == me["user_id"]
    ).first() is None


def test_inactive_set_primary_error(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, me["user_id"], is_active=False)

    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Cross-user / security
# ---------------------------------------------------------------------------

def test_user_cannot_touch_other_users_account(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    acc = _make_acc(db, other["user_id"], account_number="999")

    # update denied
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/update",
        data={"account_number": "123", "bank_id": str(_seeded_bank_id(db))},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    # delete denied
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    # set-primary denied
    resp = client.post(
        f"/profile/bank-accounts/{acc.id}/set-primary",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]

    db.refresh(acc)
    assert acc.account_number == "999"
    assert acc.is_primary is False


def test_get_api_scoped_to_owner(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    my_acc = _make_acc(db, me["user_id"], account_number="111")
    other_acc = _make_acc(db, other["user_id"], account_number="999")

    resp = client.get(f"/profile/bank-accounts/{my_acc.id}")
    assert resp.status_code == 200
    assert resp.json()["account_number"] == "111"

    resp = client.get(f"/profile/bank-accounts/{other_acc.id}")
    assert resp.status_code == 404


def test_list_api_only_own_accounts(client, db, make_user):
    me = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    _login(client, me)
    _make_acc(db, me["user_id"], account_number="111")
    _make_acc(db, other["user_id"], account_number="999")

    resp = client.get("/profile/bank-accounts")
    assert resp.status_code == 200
    nums = [a["account_number"] for a in resp.json()]
    assert "111" in nums
    assert "999" not in nums
