"""Model/DB foundation tests for employee_relatives."""
from datetime import date

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError

from models import Base
from models.employee_relative import EmployeeRelative
from models.user import User
from tests.conftest import test_engine


def _make_relative(user_id, **overrides):
    defaults = dict(
        user_id=user_id,
        first_name="علی",
        last_name="رضایی",
        relationship_type="CHILD",
    )
    defaults.update(overrides)
    return EmployeeRelative(**defaults)


def test_table_registered_in_metadata():
    assert "employee_relatives" in Base.metadata.tables


def test_table_created_in_test_db():
    inspector = sa_inspect(test_engine)
    assert "employee_relatives" in inspector.get_table_names()


def test_required_columns_exist(db):
    columns = {
        c["name"] for c in sa_inspect(db.bind).get_columns("employee_relatives")
    }
    required = {
        "id", "user_id", "first_name", "last_name", "father_name",
        "national_code", "birth_date", "gender", "relationship_type",
        "marital_status", "marriage_date", "divorce_date", "death_date",
        "is_studying", "study_start_date", "study_end_date",
        "employment_status", "insurance_status",
        "is_disabled", "disability_start_date", "disability_end_date",
        "notes", "status", "submitted_by", "verified_by", "verified_at",
        "rejection_reason", "deleted_at", "deleted_by",
        "created_at", "updated_at",
    }
    assert required.issubset(columns)


def test_fk_user_id_cascade(db, make_user):
    user = make_user(role="user", balance_al=None)
    uid = user["user_id"]
    db.add(_make_relative(uid, first_name="فرزند"))
    db.commit()
    assert db.query(EmployeeRelative).filter_by(user_id=uid).count() == 1

    db.query(User).filter(User.user_id == uid).delete(synchronize_session=False)
    db.commit()
    assert db.query(EmployeeRelative).filter_by(user_id=uid).count() == 0


def test_multiple_relatives_per_user(db, make_user):
    user = make_user(role="user", balance_al=None)
    uid = user["user_id"]
    db.add(_make_relative(uid, first_name="فرزند۱", relationship_type="CHILD"))
    db.add(_make_relative(uid, first_name="همسر", relationship_type="SPOUSE"))
    db.add(_make_relative(uid, first_name="پدر", relationship_type="FATHER"))
    db.commit()
    rows = db.query(EmployeeRelative).filter_by(user_id=uid).all()
    assert len(rows) == 3
    types = {r.relationship_type for r in rows}
    assert types == {"CHILD", "SPOUSE", "FATHER"}


def test_invalid_relationship_type_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    db.add(_make_relative(user["user_id"], relationship_type="COUSIN"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_death_before_birth_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    db.add(_make_relative(
        user["user_id"],
        birth_date=date(2010, 1, 1),
        death_date=date(2009, 1, 1),
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_display_helpers():
    rel = _make_relative("U1", gender="M", marital_status="S", relationship_type="CHILD")
    assert rel.full_name == "علی رضایی"
    assert rel.relationship_type_name == "فرزند"
    assert rel.gender_name == "مرد"
    assert rel.marital_status_name == "مجرد"
    assert rel.is_deleted is False
