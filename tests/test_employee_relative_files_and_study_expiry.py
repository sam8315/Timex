"""Tests for study expiry and relative file attachments."""
from datetime import date, timedelta
from io import BytesIO
from urllib.parse import unquote

import pytest

from web.services.employee_relative_file_service import (
    add_file,
    list_files,
    soft_delete_file,
)
from web.services.employee_relative_service import (
    create_relative,
    expire_ended_studies,
    verify_relative,
)
from .conftest import login_as


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "timex_storage"
    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(root))
    yield root


def test_future_study_end_date_allowed(db, make_user):
    user = make_user(role="user", balance_al=None)
    future = date.today() + timedelta(days=90)
    rel = create_relative(
        db,
        user_id=user["user_id"],
        first_name="سارا",
        last_name="محصل",
        relationship_type="CHILD",
        is_studying=True,
        study_start_date=date.today() - timedelta(days=30),
        study_end_date=future,
        status="VERIFIED",
    )
    assert rel.study_end_date == future
    assert rel.is_studying is True


def test_expire_ended_studies_clears_flag_keeps_status(db, make_user):
    user = make_user(role="user", balance_al=None)
    past = create_relative(
        db,
        user_id=user["user_id"],
        first_name="گذشته",
        last_name="تحصیل",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() - timedelta(days=1),
        status="VERIFIED",
        created_by="admin1",
    )
    future = create_relative(
        db,
        user_id=user["user_id"],
        first_name="آینده",
        last_name="تحصیل",
        relationship_type="CHILD",
        is_studying=True,
        study_end_date=date.today() + timedelta(days=10),
        status="VERIFIED",
        created_by="admin1",
    )

    updated = expire_ended_studies(db, as_of=date.today())
    assert updated == 1
    db.refresh(past)
    db.refresh(future)
    assert past.is_studying is False
    assert past.status == "VERIFIED"
    assert past.deleted_at is None
    assert future.is_studying is True


def test_add_multiple_files_and_download(client, db, make_user, _isolated_storage):
    owner = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=owner["user_id"],
        first_name="فرزند",
        last_name="فایل",
        relationship_type="CHILD",
        status="PENDING",
    )
    f1 = add_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\none",
        original_filename="a.pdf",
        uploaded_by=owner["user_id"],
    )
    f2 = add_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\ntwo",
        original_filename="b.pdf",
        uploaded_by=owner["user_id"],
    )
    assert len(list_files(db, rel.id)) == 2
    assert f1.storage_key.startswith("/private/employee-relatives/")
    assert (_isolated_storage / "employee-relatives").exists()

    login_as(client, owner["national_code"])
    resp = client.get(f"/employee-relatives/files/{f2.id}/file", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_other_employee_cannot_download_file(client, db, make_user):
    owner = make_user(role="user", balance_al=None)
    other = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=owner["user_id"],
        first_name="محرمانه",
        last_name="فایل",
        relationship_type="CHILD",
    )
    row = add_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\nsecret",
        original_filename="secret.pdf",
        uploaded_by=owner["user_id"],
    )
    login_as(client, other["national_code"])
    resp = client.get(f"/employee-relatives/files/{row.id}/file", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]


def test_employee_file_upload_resets_verified_to_pending(client, db, make_user):
    owner = make_user(role="user", balance_al=None)
    admin = make_user(role="super_admin")
    rel = create_relative(
        db,
        user_id=owner["user_id"],
        first_name="تأیید",
        last_name="شده",
        relationship_type="CHILD",
        status="PENDING",
    )
    verify_relative(
        db, user_id=owner["user_id"], relative_id=rel.id, verified_by=admin["user_id"]
    )
    db.refresh(rel)
    assert rel.status == "VERIFIED"

    login_as(client, owner["national_code"])
    resp = client.post(
        f"/profile/relatives/{rel.id}/files/add",
        files={"file": ("id.pdf", BytesIO(b"%PDF-1.4\nx"), "application/pdf")},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = unquote(resp.headers["location"])
    assert "success=" in loc
    db.refresh(rel)
    assert rel.status == "PENDING"
    assert len(list_files(db, rel.id)) == 1


def test_employee_file_delete_resets_verified_to_pending(db, make_user):
    owner = make_user(role="user", balance_al=None)
    admin = make_user(role="super_admin")
    rel = create_relative(
        db,
        user_id=owner["user_id"],
        first_name="حذف",
        last_name="فایل",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by=admin["user_id"],
    )
    row = add_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\nz",
        original_filename="z.pdf",
        uploaded_by=admin["user_id"],
        reset_verification=False,
    )
    db.refresh(rel)
    assert rel.status == "VERIFIED"

    soft_delete_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_id=row.id,
        deleted_by=owner["user_id"],
        reset_verification=True,
    )
    db.refresh(rel)
    assert rel.status == "PENDING"
    assert list_files(db, rel.id) == []


def test_admin_file_upload_keeps_verified_status(client, db, make_user):
    admin = make_user(role="super_admin")
    target = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=target["user_id"],
        first_name="ادمین",
        last_name="فایل",
        relationship_type="CHILD",
        status="VERIFIED",
        created_by=admin["user_id"],
    )
    login_as(client, admin["national_code"])
    resp = client.post(
        f"/admin/profile/{target['user_id']}/relatives/{rel.id}/files/add",
        files={"file": ("admin.pdf", BytesIO(b"%PDF-1.4\nadmin"), "application/pdf")},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.refresh(rel)
    assert rel.status == "VERIFIED"
    assert len(list_files(db, rel.id)) == 1


def test_profile_renders_files_modal(client, db, make_user):
    owner = make_user(role="user", balance_al=None)
    rel = create_relative(
        db,
        user_id=owner["user_id"],
        first_name="نمایش",
        last_name="فایل",
        relationship_type="CHILD",
    )
    add_file(
        db,
        user_id=owner["user_id"],
        relative_id=rel.id,
        file_bytes=b"%PDF-1.4\nui",
        original_filename="ui.pdf",
        uploaded_by=owner["user_id"],
    )
    login_as(client, owner["national_code"])
    page = client.get("/profile", headers={"Accept": "text/html"})
    assert page.status_code == 200
    assert f"relativeFilesModal-{rel.id}" in page.text
    assert "ui.pdf" in page.text
