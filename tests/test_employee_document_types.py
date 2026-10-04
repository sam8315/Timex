"""Tests for EmployeeDocumentType CRUD, seed/migration, and permissions."""
import pytest
from sqlalchemy import inspect, text

from database.init_db import (
    migrate_employee_document_types,
    seed_employee_document_types,
)
from models.employee_document import LEGACY_DOCUMENT_TYPE_SEED, EmployeeDocument
from models.employee_document_type import EmployeeDocumentType
from web.permissions import ALL_PERMISSIONS
from web.services.employee_document_service import (
    create_document,
    list_active_document_types,
)
from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


def _cleanup_types(db, *codes):
    for code in codes:
        row = (
            db.query(EmployeeDocumentType)
            .filter(EmployeeDocumentType.code == code)
            .first()
        )
        if not row:
            continue
        db.query(EmployeeDocument).filter(
            EmployeeDocument.document_type_id == row.id
        ).delete()
        db.delete(row)
        db.commit()


def _type_by_code(db, code: str) -> EmployeeDocumentType:
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.code == code)
        .first()
    )
    assert row is not None
    return row


def test_permission_in_catalog():
    assert "manage_employee_document_types" in ALL_PERMISSIONS
    info = ALL_PERMISSIONS["manage_employee_document_types"]
    assert info["admin"] is True
    assert info["super_admin"] is True


def test_seed_legacy_types_idempotent(db):
    before = db.query(EmployeeDocumentType).count()
    seed_employee_document_types(bind_engine=db.get_bind())
    seed_employee_document_types(bind_engine=db.get_bind())
    codes = {
        r.code for r in db.query(EmployeeDocumentType).all()
    }
    for code, _name in LEGACY_DOCUMENT_TYPE_SEED:
        assert code in codes
    assert db.query(EmployeeDocumentType).count() >= before
    assert db.query(EmployeeDocumentType).count() >= len(LEGACY_DOCUMENT_TYPE_SEED)


def test_seed_preserves_admin_rename(db):
    row = _type_by_code(db, "INSURANCE")
    original = row.name
    row.name = "بیمه سفارشی ادمین"
    db.commit()
    try:
        seed_employee_document_types(bind_engine=db.get_bind())
        db.refresh(row)
        assert row.name == "بیمه سفارشی ادمین"
    finally:
        row.name = original
        db.commit()


def test_migrate_idempotent(db):
    migrate_employee_document_types(bind_engine=db.get_bind())
    migrate_employee_document_types(bind_engine=db.get_bind())
    insp = inspect(db.get_bind())
    cols = {c["name"] for c in insp.get_columns("employee_documents")}
    assert "document_type_id" in cols
    assert "document_type" not in cols
    assert "employee_document_types" in insp.get_table_names()


