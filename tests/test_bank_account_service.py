"""
Focused tests for the Employee Bank Account service layer (Phase 3).

Covers:
- list / get bank accounts
- create / update / delete
- multiple accounts per user
- set primary / switching primary
- inactive account cannot become Primary
- deactivating the active Primary (allowed, no auto-reassignment)
- reactivation
- verification status transitions
- string / leading-zero preservation
- cross-user scoping and error behavior
"""
import pytest

from database.init_db import seed_banks
from models.bank import Bank
from models.employee_bank_account import EmployeeBankAccount
from web.services.bank_account_service import (
    BankAccountServiceError,
    list_bank_accounts,
    get_bank_account,
    create_bank_account,
    update_bank_account,
    delete_bank_account,
    set_primary_bank_account,
    set_active_bank_account,
    change_verification_status,
)

from .conftest import test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seeded_bank_id(db, code="018") -> int:
    seed_banks(bind_engine=test_engine)
    return db.query(Bank).filter(Bank.code == code).one().id


@pytest.fixture
def inactive_bank(db):
    """Get-or-create an inactive bank row; always removed after the test."""
    bank = db.query(Bank).filter(Bank.code == "99X").first()
    if not bank:
        bank = Bank(
            code="99X",
            name="Inactive Test Bank",
            country_code="IR",
            is_active=False,
            sort_order=999,
        )
        db.add(bank)
        db.commit()
    elif bank.is_active:
        bank.is_active = False
        db.commit()
    else:
        db.refresh(bank)
    try:
        yield bank
    finally:
        db.query(EmployeeBankAccount).filter(
            EmployeeBankAccount.bank_id == bank.id
        ).delete(synchronize_session=False)
        db.query(Bank).filter(Bank.id == bank.id).delete(
            synchronize_session=False
        )
        db.commit()


def _create_acc(db, user_id, **overrides):
    defaults = dict(
        bank_id=_seeded_bank_id(db),
        account_number="12345678901234567890",
        is_primary=False,
        is_active=True,
    )
    defaults.update(overrides)
    return create_bank_account(db, user_id=user_id, **defaults)


# ---------------------------------------------------------------------------
# List accounts
# ---------------------------------------------------------------------------

def test_list_bank_accounts_empty(db, make_user):
    user = make_user(role="user", balance_al=None)
    assert list_bank_accounts(db, user["user_id"]) == []


def test_list_bank_accounts_returns_all(db, make_user):
    user = make_user(role="user", balance_al=None)
    _create_acc(db, user["user_id"], account_number="1111111111")
    _create_acc(db, user["user_id"], account_number="2222222222")
    result = list_bank_accounts(db, user["user_id"])
    assert len(result) == 2


def test_list_bank_accounts_ordered_primary_first(db, make_user):
    user = make_user(role="user", balance_al=None)
    _create_acc(db, user["user_id"], account_number="1111111111", is_primary=False)
    _create_acc(db, user["user_id"], account_number="2222222222", is_primary=True)
    result = list_bank_accounts(db, user["user_id"])
    assert result[0].is_primary is True
    assert result[0].account_number == "2222222222"


def test_list_bank_accounts_nonexistent_user_raises(db):
    with pytest.raises(BankAccountServiceError, match="کاربر یافت نشد"):
        list_bank_accounts(db, "NONEXISTENT-USER")


# ---------------------------------------------------------------------------
# Get account
# ---------------------------------------------------------------------------

def test_get_bank_account_by_id(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], account_number="1111111111")
    result = get_bank_account(db, user["user_id"], acc.id)
    assert result.id == acc.id
    assert result.account_number == "1111111111"


def test_get_bank_account_nonexistent_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        get_bank_account(db, user["user_id"], 999999)


def test_get_bank_account_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        get_bank_account(db, user_a["user_id"], acc.id)


def test_get_bank_account_nonexistent_user_raises(db):
    with pytest.raises(BankAccountServiceError, match="کاربر یافت نشد"):
        get_bank_account(db, "NONEXISTENT", 1)


