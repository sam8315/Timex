"""Employee Documents — upload, access control, verify/reject, soft delete."""
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import jdatetime
import pytest

from models.employee_document import EmployeeDocument
from models.employee_document_type import EmployeeDocumentType
from web.services.employee_document_service import (
    EmployeeDocumentError,
    create_document,
    get_document,
    list_documents,
    max_upload_bytes,
    reject_document,
    resolve_document_file,
    soft_delete_document,
    verify_document,
)
from web.services.file_storage import CATEGORY_CONFIGS, get_default_storage
from .conftest import login_as


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "timex_storage"
    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(root))
    yield root


def _jalali(d: date | None = None) -> str:
    g = d or date.today()
    return jdatetime.date.fromgregorian(date=g).strftime("%Y/%m/%d")


def _type_id(db, code: str = "NATIONAL_ID") -> int:
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.code == code)
        .first()
    )
    assert row is not None, f"missing seeded document type {code}"
    return row.id


def _create_via_service(db, user_id, *, title="کارت ملی من", **kwargs):
    code = kwargs.get("document_type_code", "NATIONAL_ID")
    type_id = kwargs.get("document_type_id") or _type_id(db, code)
    return create_document(
        db,
        user_id=user_id,
        uploaded_by=user_id,
        document_type_id=type_id,
        title=title,
        file_bytes=kwargs.get("file_bytes", b"%PDF-1.4\ndoc"),
        original_filename=kwargs.get("original_filename", "id.pdf"),
        document_number=kwargs.get("document_number"),
        issue_date=kwargs.get("issue_date"),
        expiry_date=kwargs.get("expiry_date"),
        notes=kwargs.get("notes"),
    )


def test_create_document_and_upload_valid_file(db, make_user, _isolated_storage):
    user = make_user(role="user")
    doc = _create_via_service(
        db,
        user["user_id"],
        issue_date=date(2020, 1, 1),
        expiry_date=date(2030, 1, 1),
        document_number="1234567890",
    )
    assert doc.id
    assert doc.status == "PENDING"
    assert doc.storage_key.startswith("/private/employee-documents/")
    assert "/static/" not in doc.storage_key
    assert doc.original_filename == "id.pdf"
    assert doc.size_bytes > 0
    assert doc.mime_type == "application/pdf"
    disk = resolve_document_file(doc)
    assert disk.is_file()
    assert _isolated_storage.resolve() in disk.resolve().parents
    assert get_default_storage().is_uuid_filename(disk.name)


def test_invalid_extension_rejected(db, make_user):
    user = make_user(role="user")
    with pytest.raises(EmployeeDocumentError) as exc:
        _create_via_service(
            db,
            user["user_id"],
            file_bytes=b"MZ",
            original_filename="evil.exe",
        )
    assert "نوع فایل" in str(exc.value)


def test_oversized_file_rejected(db, make_user):
    user = make_user(role="user")
    limit = max_upload_bytes()
    with pytest.raises(EmployeeDocumentError) as exc:
        _create_via_service(
            db,
            user["user_id"],
            file_bytes=b"x" * (limit + 1),
            original_filename="big.pdf",
        )
    assert "حجم" in str(exc.value)


def test_empty_file_rejected(db, make_user):
    user = make_user(role="user")
    with pytest.raises(EmployeeDocumentError) as exc:
        _create_via_service(
            db,
            user["user_id"],
            file_bytes=b"",
            original_filename="empty.pdf",
        )
    assert "خالی" in str(exc.value)


def test_owner_can_list_and_download(client, db, make_user):
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"])
    login_as(client, user["national_code"])

    page = client.get("/employee-documents", follow_redirects=False)
    assert page.status_code == 200
    assert doc.title.encode("utf-8") in page.content

    file_resp = client.get(f"/employee-documents/{doc.id}/file", follow_redirects=False)
    assert file_resp.status_code == 200
    assert file_resp.content.startswith(b"%PDF")