def test_create_edit_toggle_delete(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    _cleanup_types(db, "CUSTOM_LICENSE", "CUSTOM_LICENSE")

    resp = client.post(
        "/admin/employee-document-types/add",
        data={
            "code": "custom_license",
            "name": "مجوز سفارشی",
            "sort_order": "10",
            "is_active": "on",
        },
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 302
    assert "success" in (resp.headers.get("location") or "")
    row = _type_by_code(db, "CUSTOM_LICENSE")
    assert row.name == "مجوز سفارشی"
    assert row.is_active is True

    # duplicate code rejected
    dup = client.post(
        "/admin/employee-document-types/add",
        data={
            "code": "CUSTOM_LICENSE",
            "name": "تکراری",
            "sort_order": "1",
            "is_active": "on",
        },
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert dup.status_code == 302
    assert "error" in (dup.headers.get("location") or "")

    edit = client.post(
        f"/admin/employee-document-types/{row.id}/edit",
        data={"name": "مجوز ویرایش‌شده", "sort_order": "3", "is_active": "on"},
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert edit.status_code == 302
    db.refresh(row)
    assert row.name == "مجوز ویرایش‌شده"
    assert row.code == "CUSTOM_LICENSE"
    assert row.sort_order == 3

    toggle = client.post(
        f"/admin/employee-document-types/{row.id}/toggle",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert toggle.status_code == 302
    db.refresh(row)
    assert row.is_active is False

    # reactivate then delete unused
    row.is_active = True
    db.commit()
    delete = client.post(
        f"/admin/employee-document-types/{row.id}/delete",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert delete.status_code == 302
    assert "success" in (delete.headers.get("location") or "")
    assert (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.code == "CUSTOM_LICENSE")
        .first()
        is None
    )


def test_delete_rejected_when_in_use(client, db, make_user):
    admin = make_user(role="admin")
    user = make_user(role="user")
    login_as(client, admin["national_code"])
    _cleanup_types(db, "USED_TYPE")

    add = client.post(
        "/admin/employee-document-types/add",
        data={
            "code": "USED_TYPE",
            "name": "نوع استفاده‌شده",
            "sort_order": "1",
            "is_active": "on",
        },
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert add.status_code == 302
    row = _type_by_code(db, "USED_TYPE")

    create_document(
        db,
        user_id=user["user_id"],
        uploaded_by=user["user_id"],
        document_type_id=row.id,
        title="مدرک وابسته",
        file_bytes=b"%PDF-1.4\nx",
        original_filename="x.pdf",
    )

    delete = client.post(
        f"/admin/employee-document-types/{row.id}/delete",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert delete.status_code == 302
    assert "error" in (delete.headers.get("location") or "")
    assert (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.id == row.id)
        .first()
        is not None
    )

    # cleanup documents then type
    db.query(EmployeeDocument).filter(
        EmployeeDocument.document_type_id == row.id
    ).delete()
    db.commit()
    _cleanup_types(db, "USED_TYPE")


def test_unauthorized_user_denied(client, db, make_user):
    user = make_user(role="user")
    login_as(client, user["national_code"])
    resp = client.get(
        "/admin/employee-document-types?show_all=1",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code in (302, 303, 403)


def test_admin_can_list(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    resp = client.get(
        "/admin/employee-document-types?show_all=1",
        follow_redirects=False,
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 200
    assert "NATIONAL_ID".encode("utf-8") in resp.content
    assert "کارت ملی".encode("utf-8") in resp.content


def test_inactive_excluded_from_active_list(db):
    row = _type_by_code(db, "OTHER")
    original = row.is_active
    row.is_active = False
    db.commit()
    try:
        active_ids = {t.id for t in list_active_document_types(db)}
        assert row.id not in active_ids
    finally:
        row.is_active = original
        db.commit()


def test_migrate_unmapped_legacy_fails_safely(db, make_user):
    """If legacy document_type values cannot be mapped, migration must abort."""
    user = make_user(role="user")
    bind = db.get_bind()
    migrate_employee_document_types(bind_engine=bind)
    added_legacy = False

    try:
        with bind.connect() as conn:
            cols = {
                c["name"] for c in inspect(bind).get_columns("employee_documents")
            }
            added_legacy = "document_type" not in cols
            if added_legacy:
                conn.execute(
                    text(
                        'ALTER TABLE "employee_documents" '
                        'ADD COLUMN "document_type" VARCHAR(40) NULL'
                    )
                )
                conn.commit()

            conn.execute(
                text(
                    'ALTER TABLE "employee_documents" '
                    'ALTER COLUMN "document_type_id" DROP NOT NULL'
                )
            )
            conn.commit()
            conn.execute(
                text(
                    """
                    INSERT INTO employee_documents (
                        user_id, document_type_id, document_type, title,
                        original_filename, storage_key, mime_type, size_bytes,
                        status, uploaded_by, uploaded_at
                    ) VALUES (
                        :uid, NULL, 'NOT_A_REAL_TYPE', 'probe',
                        'p.pdf', '/private/employee-documents/p.pdf',
                        'application/pdf', 1, 'PENDING', :uid, NOW()
                    )
                    """
                ),
                {"uid": user["user_id"]},
            )
            conn.commit()

        with pytest.raises(RuntimeError) as exc:
            migrate_employee_document_types(bind_engine=bind)
        assert "unmapped" in str(exc.value).lower()
    finally:
        with bind.connect() as conn:
            conn.execute(
                text(
                    "DELETE FROM employee_documents WHERE user_id = :uid"
                ),
                {"uid": user["user_id"]},
            )
            conn.commit()
            if added_legacy or "document_type" in {
                c["name"] for c in inspect(bind).get_columns("employee_documents")
            }:
                conn.execute(
                    text(
                        'ALTER TABLE "employee_documents" '
                        'DROP COLUMN IF EXISTS "document_type"'
                    )
                )
                conn.commit()
        migrate_employee_document_types(bind_engine=bind)
