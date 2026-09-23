"""
Focused UX tests for the bank-account form fields on /profile (user) and
/admin/profile/{id} (admin):

Card (شماره کارت):
- placeholder absent
- no helper/checksum text (formatting or validation hints)
- numeric input only (inputmode + JS digit-only normalization)
- visual 4-4-4-4 grouping with '-'
- submitted value contains no hyphens
- leading zeros preserved
- max 16 digits

Sheba (شماره شبا):
- placeholder absent
- no helper/checksum text
- fixed, non-editable IR prefix (visible span + hidden composed field)
- control forces LTR order (IR then digits) inside the RTL page
- only numeric digits editable
- max 24 editable digits
- submitted value is IR + 24 digits
- leading zeros preserved

Account number (شماره حساب):
- numeric-only input (inputmode + JS digit normalization)
- no placeholder / no helper text
- max 50 digits (backend String(50) limit)
- submitted value is a plain numeric string
- leading zeros preserved

Account owner (نام صاحب حساب):
- form displays the Employee full name
- owner field is read-only in the UI
- create ignores any client-supplied account_title
- update ignores any client-supplied account_title
- stored value always matches the Employee name

No Luhn / MOD-97 logic exists in the shipped JavaScript; the server remains
authoritative for all validation.
"""
import re
from pathlib import Path

from database.init_db import seed_banks
from models.bank import Bank
from models.employee import Employee
from models.employee_bank_account import EmployeeBankAccount
from web.services.bank_account_service import create_bank_account

from .conftest import login_as, test_engine

HTML_ACCEPT = {"Accept": "text/html"}

VALID_CARD = "6037990000000006"
VALID_CARD_HYPHENS = "6037-9900-0000-0006"
VALID_CARD_ZEROS = "0000111122223337"
VALID_SHEBA = "IR940180000000000001234567"
VALID_SHEBA_ZEROS = "IR320180000000000000000000"

JS_PATH = (
    Path(__file__).resolve().parents[1]
    / "web" / "static" / "js" / "bank_fields.js"
)


def _bank_js() -> str:
    assert JS_PATH.exists(), f"missing {JS_PATH}"
    return JS_PATH.read_text(encoding="utf-8")


def _input_tags(body: str, name: str) -> list:
    """Whole <input> tags carrying name="..." (attrs may span lines)."""
    return re.findall(
        r'<input[^>]*name="%s"[^>]*>' % re.escape(name), body
    )


def _input_tags_with_attr(body: str, attr: str) -> list:
    """Whole <input> tags carrying an arbitrary attribute."""
    return re.findall(r'<input[^>]*%s[^>]*>' % re.escape(attr), body)


def _employee_full_name(db, user_id: str) -> str:
    emp = db.query(Employee).filter(Employee.user_id == user_id).one()
    return emp.full_name


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