def test_other_employee_denied(client, db, make_user):
    owner = make_user(role="user")
    other = make_user(role="user")
    doc = _create_via_service(db, owner["user_id"])

    login_as(client, other["national_code"])
    denied = client.get(f"/employee-documents/{doc.id}/file", follow_redirects=False)
    assert denied.status_code == 302
    assert "error=" in denied.headers["location"]


def test_admin_access(client, db, make_user):
    admin = make_user(role="admin")
    owner = make_user(role="user")
    doc = _create_via_service(db, owner["user_id"], title="مدرک ادمین")

    login_as(client, admin["national_code"])
    profile = client.get(f"/admin/profile/{owner['user_id']}", follow_redirects=False)
    assert profile.status_code == 200
    assert "پرونده پرسنلی".encode("utf-8") in profile.content
    assert "مدرک ادمین".encode("utf-8") in profile.content

    file_resp = client.get(f"/employee-documents/{doc.id}/file", follow_redirects=False)
    assert file_resp.status_code == 200


def test_unauthenticated_access_denied(client, db, make_user):
    owner = make_user(role="user")
    doc = _create_via_service(db, owner["user_id"])

    page = client.get("/employee-documents", follow_redirects=False)
    assert page.status_code in (302, 307)
    assert "/login" in page.headers.get("location", "")

    file_resp = client.get(f"/employee-documents/{doc.id}/file", follow_redirects=False)
    assert file_resp.status_code in (302, 307)
    assert "/login" in file_resp.headers.get("location", "")


def test_direct_static_access_unavailable(client, db, make_user):
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"])
    filename = Path(doc.storage_key).name
    leaked = client.get(f"/static/uploads/employee-documents/{filename}", follow_redirects=False)
    assert leaked.status_code == 404
    assert "/static/" not in doc.storage_key


def test_verify_and_reject(db, make_user):
    admin = make_user(role="admin")
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"])

    verified = verify_document(db, doc.id, verified_by=admin["user_id"])
    assert verified.status == "VERIFIED"
    assert verified.verified_by == admin["user_id"]
    assert verified.verified_at is not None
    assert verified.rejection_reason is None

    doc2 = _create_via_service(db, user["user_id"], title="مدرک رد")
    rejected = reject_document(
        db, doc2.id, verified_by=admin["user_id"], rejection_reason="ناقص است"
    )
    assert rejected.status == "REJECTED"
    assert rejected.rejection_reason == "ناقص است"

    with pytest.raises(EmployeeDocumentError):
        reject_document(db, doc2.id, verified_by=admin["user_id"], rejection_reason="  ")