# ---------------------------------------------------------------------------
# Create account
# ---------------------------------------------------------------------------

def test_create_bank_account_basic(db, make_user):
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    acc = _create_acc(db, user["user_id"], bank_id=bank_id, account_number="1111111111")
    assert acc.id is not None
    assert acc.user_id == user["user_id"]
    assert acc.bank_id == bank_id
    assert acc.account_number == "1111111111"
    assert acc.is_primary is False
    assert acc.is_active is True
    assert acc.verification_status == "unverified"
    assert acc.verified_at is None
    assert acc.verified_by is None


def test_create_snapshots_bank_name(db, make_user):
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db, "018")
    acc = _create_acc(db, user["user_id"], bank_id=bank_id)
    bank = db.query(Bank).filter(Bank.id == bank_id).one()
    assert acc.bank_name == bank.name == "Tejarat"


def test_create_with_optional_fields(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(
        db, user["user_id"],
        account_number="1111111111",
        branch_name="Branch A",
        branch_code="001",
        card_number="6037991111111111",
        sheba="IR000000000000000000000001",
        account_type="current",
        account_title="Test Title",
        description="note",
    )
    assert acc.branch_name == "Branch A"
    assert acc.branch_code == "001"
    assert acc.card_number == "6037991111111111"
    assert acc.sheba == "IR000000000000000000000001"
    assert acc.account_type == "current"
    assert acc.account_title == "Test Title"
    assert acc.description == "note"


def test_create_nonexistent_user_raises(db):
    with pytest.raises(BankAccountServiceError, match="کاربر یافت نشد"):
        create_bank_account(
            db=db,
            user_id="NONEXISTENT",
            bank_id=1,
            account_number="1111111111",
        )


def test_create_empty_account_number_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    for bad in (None, "", "   "):
        with pytest.raises(BankAccountServiceError, match="شماره حساب"):
            _create_acc(db, user["user_id"], account_number=bad)


def test_create_nonexistent_bank_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="بانک یافت نشد"):
        _create_acc(db, user["user_id"], bank_id=999999)


def test_create_inactive_bank_rejected(db, make_user, inactive_bank):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="بانک غیرفعال"):
        _create_acc(db, user["user_id"], bank_id=inactive_bank.id)


def test_create_primary_inactive_combo_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب غیرفعال نمی‌تواند اصلی باشد"):
        _create_acc(db, user["user_id"], is_primary=True, is_active=False)


def test_create_primary_unsets_previous(db, make_user):
    user = make_user(role="user", balance_al=None)
    first = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    second = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=True)

    db.expire_all()
    first_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == first.id).one()
    second_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == second.id).one()
    assert first_reloaded.is_primary is False
    assert second_reloaded.is_primary is True


def test_create_inactive_optional_defaults(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], branch_name=None, card_number=None, sheba=None)
    assert acc.branch_name is None
    assert acc.card_number is None
    assert acc.sheba is None


# ---------------------------------------------------------------------------
# Update account
# ---------------------------------------------------------------------------

def test_update_bank_account_fields(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], account_number="1111111111")
    updated = update_bank_account(
        db, user["user_id"], acc.id,
        account_number="9999999999",
        branch_name="New Branch",
    )
    assert updated.account_number == "9999999999"
    assert updated.branch_name == "New Branch"
    assert updated.bank_id == acc.bank_id


def test_update_keeps_omitted_fields(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(
        db, user["user_id"],
        account_number="1111111111",
        branch_name="Branch A",
        card_number="6037991111111111",
    )
    updated = update_bank_account(db, user["user_id"], acc.id, branch_code="042")
    assert updated.account_number == "1111111111"
    assert updated.branch_name == "Branch A"
    assert updated.card_number == "6037991111111111"
    assert updated.branch_code == "042"


def test_update_none_clears_optional_field(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], branch_name="Branch A", card_number="6037")
    updated = update_bank_account(
        db, user["user_id"], acc.id, branch_name=None, card_number=None
    )
    assert updated.branch_name is None
    assert updated.card_number is None