def _surfaces(client, db, make_user):
    """Build both bank-form surfaces (normal user + admin) for one test.

    Returns two dicts; each carries its rendered page body, the owner's
    user_id, its existing account (so the edit modal renders), the POST
    URLs, and a callable restoring the correct session before POSTing.
    """
    me = make_user(role="user", balance_al=None)
    super_u = make_user(role="super_admin")
    target = make_user(role="user", balance_al=None)

    user_acc = _make_acc(
        db, me["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA
    )
    admin_acc = _make_acc(
        db, target["user_id"], card_number=VALID_CARD, sheba=VALID_SHEBA
    )

    login_as(client, me["national_code"])
    user_body = client.get("/profile", headers=HTML_ACCEPT).text
    login_as(client, super_u["national_code"])
    admin_body = client.get(
        f"/admin/profile/{target['user_id']}", headers=HTML_ACCEPT
    ).text

    return [
        {
            "name": "user",
            "owner_user_id": me["user_id"],
            "body": user_body,
            "acc": user_acc,
            "add": "/profile/bank-accounts/add",
            "update": lambda acc_id: f"/profile/bank-accounts/{acc_id}/update",
            "login": lambda: login_as(client, me["national_code"]),
        },
        {
            "name": "admin",
            "owner_user_id": target["user_id"],
            "body": admin_body,
            "acc": admin_acc,
            "add": (
                f"/admin/profile/{target['user_id']}/bank-accounts/add"
            ),
            "update": lambda acc_id: (
                f"/admin/profile/{target['user_id']}"
                f"/bank-accounts/{acc_id}/update"
            ),
            "login": lambda: login_as(client, super_u["national_code"]),
        },
    ]


def _create_form_data(bank_id, **extra):
    data = {
        "bank_id": str(bank_id),
        "account_number": "1111111111",
        "is_primary": "false",
        "is_active": "true",
    }
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Card UI
# ---------------------------------------------------------------------------

def test_card_and_sheba_helper_text_absent(client, db, make_user):
    """No visible formatting/validation hint under card or sheba fields."""
    forbidden = (
        "نمایش گروه‌بندی",
        "گروه‌بندی 4-4-4-4",
        "نمایش 4-4-4-4",
        "اعتبارسنجی چک‌سام",
        "چک‌سام سمت سرور",
        "پیشوند IR ثابت است",
        "۱۶ رقم",
        "24 رقم؛",
        "Luhn",
        "MOD-97",
        "چک‌سام",
    )
    for surf in _surfaces(client, db, make_user):
        body = surf["body"]
        for phrase in forbidden:
            assert phrase not in body, (surf["name"], phrase)


def test_card_placeholder_absent(client, db, make_user):
    for surf in _surfaces(client, db, make_user):
        tags = _input_tags(surf["body"], "card_number")
        assert len(tags) >= 2, surf["name"]  # add + edit form
        for tag in tags:
            assert "placeholder" not in tag, (surf["name"], tag)
        assert "6037990000000000" not in surf["body"], surf["name"]


def test_card_numeric_input_only(client, db, make_user):
    js = _bank_js()
    # JS keeps digits only and normalizes Persian/Arabic digits
    assert "toAsciiDigits" in js
    assert "MAX_CARD_DIGITS = 16" in js
    for surf in _surfaces(client, db, make_user):
        assert "/static/js/bank_fields.js" in surf["body"], surf["name"]
        tags = _input_tags(surf["body"], "card_number")
        assert tags, surf["name"]
        for tag in tags:
            assert 'inputmode="numeric"' in tag, (surf["name"], tag)
            assert "data-bank-card" in tag, (surf["name"], tag)
            assert "pattern=" not in tag, (surf["name"], tag)


def test_card_visual_4444_grouping(client, db, make_user):
    js = _bank_js()
    # visual grouping into 4-digit blocks separated by '-'
    assert "formatCard" in js
    assert "match(/.{1,4}/g)" in js
    assert "join('-')" in js
    for surf in _surfaces(client, db, make_user):
        assert "data-bank-card" in surf["body"], surf["name"]
        # 16 digits + 3 hyphens is the max displayed length
        for tag in _input_tags(surf["body"], "card_number"):
            assert 'maxlength="19"' in tag, (surf["name"], tag)


def test_card_submitted_value_has_no_hyphens(client, db, make_user):
    js = _bank_js()
    # submit handler strips hyphens before the form is sent
    assert "card.value = cardDigits(card.value)" in js

    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, card_number=VALID_CARD_HYPHENS),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.card_number == VALID_CARD
        assert "-" not in row.card_number
        assert row.card_number == VALID_CARD_HYPHENS.replace("-", "")


def test_card_leading_zeros_preserved(client, db, make_user):
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, card_number=VALID_CARD_ZEROS),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.card_number == VALID_CARD_ZEROS
        assert row.card_number.startswith("0000")


def test_card_max_16_digits(client, db, make_user):
    js = _bank_js()
    assert "MAX_CARD_DIGITS = 16" in js
    assert "slice(0, MAX_CARD_DIGITS)" in js

    too_long = "60379900000000061"  # 17 digits
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, card_number=too_long),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "error=" in resp.headers["location"], surf["name"]
        assert (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.card_number == too_long)
            .first()
            is None
        )


# ---------------------------------------------------------------------------
# Sheba UI
# ---------------------------------------------------------------------------

def test_sheba_placeholder_absent(client, db, make_user):
    for surf in _surfaces(client, db, make_user):
        for tag in _input_tags_with_attr(surf["body"], "data-sheba-digits"):
            assert "placeholder" not in tag, (surf["name"], tag)
        for tag in _input_tags(surf["body"], "sheba"):
            assert "placeholder" not in tag, (surf["name"], tag)
        assert "IR000000000000000000000000" not in surf["body"], surf["name"]


