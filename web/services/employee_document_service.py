"""Business logic for Employee Documents (Unified File Storage)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models.employee_document import (
    DOCUMENT_STATUSES,
    DOCUMENT_TYPES,
    EmployeeDocument,
)
from web.services.file_storage import (
    CATEGORY_CONFIGS,
    FileStorage,
    FileStorageError,
    get_default_storage,
)

CATEGORY = "employee-documents"
_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class EmployeeDocumentError(ValueError):
    """Domain / validation error for employee documents."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _storage() -> FileStorage:
    return get_default_storage()


def _active_query(db: Session, user_id: Optional[str] = None):
    q = db.query(EmployeeDocument).filter(EmployeeDocument.deleted_at.is_(None))
    if user_id is not None:
        q = q.filter(EmployeeDocument.user_id == user_id)
    return q


def list_documents(db: Session, user_id: str) -> list[EmployeeDocument]:
    return (
        _active_query(db, user_id)
        .order_by(EmployeeDocument.uploaded_at.desc(), EmployeeDocument.id.desc())
        .all()
    )


def get_document(
    db: Session,
    document_id: int,
    *,
    include_deleted: bool = False,
) -> EmployeeDocument:
    q = db.query(EmployeeDocument).filter(EmployeeDocument.id == document_id)
    if not include_deleted:
        q = q.filter(EmployeeDocument.deleted_at.is_(None))
    doc = q.first()
    if not doc:
        raise EmployeeDocumentError("مدرک یافت نشد")
    return doc


def create_document(
    db: Session,
    *,
    user_id: str,
    uploaded_by: str,
    document_type: str,
    title: str,
    file_bytes: bytes,
    original_filename: str,
    document_number: Optional[str] = None,
    issue_date: Optional[date] = None,
    expiry_date: Optional[date] = None,
    notes: Optional[str] = None,
) -> EmployeeDocument:
    if document_type not in DOCUMENT_TYPES:
        raise EmployeeDocumentError("نوع مدرک نامعتبر است")

    title = (title or "").strip()
    if not title:
        raise EmployeeDocumentError("عنوان مدرک الزامی است")

    if not original_filename:
        raise EmployeeDocumentError("نام فایل نامعتبر است")

    storage = _storage()
    storage_key: Optional[str] = None
    try:
        storage_key = storage.save(
            CATEGORY,
            file_bytes,
            original_filename=original_filename,
        )
    except FileStorageError as exc:
        raise _map_storage_error(exc) from exc

    ext = Path(original_filename).suffix.lower()
    mime_type = _MIME_BY_EXT.get(ext, "application/octet-stream")

    doc = EmployeeDocument(
        user_id=user_id,
        document_type=document_type,
        title=title,
        document_number=(document_number or "").strip() or None,
        issue_date=issue_date,
        expiry_date=expiry_date,
        original_filename=Path(original_filename).name,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=len(file_bytes),
        status="PENDING",
        uploaded_by=uploaded_by,
        uploaded_at=_now(),
        notes=(notes or "").strip() or None,
    )
    db.add(doc)
    try:
        db.commit()
        db.refresh(doc)
    except Exception:
        db.rollback()
        if storage_key:
            storage.delete(storage_key)
        raise
    return doc


def soft_delete_document(
    db: Session,
    document_id: int,
    *,
    deleted_by: str,
    allow_verified: bool = False,
) -> EmployeeDocument:
    doc = get_document(db, document_id)
    if doc.status == "VERIFIED" and not allow_verified:
        raise EmployeeDocumentError("مدرک تأییدشده قابل حذف توسط کارمند نیست")

    storage_key = doc.storage_key
    doc.deleted_at = _now()
    doc.deleted_by = deleted_by
    try:
        db.commit()
        db.refresh(doc)
    except Exception:
        db.rollback()
        raise

    _storage().delete(storage_key)
    return doc


def verify_document(
    db: Session,
    document_id: int,
    *,
    verified_by: str,
) -> EmployeeDocument:
    doc = get_document(db, document_id)
    doc.status = "VERIFIED"
    doc.verified_by = verified_by
    doc.verified_at = _now()
    doc.rejection_reason = None
    db.commit()
    db.refresh(doc)
    return doc


def reject_document(
    db: Session,
    document_id: int,
    *,
    verified_by: str,
    rejection_reason: str,
) -> EmployeeDocument:
    reason = (rejection_reason or "").strip()
    if not reason:
        raise EmployeeDocumentError("علت رد الزامی است")

    doc = get_document(db, document_id)
    doc.status = "REJECTED"
    doc.verified_by = verified_by
    doc.verified_at = _now()
    doc.rejection_reason = reason
    db.commit()
    db.refresh(doc)
    return doc


def resolve_document_file(doc: EmployeeDocument) -> Path:
    try:
        return _storage().resolve(doc.storage_key)
    except FileStorageError as exc:
        raise EmployeeDocumentError("فایل مدرک یافت نشد") from exc


def max_upload_bytes() -> int:
    return CATEGORY_CONFIGS[CATEGORY].max_file_size


def _map_storage_error(exc: FileStorageError) -> EmployeeDocumentError:
    if exc.code == "invalid_extension":
        return EmployeeDocumentError(
            "نوع فایل مجاز نیست (فقط PDF/JPG/JPEG/PNG/WEBP)"
        )
    if exc.code == "file_too_large":
        return EmployeeDocumentError("حجم فایل بیش از ۱۰ مگابایت است")
    if exc.code == "empty_file":
        return EmployeeDocumentError("فایل خالی است")
    if exc.code == "invalid_filename":
        return EmployeeDocumentError("نام فایل نامعتبر است")
    return EmployeeDocumentError(str(exc))