def test_http_verify_reject_and_reason(client, db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"], title="برای رد")

    login_as(client, admin["national_code"])
    reject = client.post(
        f"/admin/profile/{user['user_id']}/documents/{doc.id}/reject",
        data={"rejection_reason": "کیفیت پایین"},
        follow_redirects=False,
    )
    assert reject.status_code == 302
    db.expire_all()
    assert get_document(db, doc.id).status == "REJECTED"
    assert get_document(db, doc.id).rejection_reason == "کیفیت پایین"

    doc2 = _create_via_service(db, user["user_id"], title="برای تأیید")
    ok = client.post(
        f"/admin/profile/{user['user_id']}/documents/{doc2.id}/verify",
        follow_redirects=False,
    )
    assert ok.status_code == 302
    db.expire_all()
    assert get_document(db, doc2.id).status == "VERIFIED"


def test_verified_cannot_be_deleted_by_employee(client, db, make_user):
    admin = make_user(role="admin")
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"])
    verify_document(db, doc.id, verified_by=admin["user_id"])

    login_as(client, user["national_code"])
    resp = client.post(
        f"/employee-documents/{doc.id}/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = unquote(resp.headers["location"])
    assert "error=" in location
    db.expire_all()
    assert get_document(db, doc.id).deleted_at is None


def test_soft_delete_and_cleanup_file(db, make_user, _isolated_storage):
    user = make_user(role="user")
    doc = _create_via_service(db, user["user_id"])
    disk = resolve_document_file(doc)
    assert disk.is_file()

    soft_delete_document(db, doc.id, deleted_by=user["user_id"], allow_verified=False)
    db.expire_all()
    with pytest.raises(EmployeeDocumentError):
        get_document(db, doc.id)
    row = db.query(EmployeeDocument).filter(EmployeeDocument.id == doc.id).first()
    assert row is not None
    assert row.deleted_at is not None
    assert row.deleted_by == user["user_id"]
    assert not disk.exists()
    assert list_documents(db, user["user_id"]) == []


def test_orphan_file_cleaned_on_db_failure(db, make_user, monkeypatch, _isolated_storage):
    user = make_user(role="user")
    storage = get_default_storage()
    before = set((_isolated_storage / "employee-documents").glob("*")) if (
        _isolated_storage / "employee-documents"
    ).exists() else set()

    original_commit = db.commit

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(RuntimeError):
        create_document(
            db,
            user_id=user["user_id"],
            uploaded_by=user["user_id"],
            document_type_id=_type_id(db, "OTHER"),
            title="orphan",
            file_bytes=b"%PDF-orphan",
            original_filename="o.pdf",
        )

    monkeypatch.setattr(db, "commit", original_commit)
    after_dir = _isolated_storage / "employee-documents"
    after = set(after_dir.glob("*")) if after_dir.exists() else set()
    assert after == before
    assert db.query(EmployeeDocument).filter(
        EmployeeDocument.user_id == user["user_id"],
        EmployeeDocument.title == "orphan",
    ).count() == 0
    # storage helper still usable
    assert storage.category_dir("employee-documents") == after_dir.resolve()


def test_expiry_metadata(db, make_user):
    user = make_user(role="user")
    issue = date(2022, 3, 21)
    expiry = date(2027, 3, 21)
    doc = _create_via_service(
        db,
        user["user_id"],
        issue_date=issue,
        expiry_date=expiry,
        document_number="EXP-1",
    )
    assert doc.issue_date == issue
    assert doc.expiry_date == expiry
    assert doc.document_number == "EXP-1"


def test_employee_http_upload(client, db, make_user):
    user = make_user(role="user")
    login_as(client, user["national_code"])
    insurance_id = _type_id(db, "INSURANCE")
    resp = client.post(
        "/employee-documents/add",
        data={
            "document_type_id": str(insurance_id),
            "title": "بیمه تأمین",
            "document_number": "INS-9",
            "issue_date_str": _jalali(date(2024, 1, 1)),
            "expiry_date_str": _jalali(date(2025, 1, 1)),
            "notes": "",
        },
        files={
            "document_file": ("ins.png", BytesIO(b"\x89PNG\r\n"), "image/png"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    docs = list_documents(db, user["user_id"])
    assert len(docs) == 1
    assert docs[0].document_type_id == insurance_id
    assert docs[0].document_type_code == "INSURANCE"
    assert docs[0].mime_type == "image/png"
    assert CATEGORY_CONFIGS["employee-documents"].name == "employee-documents"


def test_inactive_type_rejected_for_new_document(db, make_user):
    user = make_user(role="user")
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.code == "OTHER")
        .first()
    )
    assert row is not None
    row.is_active = False
    db.commit()
    try:
        with pytest.raises(EmployeeDocumentError) as exc:
            _create_via_service(
                db,
                user["user_id"],
                document_type_id=row.id,
                title="غیرفعال",
            )
        assert "غیرفعال" in str(exc.value)
    finally:
        row.is_active = True
        db.commit()


def test_model_registered():
    from models.base import Base

    assert "employee_documents" in Base.metadata.tables
    assert "employee_document_types" in Base.metadata.tables
