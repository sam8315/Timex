"""
Focused tests for the Employee Bank Account model foundation (Phase 1).

Validates:
- model import / metadata / table registration (banks + employee_bank_accounts)
- table creation in the test database
- FK employee_bank_accounts.user_id -> users.user_id (CASCADE)
- multiple accounts per User
- active-primary uniqueness (partial unique index)
- verification_status CHECK constraint
- string storage for account_number / card_number / sheba
- bank reference seed (canonical active Iranian banks, Phase 12)
"""
import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from database.init_db import seed_banks
from models import Base
from models.bank import Bank
from models.employee_bank_account import EmployeeBankAccount
from tests.conftest import test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seeded_bank_id(db) -> int:
    seed_banks(bind_engine=test_engine)
    return db.query(Bank).filter(Bank.code == "018").one().id


def _make_account(
    user_id,
    bank_id,
    account_number="123456789012345678901234",
    is_primary=False,
    is_active=True,
    verification_status="unverified",
    card_number=None,
    sheba=None,
):
    return EmployeeBankAccount(
        user_id=user_id,
        bank_id=bank_id,
        bank_name="Tejarat",
        account_number=account_number,
        card_number=card_number,
        sheba=sheba,
        is_primary=is_primary,
        is_active=is_active,
        verification_status=verification_status,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_tables_registered_in_metadata():
    assert "banks" in Base.metadata.tables
    assert "employee_bank_accounts" in Base.metadata.tables


def test_tables_created_in_test_db():
    inspector = sa_inspect(test_engine)
    tables = inspector.get_table_names()
    assert "banks" in tables
    assert "employee_bank_accounts" in tables


def test_required_account_columns_exist(db):
    columns = {
        c["name"]
        for c in sa_inspect(db.bind).get_columns("employee_bank_accounts")
    }
    required = {
        "id", "user_id", "bank_id", "bank_name", "branch_name", "branch_code",
        "account_number", "card_number", "sheba", "account_type",
        "account_title", "is_primary", "is_active", "verification_status",
        "verified_at", "verified_by", "verification_note", "description",
        "created_at", "updated_at",
    }
    assert required.issubset(columns)


def test_required_bank_columns_exist(db):
    columns = {c["name"] for c in sa_inspect(db.bind).get_columns("banks")}
    required = {
        "id", "code", "name", "country_code", "is_active", "sort_order",
        "created_at", "updated_at",
    }
    assert required.issubset(columns)


# ---------------------------------------------------------------------------
# FK relationship
# ---------------------------------------------------------------------------

def test_fk_relationship_to_user(db, make_user):
    """employee_bank_accounts links to users.user_id with CASCADE delete."""
    user = make_user(role="user", balance_al=None)
    acc = _make_account(user["user_id"], _seeded_bank_id(db), is_primary=True)
    db.add(acc)
    db.commit()

    assert acc.id is not None
    assert acc.user_id == user["user_id"]

    fks = sa_inspect(db.bind).get_foreign_keys("employee_bank_accounts")
    assert any(
        f["referred_table"] == "users"
        and f["referred_columns"] == ["user_id"]
        and "user_id" in f["constrained_columns"]
        for f in fks
    )


def test_fk_relationship_to_bank(db, make_user):
    """employee_bank_accounts.bank_id references banks.id."""
    user = make_user(role="user", balance_al=None)
    acc = _make_account(user["user_id"], _seeded_bank_id(db))
    db.add(acc)
    db.commit()

    fks = sa_inspect(db.bind).get_foreign_keys("employee_bank_accounts")
    assert any(
        f["referred_table"] == "banks"
        and f["referred_columns"] == ["id"]
        and "bank_id" in f["constrained_columns"]
        for f in fks
    )


def test_cascade_delete_on_user_removal(db, make_user):
    """Deleting a user should cascade-delete their bank accounts."""
    from models.user import User

    user = make_user(role="user", balance_al=None)
    acc = _make_account(user["user_id"], _seeded_bank_id(db), is_primary=True)
    db.add(acc)
    db.commit()
    acc_id = acc.id

    db.query(User).filter(User.user_id == user["user_id"]).delete(
        synchronize_session=False
    )
    db.commit()

    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc_id
    ).first() is None


# ---------------------------------------------------------------------------
# Multiple accounts / active-primary uniqueness
# ---------------------------------------------------------------------------