def test_sheba_fixed_ir_prefix_and_hidden_composed_field(client, db, make_user):
    for surf in _surfaces(client, db, make_user):
        body = surf["body"]
        assert "/static/css/bank_fields.css" in body, surf["name"]
        # fixed, visible IR prefix (not typed by the user)
        assert body.count('<span class="bank-sheba-prefix">IR</span>') >= 2, (
            surf["name"]
        )
        # editable area carries no name → user text is never submitted raw
        digit_tags = _input_tags_with_attr(body, "data-sheba-digits")
        assert digit_tags, surf["name"]
        for tag in digit_tags:
            assert "name=" not in tag, (surf["name"], tag)
            assert "placeholder" not in tag, (surf["name"], tag)
            assert 'aria-label="24 رقم شماره شبا"' in tag, (surf["name"], tag)
            assert 'maxlength="24"' in tag, (surf["name"], tag)
        # the server-facing sheba field is the hidden composed input
        hidden_tags = _input_tags(body, "sheba")
        assert hidden_tags, surf["name"]
        for tag in hidden_tags:
            assert 'type="hidden"' in tag, (surf["name"], tag)
            assert "data-sheba-hidden" in tag, (surf["name"], tag)


def test_sheba_ltr_order_inside_rtl_page(client, db, make_user):
    """IR prefix renders before the digits, LTR, in the RTL Persian page."""
    for surf in _surfaces(client, db, make_user):
        body = surf["body"]
        # the whole control is forced LTR (add + edit forms)
        assert body.count('<div class="bank-sheba" dir="ltr">') >= 2, (
            surf["name"]
        )
        # DOM order: IR prefix first, then the editable digits → visual `IR …`
        assert body.index('class="bank-sheba-prefix"') < body.index(
            "data-sheba-digits"
        ), surf["name"]
        # digits stay LTR and are not reversed by the page direction
        for tag in _input_tags_with_attr(body, "data-sheba-digits"):
            assert 'dir="rtl"' not in tag, (surf["name"], tag)


def test_sheba_numeric_only_and_max_24_digits(client, db, make_user):
    js = _bank_js()
    assert "toAsciiDigits" in js
    assert "MAX_SHEBA_DIGITS = 24" in js
    assert "slice(0, MAX_SHEBA_DIGITS)" in js
    for surf in _surfaces(client, db, make_user):
        assert "/static/js/bank_fields.js" in surf["body"], surf["name"]
        for tag in _input_tags_with_attr(surf["body"], "data-sheba-digits"):
            assert 'inputmode="numeric"' in tag, (surf["name"], tag)
            assert 'maxlength="24"' in tag, (surf["name"], tag)


def test_sheba_submitted_value_is_ir_plus_24_digits(client, db, make_user):
    js = _bank_js()
    # hidden field is composed as 'IR' + digits on submit
    assert "'IR' + digits" in js
    assert "prepareSubmit" in js

    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, sheba=VALID_SHEBA),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.sheba == VALID_SHEBA
        assert re.fullmatch(r"IR[0-9]{24}", row.sheba)


def test_sheba_leading_zeros_preserved(client, db, make_user):
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, sheba=VALID_SHEBA_ZEROS),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.sheba == VALID_SHEBA_ZEROS
        assert row.sheba[2:].startswith("320")


def test_sheba_max_24_editable_digits_rejected_by_server(client, db, make_user):
    too_long = "IR" + "0" * 25  # 25 digits after IR
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, sheba=too_long),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "error=" in resp.headers["location"], surf["name"]
        assert (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.sheba == too_long)
            .first()
            is None
        )


# ---------------------------------------------------------------------------
# Account number (شماره حساب)
# ---------------------------------------------------------------------------

def test_account_number_numeric_only_attributes(client, db, make_user):
    """All four forms: numeric keyboard, 50-digit cap, no placeholder/help."""
    for surf in _surfaces(client, db, make_user):
        tags = _input_tags(surf["body"], "account_number")
        assert len(tags) >= 2, surf["name"]  # add + edit form
        for tag in tags:
            assert 'inputmode="numeric"' in tag, (surf["name"], tag)
            assert "data-account-number" in tag, (surf["name"], tag)
            assert 'maxlength="50"' in tag, (surf["name"], tag)
            assert 'type="text"' in tag, (surf["name"], tag)
            assert "placeholder" not in tag, (surf["name"], tag)
        assert "شماره حساب" in surf["body"], surf["name"]
        assert "فقط عدد" not in surf["body"], surf["name"]  # no helper text