def test_update_rejects_empty_account_number(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], account_number="1111111111")
    with pytest.raises(BankAccountServiceError, match="شماره حساب"):
        update_bank_account(db, user["user_id"], acc.id, account_number="   ")
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id).one()
    assert kept.account_number == "1111111111"


def test_update_change_bank_resnapshots_name(db, make_user):
    user = make_user(role="user", balance_al=None)
    tejarat = _seeded_bank_id(db, "018")
    saman = _seeded_bank_id(db, "056")
    acc = _create_acc(db, user["user_id"], bank_id=tejarat)
    assert acc.bank_name == "Tejarat"

    updated = update_bank_account(db, user["user_id"], acc.id, bank_id=saman)
    assert updated.bank_id == saman
    assert updated.bank_name == "Saman"


def test_update_nonexistent_bank_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    with pytest.raises(BankAccountServiceError, match="بانک یافت نشد"):
        update_bank_account(db, user["user_id"], acc.id, bank_id=999999)


def test_update_inactive_bank_rejected(db, make_user, inactive_bank):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    with pytest.raises(BankAccountServiceError, match="بانک غیرفعال"):
        update_bank_account(db, user["user_id"], acc.id, bank_id=inactive_bank.id)


def test_update_keep_inactive_bank_snapshot(db, make_user, inactive_bank):
    """Keeping the same inactive bank_id preserves the existing snapshot."""
    user = make_user(role="user", balance_al=None)
    bank = inactive_bank
    acc = _create_acc(
        db, user["user_id"],
        bank_id=_seeded_bank_id(db),
        account_number="1111111111",
    )
    db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id).update(
            {EmployeeBankAccount.bank_id: bank.id,
             EmployeeBankAccount.bank_name: "Inactive Test Bank"})
    db.commit()

    updated = update_bank_account(db, user["user_id"], acc.id, bank_id=bank.id)
    assert updated.bank_id == bank.id
    assert updated.bank_name == "Inactive Test Bank"


def test_update_nonexistent_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        update_bank_account(db, user["user_id"], 999999, branch_name="X")


def test_update_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        update_bank_account(db, user_a["user_id"], acc.id, branch_name="Hacked")


def test_update_nonexistent_user_raises(db):
    with pytest.raises(BankAccountServiceError, match="کاربر یافت نشد"):
        update_bank_account(db, "NONEXISTENT", 1, branch_name="X")


# ---------------------------------------------------------------------------
# Delete account
# ---------------------------------------------------------------------------

def test_delete_bank_account(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    delete_bank_account(db, user["user_id"], acc.id)
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id).first() is None


def test_delete_primary_no_auto_reassign(db, make_user):
    """Deleting the primary does not promote another account."""
    user = make_user(role="user", balance_al=None)
    primary = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    other = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=False)

    delete_bank_account(db, user["user_id"], primary.id)

    db.expire_all()
    remaining = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == other.id).one()
    assert remaining.is_primary is False


def test_delete_nonexistent_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        delete_bank_account(db, user["user_id"], 999999)


def test_delete_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        delete_bank_account(db, user_a["user_id"], acc.id)


# ---------------------------------------------------------------------------
# Set primary
# ---------------------------------------------------------------------------

def test_set_primary_bank_account(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], is_primary=False)
    result = set_primary_bank_account(db, user["user_id"], acc.id)
    assert result.is_primary is True


def test_set_primary_switches_between_accounts(db, make_user):
    user = make_user(role="user", balance_al=None)
    first = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    second = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=False)

    set_primary_bank_account(db, user["user_id"], second.id)

    db.expire_all()
    first_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == first.id).one()
    second_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == second.id).one()
    assert first_reloaded.is_primary is False
    assert second_reloaded.is_primary is True