def test_multiple_accounts_per_user(db, make_user):
    """One user can have multiple bank accounts."""
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    db.add_all([
        _make_account(user["user_id"], bank_id, account_number="1111111111111111",
                      is_primary=True),
        _make_account(user["user_id"], bank_id, account_number="2222222222222222",
                      is_primary=False),
    ])
    db.commit()

    count = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"]
    ).count()
    assert count == 2


def test_single_active_primary_per_user(db, make_user):
    """Only one active primary account (is_primary AND is_active) per user."""
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    db.add(_make_account(user["user_id"], bank_id,
                         account_number="1111111111111111", is_primary=True))
    db.commit()

    db.add(_make_account(user["user_id"], bank_id,
                         account_number="2222222222222222", is_primary=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_multiple_non_primary_allowed(db, make_user):
    """Multiple non-primary accounts per user are allowed."""
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    db.add_all([
        _make_account(user["user_id"], bank_id, account_number="1111111111111111"),
        _make_account(user["user_id"], bank_id, account_number="2222222222222222"),
    ])
    db.commit()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"]
    ).count() == 2


def test_inactive_primary_does_not_block_second_active_primary(db, make_user):
    """Partial index only covers is_primary AND is_active rows."""
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    db.add(_make_account(user["user_id"], bank_id,
                         account_number="1111111111111111",
                         is_primary=True, is_active=False))
    db.add(_make_account(user["user_id"], bank_id,
                         account_number="2222222222222222",
                         is_primary=True, is_active=True))
    db.commit()

    active_primaries = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"],
        EmployeeBankAccount.is_primary == True,  # noqa: E712
        EmployeeBankAccount.is_active == True,   # noqa: E712
    ).count()
    assert active_primaries == 1


# ---------------------------------------------------------------------------
# verification_status constraint
# ---------------------------------------------------------------------------

def test_invalid_verification_status_rejected(db, make_user):
    """An unknown verification_status is rejected by the CHECK constraint."""
    user = make_user(role="user", balance_al=None)
    acc = _make_account(user["user_id"], _seeded_bank_id(db))
    acc.verification_status = "INVALID"
    db.add(acc)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_all_valid_verification_statuses_accepted(db, make_user):
    """unverified / verified / rejected are all accepted."""
    user = make_user(role="user", balance_al=None)
    bank_id = _seeded_bank_id(db)
    statuses = ["unverified", "verified", "rejected"]
    for i, status in enumerate(statuses):
        db.add(_make_account(
            user["user_id"], bank_id,
            account_number=f"{3000000000000000 + i}",
            verification_status=status,
            is_primary=False,
        ))
    db.commit()
    assert db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.user_id == user["user_id"]
    ).count() == len(statuses)


# ---------------------------------------------------------------------------
# String storage for sensitive identifiers
# ---------------------------------------------------------------------------

def test_sensitive_fields_stored_as_strings(db):
    """account_number, card_number and sheba are VARCHAR columns."""
    cols = {
        c["name"]: c
        for c in sa_inspect(db.bind).get_columns("employee_bank_accounts")
    }
    for name in ("account_number", "card_number", "sheba"):
        assert "VARCHAR" in str(cols[name]["type"]).upper(), (
            f"{name} must be a string column, got {cols[name]['type']}"
        )


def test_leading_zero_account_number_roundtrip(db, make_user):
    """A numeric-looking string keeps its leading zero (not an integer)."""
    user = make_user(role="user", balance_al=None)
    acc = _make_account(
        user["user_id"], _seeded_bank_id(db),
        account_number="00123456789012",
        card_number="0000111122223333",
        sheba="IR000000000000000000000000",
    )
    db.add(acc)
    db.commit()
    db.expire_all()
    loaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc.id
    ).one()
    assert loaded.account_number == "00123456789012"
    assert loaded.card_number == "0000111122223333"
    assert loaded.sheba == "IR000000000000000000000000"


# ---------------------------------------------------------------------------
# Bank reference seed (Phase 12 — canonical active Iranian banks)
# ---------------------------------------------------------------------------

EXCLUDED_OBSOLETE_BANK_NAMES = (
    "بانک آینده",
    "بانک انصار",
    "بانک قوامین",
    "بانک حکمت ایرانیان",
    "بانک مهر اقتصاد",
    "مؤسسه اعتباری کوثر",
    "مؤسسه اعتباری توسعه",
    "مؤسسه اعتباری نور",
    "مؤسسه اعتباری ملل",
    "بانک مرکزی جمهوری اسلامی ایران",
)