def test_account_number_js_digits_only(client, db, make_user):
    js = _bank_js()
    # digits-only normalization (Persian/Arabic → ASCII), 50-digit cap,
    # stripped again right before submit → plain numeric string
    assert "MAX_ACCOUNT_DIGITS = 50" in js
    assert "accountNumberValue" in js
    assert "toAsciiDigits(value).slice(0, MAX_ACCOUNT_DIGITS)" in js
    assert "account.value = accountNumberValue(account.value)" in js
    for surf in _surfaces(client, db, make_user):
        assert "/static/js/bank_fields.js" in surf["body"], surf["name"]


def test_account_number_leading_zeros_roundtrip(client, db, make_user):
    """Plain numeric submission keeps leading zeros end-to-end."""
    account_number = "0001234567890123456789"
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(bank_id, account_number=account_number),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.account_number == account_number
        assert row.account_number.startswith("000")
        assert row.account_number.isdigit()


# ---------------------------------------------------------------------------
# Account owner (نام صاحب حساب)
# ---------------------------------------------------------------------------

def test_owner_field_shows_employee_name_and_readonly(client, db, make_user):
    for surf in _surfaces(client, db, make_user):
        full_name = _employee_full_name(db, surf["owner_user_id"])
        tags = _input_tags(surf["body"], "account_title")
        assert len(tags) >= 2, surf["name"]  # add + edit form
        for tag in tags:
            assert "readonly" in tag, (surf["name"], tag)
            assert f'value="{full_name}"' in tag, (surf["name"], tag)


def test_create_ignores_client_account_title(client, db, make_user):
    bank_id = _seeded_bank_id(db)
    fake_title = "عنوان دلخواه کلاینت"
    for surf in _surfaces(client, db, make_user):
        full_name = _employee_full_name(db, surf["owner_user_id"])
        surf["login"]()
        resp = client.post(
            surf["add"],
            data=_create_form_data(
                bank_id,
                account_title=fake_title,
                card_number=VALID_CARD,
                sheba=VALID_SHEBA,
            ),
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]
        row = (
            db.query(EmployeeBankAccount)
            .filter(EmployeeBankAccount.user_id == surf["owner_user_id"])
            .order_by(EmployeeBankAccount.id.desc())
            .first()
        )
        assert row.account_title == full_name
        assert row.account_title != fake_title


def test_update_ignores_client_account_title(client, db, make_user):
    fake_title = "عنوان جعلی هنگام ویرایش"
    for surf in _surfaces(client, db, make_user):
        full_name = _employee_full_name(db, surf["owner_user_id"])
        acc = surf["acc"]
        # tamper the stored title directly (simulates arbitrary/legacy data)
        acc.account_title = "عنوان قدیمی آزاد"
        db.commit()

        surf["login"]()
        resp = client.post(
            surf["update"](acc.id),
            data={
                "bank_id": str(acc.bank_id),
                "account_number": acc.account_number,
                "account_title": fake_title,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, surf["name"]
        assert "success=" in resp.headers["location"], surf["name"]

        db.expire_all()
        kept = db.query(EmployeeBankAccount).filter(
            EmployeeBankAccount.id == acc.id
        ).one()
        # server re-derives from Employee on every update
        assert kept.account_title == full_name
        assert kept.account_title != fake_title
        assert kept.account_title != "عنوان قدیمی آزاد"


def test_stored_owner_always_matches_employee_name(client, db, make_user):
    """Create + update both leave account_title equal to Employee.full_name."""
    bank_id = _seeded_bank_id(db)
    for surf in _surfaces(client, db, make_user):
        full_name = _employee_full_name(db, surf["owner_user_id"])
        acc = surf["acc"]
        assert acc.account_title == full_name

        surf["login"]()
        resp = client.post(
            surf["update"](acc.id),
            data={
                "bank_id": str(acc.bank_id),
                "account_number": acc.account_number,
                "account_title": "هر عنوانی غیر از نام کارمند",
            },
            follow_redirects=False,
        )
        assert "success=" in resp.headers["location"], surf["name"]
        db.expire_all()
        kept = db.query(EmployeeBankAccount).filter(
            EmployeeBankAccount.id == acc.id
        ).one()
        assert kept.account_title == full_name