def test_set_primary_exactly_one_per_user(db, make_user):
    user = make_user(role="user", balance_al=None)
    _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    second = _create_acc(db, user["user_id"], account_number="2222222222")
    third = _create_acc(db, user["user_id"], account_number="3333333333")

    set_primary_bank_account(db, user["user_id"], second.id)
    set_primary_bank_account(db, user["user_id"], third.id)

    count = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"],
        EmployeeBankAccount.is_primary == True,  # noqa: E712
    ).count()
    assert count == 1


def test_inactive_account_cannot_become_primary(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], is_active=False, is_primary=False)
    with pytest.raises(BankAccountServiceError, match="حساب غیرفعال نمی‌تواند اصلی باشد"):
        set_primary_bank_account(db, user["user_id"], acc.id)
    db.expire_all()
    kept = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id).one()
    assert kept.is_primary is False


def test_set_primary_nonexistent_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        set_primary_bank_account(db, user["user_id"], 999999)


def test_set_primary_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        set_primary_bank_account(db, user_a["user_id"], acc.id)


# ---------------------------------------------------------------------------
# Active / inactive
# ---------------------------------------------------------------------------

def test_deactivate_active_primary_allowed_no_reassign(db, make_user):
    """Deactivating the active Primary is allowed; is_primary preserved."""
    user = make_user(role="user", balance_al=None)
    primary = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    other = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=False)

    result = set_active_bank_account(db, user["user_id"], primary.id, active=False)

    db.expire_all()
    primary_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == primary.id).one()
    other_reloaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == other.id).one()
    assert result.is_active is False
    assert primary_reloaded.is_active is False
    assert primary_reloaded.is_primary is True
    assert other_reloaded.is_primary is False


def test_deactivate_primary_then_switch_then_reactivate_old(db, make_user):
    """A primary+active -> deactivate A -> promote B -> reactivate A.

    Reactivating A must not create two active primaries: step 3 demotes A,
    so A comes back as is_primary=false, is_active=true. The partial unique
    index (user_id WHERE is_primary AND is_active) is never violated.
    """
    user = make_user(role="user", balance_al=None)
    acc_a = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    acc_b = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=False)

    # 1) Deactivate the active primary (allowed; is_primary kept).
    set_active_bank_account(db, user["user_id"], acc_a.id, active=False)

    # 2) Promote B as the new active primary (demotes A in the same transaction).
    set_primary_bank_account(db, user["user_id"], acc_b.id)

    # 3) Reactivate A.
    result = set_active_bank_account(db, user["user_id"], acc_a.id, active=True)

    db.expire_all()
    a = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc_a.id).one()
    b = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc_b.id).one()
    assert result.is_active is True
    assert a.is_active is True
    assert a.is_primary is False
    assert b.is_primary is True
    assert b.is_active is True
    active_primaries = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"],
        EmployeeBankAccount.is_primary == True,   # noqa: E712
        EmployeeBankAccount.is_active == True,    # noqa: E712
    ).count()
    assert active_primaries == 1


def test_reactivate_restores_active_flag(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], is_active=True)
    set_active_bank_account(db, user["user_id"], acc.id, active=False)
    result = set_active_bank_account(db, user["user_id"], acc.id, active=True)
    assert result.is_active is True


def test_set_active_nonexistent_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        set_active_bank_account(db, user["user_id"], 999999, active=False)


def test_set_active_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        set_active_bank_account(db, user_a["user_id"], acc.id, active=False)


# ---------------------------------------------------------------------------
# Verification status
# ---------------------------------------------------------------------------