def test_bank_seed_canonical_active_set(db):
    """All 27 canonical banks exist, active, IR, Persian names, ordered codes."""
    from database.init_db import CANONICAL_BANKS

    seed_banks(bind_engine=test_engine)
    seed_banks(bind_engine=test_engine)

    rows = db.query(Bank).order_by(Bank.sort_order).all()
    active = [b for b in rows if b.is_active]
    mapping = {b.code: b.name for b in active}

    assert len(CANONICAL_BANKS) == 27
    assert mapping == dict(CANONICAL_BANKS)
    assert all(b.country_code == "IR" for b in active)
    assert all(b.is_active for b in active)
    assert all(isinstance(b.code, str) and len(b.code) == 3 for b in active)
    assert [b.code for b in active] == [c for c, _ in CANONICAL_BANKS]
    assert [b.sort_order for b in active] == list(range(1, 28))
    # Exact Persian names — no English short names in the active set.
    assert "بانک تجارت" in mapping.values()
    assert "بانک سامان" in mapping.values()
    assert "بانک ملت" in mapping.values()
    assert not any(n in mapping.values() for n in ("Tejarat", "Saman", "Mellat"))


def test_bank_seed_idempotent_no_duplicates(db):
    """Running the startup seed twice produces no duplicate rows."""
    seed_banks(bind_engine=test_engine)
    seed_banks(bind_engine=test_engine)

    rows = db.query(Bank).all()
    codes = [b.code for b in rows]
    assert len(codes) == len(set(codes))
    active = [b for b in rows if b.is_active]
    assert len(active) == 27


def test_bank_seed_corrects_english_names_to_persian(db):
    """Existing canonical rows with old English names are corrected."""
    seed_banks(bind_engine=test_engine)
    bank = db.query(Bank).filter(Bank.code == "018").one()
    bank.name = "Tejarat"
    bank.country_code = "US"
    bank.is_active = False
    bank.sort_order = 1
    db.commit()
    bank_id = bank.id

    seed_banks(bind_engine=test_engine)
    db.expire_all()

    fixed = db.query(Bank).filter(Bank.id == bank_id).one()
    assert fixed.name == "بانک تجارت"
    assert fixed.country_code == "IR"
    assert fixed.is_active is True
    assert fixed.sort_order == 8  # position of 018 in canonical list


def test_bank_seed_deactivates_non_canonical_without_delete(db):
    """Non-canonical bank codes are deactivated, never deleted (FK safety)."""
    obsolete = db.query(Bank).filter(Bank.code == "062").first()
    if obsolete is None:
        obsolete = Bank(
            code="062", name="بانک آینده", country_code="IR",
            is_active=True, sort_order=900,
        )
        db.add(obsolete)
    else:
        obsolete.name = "بانک آینده"
        obsolete.is_active = True
        obsolete.sort_order = 900
    db.commit()
    obsolete_id = obsolete.id

    seed_banks(bind_engine=test_engine)
    db.expire_all()

    row = db.query(Bank).filter(Bank.id == obsolete_id).first()
    assert row is not None  # not deleted — FK may reference it
    assert row.is_active is False
    assert row.name == "بانک آینده"  # name not rewritten for non-canonical


def test_bank_seed_excludes_obsolete_from_active_set(db):
    """Merged/revoked/central/foreign banks never appear as active."""
    seed_banks(bind_engine=test_engine)

    active_names = {
        b.name for b in db.query(Bank).filter(Bank.is_active == True)  # noqa: E712
    }
    active_codes = {
        b.code for b in db.query(Bank).filter(Bank.is_active == True)  # noqa: E712
    }

    for name in EXCLUDED_OBSOLETE_BANK_NAMES:
        assert name not in active_names
    # Known obsolete/merged Sheba codes must not be in the active set.
    for code in ("010", "051", "062", "063", "065"):
        assert code not in active_codes


def test_bank_seed_leaves_employee_accounts_untouched(db, make_user):
    """Seed only touches banks; employee_bank_accounts rows are unchanged."""
    user = make_user(role="user", balance_al=None)
    seed_banks(bind_engine=test_engine)
    bank_id = db.query(Bank).filter(Bank.code == "018").one().id

    acc = _make_account(user["user_id"], bank_id)
    acc.bank_name = "Legacy Snapshot"
    db.add(acc)
    db.commit()
    acc_id = acc.id

    seed_banks(bind_engine=test_engine)
    db.expire_all()

    loaded = db.query(EmployeeBankAccount).filter(
        EmployeeBankAccount.id == acc_id
    ).one()
    assert loaded.bank_id == bank_id
    assert loaded.bank_name == "Legacy Snapshot"
    assert loaded.account_number == "123456789012345678901234"
