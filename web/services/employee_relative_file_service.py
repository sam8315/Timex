"""آپلود/حذف/دانلود فایل‌های پیوست بستگان."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from models.employee_relative_file import EmployeeRelativeFile
from web.services.employee_relative_service import (
    EmployeeRelativeServiceError,
    get_relative,
)
from web.services.file_storage import (
    CATEGORY_CONFIGS,
    FileStorage,
    FileStorageError,
    get_default_storage,
)

CATEGORY = "employee-relatives"
_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _storage() -> FileStorage:
    return get_default_storage()


def _map_storage_error(exc: FileStorageError) -> EmployeeRelativeServiceError:
    if exc.code == "invalid_extension":
        return EmployeeRelativeServiceError(
            "نوع فایل مجاز نیست (فقط PDF/JPG/JPEG/PNG/WEBP)"
        )
    if exc.code == "file_too_large":
        return EmployeeRelativeServiceError("حجم فایل بیش از ۱۰ مگابایت است")
    if exc.code == "empty_file":
        return EmployeeRelativeServiceError("فایل خالی است")
    if exc.code == "invalid_filename":
        return EmployeeRelativeServiceError("نام فایل نامعتبر است")
    return EmployeeRelativeServiceError(str(exc))


def list_files(db: Session, relative_id: int) -> list[EmployeeRelativeFile]:
    return (
        db.query(EmployeeRelativeFile)
        .filter(
            EmployeeRelativeFile.relative_id == relative_id,
            EmployeeRelativeFile.deleted_at.is_(None),
        )
        .order_by(
            EmployeeRelativeFile.uploaded_at.desc(),
            EmployeeRelativeFile.id.desc(),
        )
        .all()
    )


def get_file(
    db: Session,
    file_id: int,
    *,
    include_deleted: bool = False,
) -> EmployeeRelativeFile:
    q = (
        db.query(EmployeeRelativeFile)
        .options(joinedload(EmployeeRelativeFile.relative))
        .filter(EmployeeRelativeFile.id == file_id)
    )
    if not include_deleted:
        q = q.filter(EmployeeRelativeFile.deleted_at.is_(None))
    row = q.first()
    if not row:
        raise EmployeeRelativeServiceError("فایل یافت نشد")
    return row


def _relative_for_user(db: Session, user_id: str, relative_id: int):
    relative = get_relative(db, relative_id)
    if relative.user_id != user_id:
        raise EmployeeRelativeServiceError("فرد وابسته یافت نشد")
    return relative


def _maybe_reset_verification(relative, *, reset_verification: bool) -> None:
    if reset_verification and relative.status in ("VERIFIED", "REJECTED"):
        relative.status = "PENDING"
        relative.verified_by = None
        relative.verified_at = None
        relative.rejection_reason = None


def add_file(
    db: Session,
    *,
    user_id: str,
    relative_id: int,
    file_bytes: bytes,
    original_filename: str,
    uploaded_by: str,
    reset_verification: bool = False,
) -> EmployeeRelativeFile:
    relative = _relative_for_user(db, user_id, relative_id)

    if not original_filename:
        raise EmployeeRelativeServiceError("نام فایل نامعتبر است")

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
    row = EmployeeRelativeFile(
        relative_id=relative.id,
        storage_key=storage_key,
        original_filename=Path(original_filename).name,
        mime_type=_MIME_BY_EXT.get(ext, "application/octet-stream"),
        size_bytes=len(file_bytes),
        uploaded_by=uploaded_by,
        uploaded_at=_now(),
    )
    db.add(row)
    _maybe_reset_verification(relative, reset_verification=reset_verification)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        if storage_key:
            storage.delete(storage_key)
        raise
    return row


def soft_delete_file(
    db: Session,
    *,
    user_id: str,
    relative_id: int,
    file_id: int,
    deleted_by: str,
    reset_verification: bool = False,
) -> EmployeeRelativeFile:
    relative = _relative_for_user(db, user_id, relative_id)
    row = get_file(db, file_id)
    if row.relative_id != relative.id:
        raise EmployeeRelativeServiceError("فایل متعلق به این فرد وابسته نیست")

    storage_key = row.storage_key
    row.deleted_at = _now()
    row.deleted_by = deleted_by
    _maybe_reset_verification(relative, reset_verification=reset_verification)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise

    _storage().delete(storage_key)
    return row


def resolve_file_path(row: EmployeeRelativeFile) -> Path:
    try:
        return _storage().resolve(row.storage_key)
    except FileStorageError as exc:
        raise EmployeeRelativeServiceError("فایل یافت نشد") from exc


def max_upload_bytes() -> int:
    return CATEGORY_CONFIGS[CATEGORY].max_file_size
