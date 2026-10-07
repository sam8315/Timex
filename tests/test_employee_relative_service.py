"""Service-layer tests for employee relatives."""
from datetime import date, timedelta

import pytest

from models.employee_relative import EmployeeRelative
from web.services.employee_relative_service import (
    EmployeeRelativeServiceError,
    create_relative,
    get_relative,
    is_valid_national_code,
    list_relatives,
    reject_relative,
    soft_delete_relative,
    update_relative,
    verify_relative,
)


def _valid_nc(seed: int = 123456789) -> str:
    base = f"{seed % 10**9:09d}"
    if len(set(base)) == 1:
        base = "001234567"
    checksum = sum(int(base[i]) * (10 - i) for i in range(9)) % 11
    check = checksum if checksum < 2 else 11 - checksum
    return base + str(check)


def test_is_valid_national_code_helper():
    assert is_valid_national_code(_valid_nc())
    assert not is_valid_national_code("0000000000")
    assert not is_valid_national_code("123")


def test_create_and_list(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="سارا",
        last_name="محمدی",
        relationship_type="CHILD",
        birth_date=date(2015, 5, 1),
        gender="F",
        created_by="admin1",
    )
    assert rel.id
    assert rel.relationship_type == "CHILD"
    rows = list_relatives(db, user["user_id"])
    assert len(rows) == 1
    assert rows[0].full_name == "سارا محمدی"


def test_multiple_children_and_relationship_types(db, make_user):
    user = make_user(role="user", balance_al=None)
    uid = user["user_id"]
    create_relative(db, user_id=uid, first_name="فرزند۱", last_name="الف", relationship_type="CHILD")
    create_relative(db, user_id=uid, first_name="فرزند۲", last_name="ب", relationship_type="CHILD")
    create_relative(db, user_id=uid, first_name="همسر", last_name="ج", relationship_type="SPOUSE")
    create_relative(db, user_id=uid, first_name="مادر", last_name="د", relationship_type="MOTHER")
    rows = list_relatives(db, uid)
    assert len(rows) == 4
    assert sum(1 for r in rows if r.relationship_type == "CHILD") == 2


def test_update_marital_and_dates(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="رضا",
        last_name="کریمی",
        relationship_type="SPOUSE",
        birth_date=date(1990, 1, 1),
    )
    updated = update_relative(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        marital_status="M",
        marriage_date=date(2015, 6, 1),
        employment_status="employed",
        insurance_status="insured",
        is_studying=False,
    )
    assert updated.marital_status == "M"
    assert updated.marriage_date == date(2015, 6, 1)
    assert updated.employment_status == "employed"
    assert updated.insurance_status == "insured"
    assert updated.is_studying is False


def test_soft_delete_hides_from_list(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="موقت",
        last_name="تست",
        relationship_type="OTHER",
    )
    soft_delete_relative(
        db, user["user_id"], rel.id, deleted_by="admin1"
    )
    assert list_relatives(db, user["user_id"]) == []
    deleted = get_relative(db, rel.id, include_deleted=True)
    assert deleted.deleted_at is not None
    assert deleted.deleted_by == "admin1"
    with pytest.raises(EmployeeRelativeServiceError):
        get_relative(db, rel.id)


def test_soft_delete_blocks_update(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="موقت",
        last_name="تست",
        relationship_type="OTHER",
    )
    soft_delete_relative(db, user["user_id"], rel.id, deleted_by="admin1")
    with pytest.raises(EmployeeRelativeServiceError):
        update_relative(
            db, user["user_id"], rel.id, first_name="تغییر"
        )


def test_national_code_validation(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(EmployeeRelativeServiceError, match="کد ملی"):
        create_relative(
            db,
            user_id=user["user_id"],
            first_name="الف",
            last_name="ب",
            relationship_type="CHILD",
            national_code="1234567890",
        )
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        national_code=_valid_nc(123456789),
    )
    assert rel.national_code == _valid_nc(123456789)