def test_verify_stamps_fields(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    result = change_verification_status(
        db, user["user_id"], acc.id, "verified",
        changed_by="ADMIN-1", note="ok",
    )
    assert result.verification_status == "verified"
    assert result.verified_by == "ADMIN-1"
    assert result.verified_at is not None
    assert result.verification_note == "ok"


def test_reject_stamps_fields(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    result = change_verification_status(
        db, user["user_id"], acc.id, "rejected",
        changed_by="ADMIN-1", note="mismatch",
    )
    assert result.verification_status == "rejected"
    assert result.verified_by == "ADMIN-1"
    assert result.verified_at is not None
    assert result.verification_note == "mismatch"


def test_unverified_clears_stamps(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    change_verification_status(
        db, user["user_id"], acc.id, "verified", changed_by="ADMIN-1"
    )
    result = change_verification_status(
        db, user["user_id"], acc.id, "unverified", note="reset"
    )
    assert result.verification_status == "unverified"
    assert result.verified_at is None
    assert result.verified_by is None
    assert result.verification_note == "reset"


def test_verification_invalid_status_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    with pytest.raises(BankAccountServiceError, match="وضعیت تأیید نامعتبر"):
        change_verification_status(
            db, user["user_id"], acc.id, "pending", changed_by="ADMIN-1"
        )


@pytest.mark.parametrize("status", ["verified", "rejected"])
def test_verification_requires_changed_by(db, make_user, status):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"])
    with pytest.raises(BankAccountServiceError, match="انجام‌دهنده تغییر"):
        change_verification_status(db, user["user_id"], acc.id, status)


def test_verification_nonexistent_account_raises(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        change_verification_status(
            db, user["user_id"], 999999, "verified", changed_by="ADMIN-1"
        )


def test_verification_cross_user_denied(db, make_user):
    user_a = make_user(role="user", balance_al=None)
    user_b = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user_b["user_id"])
    with pytest.raises(BankAccountServiceError, match="حساب بانکی یافت نشد"):
        change_verification_status(
            db, user_a["user_id"], acc.id, "verified", changed_by="ADMIN-1"
        )


# ---------------------------------------------------------------------------
# String / leading-zero preservation
# ---------------------------------------------------------------------------

def test_create_preserves_leading_zeros(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(
        db, user["user_id"],
        account_number="00123456789012",
        card_number="0000111122223333",
        sheba="IR000000000000000000000000",
    )
    db.expire_all()
    loaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id).one()
    assert loaded.account_number == "00123456789012"
    assert loaded.card_number == "0000111122223333"
    assert loaded.sheba == "IR000000000000000000000000"


def test_update_preserves_leading_zeros(db, make_user):
    user = make_user(role="user", balance_al=None)
    acc = _create_acc(db, user["user_id"], account_number="1111111111")
    updated = update_bank_account(
        db, user["user_id"], acc.id,
        account_number="00987654321",
        card_number="0000000000000001",
        sheba="IR000000000000000000000002",
    )
    assert updated.account_number == "00987654321"
    assert updated.card_number == "0000000000000001"
    assert updated.sheba == "IR000000000000000000000002"


# ---------------------------------------------------------------------------
# Multiple accounts lifecycle
# ---------------------------------------------------------------------------

def test_multiple_accounts_crud(db, make_user):
    user = make_user(role="user", balance_al=None)
    a1 = _create_acc(db, user["user_id"], account_number="1111111111", is_primary=True)
    a2 = _create_acc(db, user["user_id"], account_number="2222222222", is_primary=False)
    a3 = _create_acc(db, user["user_id"], account_number="3333333333", is_primary=False)

    assert len(list_bank_accounts(db, user["user_id"])) == 3

    update_bank_account(db, user["user_id"], a2.id, branch_name="Branch B")
    assert get_bank_account(db, user["user_id"], a2.id).branch_name == "Branch B"

    set_primary_bank_account(db, user["user_id"], a3.id)
    primaries = [
        a for a in list_bank_accounts(db, user["user_id"]) if a.is_primary
    ]
    assert len(primaries) == 1
    assert primaries[0].id == a3.id

    delete_bank_account(db, user["user_id"], a1.id)
    remaining = list_bank_accounts(db, user["user_id"])
    assert len(remaining) == 2
    assert all(a.id != a1.id for a in remaining)
