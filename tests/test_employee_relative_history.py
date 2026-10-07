"""Tests for employee relative audit history."""
from datetime import date, timedelta

import pytest

from models.employee_relative_history import EmployeeRelativeHistory
from web.services.employee_relative_file_service import add_file, soft_delete_file
from web.services.employee_relative_service import (
    create_relative,
    expire_ended_studies,
    reject_relative,
    soft_delete_relative,
    update_relative,
    verify_relative,
)
from .conftest import login_as


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "timex_storage"
    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(root))
    yield root


def _hist(db, user_id: str):
    return (
        db.query(EmployeeRelativeHistory)
        .filter(EmployeeRelativeHistory.user_id == user_id)
        .order_by(EmployeeRelativeHistory.id.asc())
        .all()
    )


def test_create_logs_history(db, make_user):
    user = make_user(role="user", balance_al=None)
    create_relative(
        db,
        user_id=user["user_id"],
        first_name="سارا",
        last_name="احمدی",
        relationship_type="CHILD",
        created_by=user["user_id"],
    )
    rows = _hist(db, user["user_id"])
    assert len(rows) == 1
    assert rows[0].action == "CREATE"
    assert rows[0].first_name == "سارا"
    assert rows[0].changed_by_user_id == user["user_id"]


def test_update_logs_only_when_changed(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="قدیم",
        last_name="نام",
        relationship_type="CHILD",
        created_by=user["user_id"],
    )
    before = len(_hist(db, user["user_id"]))

    update_relative(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        first_name="قدیم",
        last_name="نام",
        relationship_type="CHILD",
        changed_by=user["user_id"],
    )
    assert len(_hist(db, user["user_id"])) == before

    update_relative(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        first_name="جدید",
        changed_by=user["user_id"],
    )
    rows = _hist(db, user["user_id"])
    assert len(rows) == before + 1
    assert rows[-1].action == "UPDATE"
    assert rows[-1].first_name == "قدیم"  # snapshot before change


def test_verify_reject_delete_and_study_expire(db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="فرزند",
        last_name="تست",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() - timedelta(days=1),
        created_by=user["user_id"],
    )
    verify_relative(
        db, user_id=user["user_id"], relative_id=rel.id, verified_by=admin["user_id"]
    )
    reject_relative(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        rejected_by=admin["user_id"],
        reason="ناقص",
    )
    # recreate studying for expire
    rel2 = create_relative(
        db,
        user_id=user["user_id"],
        first_name="محصل",
        last_name="منقضی",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() - timedelta(days=2),
        created_by=admin["user_id"],
        status="VERIFIED",
    )
    expire_ended_studies(db, as_of=date.today())
    soft_delete_relative(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        deleted_by=admin["user_id"],
        allow_verified=True,
    )

    actions = {r.action for r in _hist(db, user["user_id"])}
    assert "VERIFY" in actions
    assert "REJECT" in actions
    assert "STUDY_EXPIRE" in actions
    assert "DELETE" in actions
    expire_rows = [
        r for r in _hist(db, user["user_id"]) if r.action == "STUDY_EXPIRE"
    ]
    assert expire_rows
    assert expire_rows[0].changed_by_user_id is None
    assert expire_rows[0].is_studying is True  # snapshot before flip
    db.refresh(rel2)
    assert rel2.is_studying is False


def test_file_add_delete_history(db, make_user):
    user = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="فایل",
        last_name="تست",
        relationship_type="CHILD",
        created_by=user["user_id"],
    )
    row = add_file(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\nhist",
        original_filename="hist.pdf",
        uploaded_by=user["user_id"],
    )
    soft_delete_file(
        db,
        user_id=user["user_id"],
        relative_id=rel.id,
        file_id=row.id,
        deleted_by=user["user_id"],
        reset_verification=True,
    )
    actions = [r.action for r in _hist(db, user["user_id"])]
    assert "FILE_ADD" in actions
    assert "FILE_DELETE" in actions
    add_row = next(r for r in _hist(db, user["user_id"]) if r.action == "FILE_ADD")
    assert "hist.pdf" in (add_row.detail or "")


def test_admin_profile_renders_relative_history(client, db, make_user):
    admin = make_user(role="super_admin")
    target = make_user(role="user", balance_al=None)
    create_relative(
        db,
        user_id=target["user_id"],
        first_name="نمایش",
        last_name="سابقه",
        relationship_type="CHILD",
        created_by=admin["user_id"],
        status="VERIFIED",
    )
    login_as(client, admin["national_code"])
    resp = client.get(
        f"/admin/profile/{target['user_id']}",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "سابقه تغییرات بستگان" in resp.text
    assert "ایجاد" in resp.text
    assert "نمایش سابقه" in resp.text