def test_duplicate_national_code_per_user_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    nc = _valid_nc(234567890)
    create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        national_code=nc,
    )
    with pytest.raises(EmployeeRelativeServiceError, match="کد ملی"):
        create_relative(
            db,
            user_id=user["user_id"],
            first_name="پ",
            last_name="ت",
            relationship_type="CHILD",
            national_code=nc,
        )


def test_same_national_code_allowed_for_different_users(db, make_user):
    u1 = make_user(role="user", balance_al=None)
    u2 = make_user(role="user", balance_al=None)
    nc = _valid_nc(345678901)
    create_relative(
        db, user_id=u1["user_id"], first_name="الف", last_name="ب",
        relationship_type="CHILD", national_code=nc,
    )
    rel2 = create_relative(
        db, user_id=u2["user_id"], first_name="پ", last_name="ت",
        relationship_type="CHILD", national_code=nc,
    )
    assert rel2.national_code == nc


def test_invalid_relationship_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(EmployeeRelativeServiceError, match="نسبت"):
        create_relative(
            db,
            user_id=user["user_id"],
            first_name="الف",
            last_name="ب",
            relationship_type="COUSIN",
        )


def test_future_birth_date_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(EmployeeRelativeServiceError, match="آینده"):
        create_relative(
            db,
            user_id=user["user_id"],
            first_name="الف",
            last_name="ب",
            relationship_type="CHILD",
            birth_date=date.today() + timedelta(days=3),
        )


def test_divorce_before_marriage_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    with pytest.raises(EmployeeRelativeServiceError, match="طلاق"):
        create_relative(
            db,
            user_id=user["user_id"],
            first_name="الف",
            last_name="ب",
            relationship_type="SPOUSE",
            marriage_date=date(2020, 1, 1),
            divorce_date=date(2019, 1, 1),
        )


def test_unknown_employment_normalized_to_null(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        employment_status="unknown",
        insurance_status="",
    )
    assert rel.employment_status is None
    assert rel.insurance_status is None


def test_disability_and_study_flags(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        is_studying=True,
        study_start_date=date(2020, 9, 1),
        is_disabled=True,
        disability_start_date=date(2021, 1, 1),
    )
    assert rel.is_studying is True
    assert rel.is_disabled is True
    row = db.query(EmployeeRelative).filter_by(id=rel.id).one()
    assert row.study_start_date == date(2020, 9, 1)


def test_create_defaults_to_pending(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
    )
    assert rel.status == "PENDING"


def test_admin_create_verified(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by="admin1",
    )
    assert rel.status == "VERIFIED"
    assert rel.verified_by == "admin1"
    assert rel.verified_at is not None


def test_user_update_resets_verification(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by="admin1",
    )
    updated = update_relative(
        db,
        user["user_id"],
        rel.id,
        first_name="جدید",
        reset_verification=True,
    )
    assert updated.first_name == "جدید"
    assert updated.status == "PENDING"
    assert updated.verified_by is None


def test_verify_and_reject(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
    )
    verified = verify_relative(
        db, user["user_id"], rel.id, verified_by="admin1"
    )
    assert verified.status == "VERIFIED"
    rejected = reject_relative(
        db, user["user_id"], rel.id, rejected_by="admin1", reason="ناقص"
    )
    assert rejected.status == "REJECTED"
    assert rejected.rejection_reason == "ناقص"


def test_soft_delete_verified_blocked_for_employee(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="الف",
        last_name="ب",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by="admin1",
    )
    with pytest.raises(EmployeeRelativeServiceError, match="تأییدشده"):
        soft_delete_relative(
            db, user["user_id"], rel.id, deleted_by=user["user_id"],
            allow_verified=False,
        )
    soft_delete_relative(
        db, user["user_id"], rel.id, deleted_by="admin1", allow_verified=True
    )
    assert list_relatives(db, user["user_id"]) == []
