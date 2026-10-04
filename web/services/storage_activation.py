"""DB-backed activation of Unified File Storage for legacy Contracts / Education / Avatars.

Flow: collect DB refs → preflight all → copy → SHA-256 verify → update DB in one
transaction. Sources are never deleted. No new mapping tables.

Production: call only against an intentional target; tests use temp FS + test DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models.contract import Contract
from models.education import Education
from models.employee import Employee
from web.services.file_storage import CATEGORY_CONFIGS, FileStorage, get_default_storage
from web.services.storage_migration import (
    MIGRATABLE_CATEGORIES,
    MigrationItem,
    MigrationStatus,
    StorageMigrationService,
    build_destination_key,
    category_for_legacy_key,
    extension_allowed_for_category,
    normalize_legacy_key,
    _file_fingerprint,
)


UNIFIED_PREFIXES = (
    "/private/contracts/",
    "/private/education/",
    "/private/avatars/",
)


def is_unified_storage_key(value: Optional[str]) -> bool:
    normalized = normalize_legacy_key(value or "")
    return any(normalized.startswith(p) for p in UNIFIED_PREFIXES)


def is_legacy_key(value: Optional[str]) -> bool:
    """True when a DB path should be migrated (non-empty and not already unified)."""
    normalized = normalize_legacy_key(value or "")
    if not normalized:
        return False
    if is_unified_storage_key(normalized):
        return False
    return category_for_legacy_key(normalized) in MIGRATABLE_CATEGORIES


@dataclass
class ActivationItem:
    record_type: str  # contract | education | avatar
    record_id: int | str
    user_id: str
    field_name: str
    category: str
    legacy_key: str
    destination_key: str = ""
    source_path: Optional[Path] = None
    destination_path: Path = field(default_factory=Path)
    status: MigrationStatus = MigrationStatus.PENDING
    checksum: str = ""
    error: str = ""
    message: str = ""
    needs_db_update: bool = False
    db_updated: bool = False

    @property
    def record_identity(self) -> str:
        return f"{self.record_type}:{self.record_id}"

    def to_dict(self) -> dict:
        return {
            "record_identity": self.record_identity,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "user_id": self.user_id,
            "field_name": self.field_name,
            "category": self.category,
            "legacy_key": self.legacy_key,
            "destination_key": self.destination_key,
            "source_path": str(self.source_path) if self.source_path else None,
            "destination_path": str(self.destination_path) if self.destination_path else None,
            "status": self.status.value,
            "checksum": self.checksum,
            "error": self.error,
            "message": self.message,
            "needs_db_update": self.needs_db_update,
            "db_updated": self.db_updated,
        }


@dataclass
class ActivationReport:
    items: list[ActivationItem] = field(default_factory=list)
    dry_run: bool = True
    aborted: bool = False
    abort_reason: str = ""

    def items_for(self, category: str) -> list[ActivationItem]:
        return [i for i in self.items if i.category == category]

    def count_status(self, status: MigrationStatus, category: Optional[str] = None) -> int:
        items = self.items_for(category) if category else self.items
        return sum(1 for i in items if i.status == status)

    def count_db_updated(self, category: Optional[str] = None) -> int:
        items = self.items_for(category) if category else self.items
        return sum(1 for i in items if i.db_updated)

    def format_summary(self) -> str:
        lines: list[str] = []
        if self.aborted:
            lines.append(f"ABORTED: {self.abort_reason}")
            lines.append("")
        for category in MIGRATABLE_CATEGORIES:
            cat_items = self.items_for(category)
            lines.append(category)
            lines.append(f"  total: {len(cat_items)}")
            lines.append(f"  pending: {self.count_status(MigrationStatus.PENDING, category)}")
            lines.append(f"  copied: {self.count_status(MigrationStatus.COPIED, category)}")
            lines.append(
                f"  already_migrated: {self.count_status(MigrationStatus.ALREADY_MIGRATED, category)}"
            )
            lines.append(f"  missing: {self.count_status(MigrationStatus.MISSING, category)}")
            lines.append(f"  skipped: {self.count_status(MigrationStatus.SKIPPED, category)}")
            lines.append(f"  errors: {self.count_status(MigrationStatus.ERROR, category)}")
            lines.append(f"  db_updated: {self.count_db_updated(category)}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class StorageActivationService:
    """Activate Unified Storage for DB-referenced legacy media files."""

    def __init__(
        self,
        db: Session,
        *,
        storage: Optional[FileStorage] = None,
        migration: Optional[StorageMigrationService] = None,
    ) -> None:
        self.db = db
        self.storage = storage or get_default_storage()
        self.migration = migration or StorageMigrationService(storage=self.storage)

    def collect_references(self) -> list[ActivationItem]:
        items: list[ActivationItem] = []

        for row in self.db.query(Contract).filter(Contract.file_path.isnot(None)).all():
            key = normalize_legacy_key(row.file_path or "")
            if not key:
                continue
            items.append(
                ActivationItem(
                    record_type="contract",
                    record_id=row.id,
                    user_id=row.user_id,
                    field_name="file_path",
                    category="contracts",
                    legacy_key=key,
                )
            )

        for row in self.db.query(Education).filter(Education.certificate_path.isnot(None)).all():
            key = normalize_legacy_key(row.certificate_path or "")
            if not key:
                continue
            items.append(
                ActivationItem(
                    record_type="education",
                    record_id=row.id,
                    user_id=row.user_id,
                    field_name="certificate_path",
                    category="education",
                    legacy_key=key,
                )
            )

        for row in self.db.query(Employee).filter(Employee.photo_path.isnot(None)).all():
            key = normalize_legacy_key(row.photo_path or "")
            if not key:
                continue
            items.append(
                ActivationItem(
                    record_type="avatar",
                    record_id=row.user_id,
                    user_id=row.user_id,
                    field_name="photo_path",
                    category="avatars",
                    legacy_key=key,
                )
            )

        return items

    def preflight(self, items: Optional[list[ActivationItem]] = None) -> ActivationReport:
        report = ActivationReport(dry_run=True)
        for item in items if items is not None else self.collect_references():
            report.items.append(self._preflight_item(item))
        return report

    def execute(self, *, dry_run: bool = True) -> ActivationReport:
        """Preflight → copy → verify → DB update (unless dry_run)."""
        report = self.preflight()
        report.dry_run = dry_run

        errors = [i for i in report.items if i.status == MigrationStatus.ERROR]
        if errors:
            report.aborted = True
            report.abort_reason = (
                f"preflight found {len(errors)} error(s); no files copied and DB unchanged"
            )
            return report

        if dry_run:
            return report

        to_copy = [
            i
            for i in report.items
            if i.status == MigrationStatus.PENDING and i.needs_db_update
        ]
        for item in to_copy:
            try:
                file_item = MigrationItem(
                    category=item.category,
                    source_path=item.source_path,
                    legacy_key=item.legacy_key,
                    destination_key=item.destination_key,
                    destination_path=item.destination_path,
                    status=MigrationStatus.PENDING,
                )
                self.migration._copy_item(file_item)  # noqa: SLF001 — shared safe copy
                src_hash = _file_fingerprint(item.source_path)
                dst_hash = _file_fingerprint(item.destination_path)
                if src_hash != dst_hash:
                    raise RuntimeError("SHA-256 mismatch after copy")
                item.checksum = dst_hash
                item.status = MigrationStatus.COPIED
                item.message = "copied and verified; source retained"
            except Exception as exc:  # noqa: BLE001
                item.status = MigrationStatus.ERROR
                item.error = str(exc)
                item.message = f"copy/verify failed: {exc}"
                try:
                    if item.destination_path.is_file():
                        item.destination_path.unlink()
                except OSError:
                    pass

        if any(i.status == MigrationStatus.ERROR for i in report.items):
            report.aborted = True
            report.abort_reason = (
                "copy/verify failure; DB unchanged (destination leftovers cleaned when possible)"
            )
            return report

        # Items needing DB update: newly copied + already-on-disk identical destinations
        db_targets = [
            i
            for i in report.items
            if i.needs_db_update
            and i.status in (MigrationStatus.COPIED, MigrationStatus.ALREADY_MIGRATED)
            and i.destination_key
            and i.legacy_key != i.destination_key
        ]

        if not db_targets:
            return report

        try:
            for item in db_targets:
                self._apply_db_update(item)
            self.db.commit()
            for item in db_targets:
                item.db_updated = True
                if item.status == MigrationStatus.ALREADY_MIGRATED:
                    item.message = "DB updated to existing verified destination; source retained"
                else:
                    item.message = "copied, verified, DB updated; source retained"
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            report.aborted = True
            report.abort_reason = f"DB update failed and was rolled back: {exc}"
            for item in db_targets:
                item.db_updated = False
                item.error = str(exc)
                item.message = "DB rolled back; destination files retained for retry"
            # Destinations kept (deterministic) so retry can ALREADY_MIGRATE + DB update
        return report

    def _preflight_item(self, item: ActivationItem) -> ActivationItem:
        key = normalize_legacy_key(item.legacy_key)
        item.legacy_key = key

        if not key:
            item.status = MigrationStatus.SKIPPED
            item.message = "empty path"
            return item

        if is_unified_storage_key(key):
            key_category = category_for_legacy_key(key)
            if key_category != item.category:
                item.status = MigrationStatus.ERROR
                item.error = (
                    f"cross-category private key: expected {item.category}, got {key_category}"
                )
                item.message = item.error
                item.needs_db_update = False
                return item
            cfg = CATEGORY_CONFIGS.get(item.category)
            if cfg is None or not key.startswith(cfg.key_prefix):
                item.status = MigrationStatus.ERROR
                item.error = "invalid unified storage key for record category"
                item.message = item.error
                item.needs_db_update = False
                return item
            try:
                # Validate key shape via FileStorage (rejects traversal / bad names).
                item.destination_path = self.storage.resolve(key)
            except Exception as exc:  # noqa: BLE001
                item.status = MigrationStatus.ERROR
                item.error = f"invalid unified storage key: {exc}"
                item.message = item.error
                item.needs_db_update = False
                return item
            item.destination_key = key
            if not item.destination_path.is_file():
                item.status = MigrationStatus.MISSING
                item.message = "unified key has no resolvable file on disk"
                item.needs_db_update = False
                return item
            item.status = MigrationStatus.ALREADY_MIGRATED
            item.message = "already unified storage key; left unchanged"
            item.needs_db_update = False
            return item

        category = category_for_legacy_key(key)
        if category is None or category not in MIGRATABLE_CATEGORIES:
            item.status = MigrationStatus.ERROR
            item.error = "unrecognized legacy key"
            item.message = item.error
            return item
        if category != item.category:
            item.status = MigrationStatus.ERROR
            item.error = f"category mismatch: expected {item.category}, got {category}"
            item.message = item.error
            return item

        if not extension_allowed_for_category(category, key):
            ext = Path(key).suffix.lower() or "(none)"
            item.status = MigrationStatus.SKIPPED
            item.message = f"extension not allowed for category: {ext}"
            return item

        try:
            item.destination_key = build_destination_key(category, key)
            item.destination_path = self.storage.resolve(item.destination_key)
        except Exception as exc:  # noqa: BLE001
            item.status = MigrationStatus.ERROR
            item.error = str(exc)
            item.message = str(exc)
            return item

        source = self.migration._resolve_legacy_source(category, key)  # noqa: SLF001
        item.source_path = source if source and source.is_file() else None
        if item.source_path is None:
            item.status = MigrationStatus.MISSING
            item.message = "source file not found"
            item.needs_db_update = False
            return item

        try:
            item.checksum = _file_fingerprint(item.source_path)
        except OSError as exc:
            item.status = MigrationStatus.ERROR
            item.error = f"cannot checksum source: {exc}"
            item.message = item.error
            return item

        if item.destination_path.is_file():
            try:
                dest_hash = _file_fingerprint(item.destination_path)
            except OSError as exc:
                item.status = MigrationStatus.ERROR
                item.error = f"cannot checksum destination: {exc}"
                item.message = item.error
                return item
            if dest_hash != item.checksum:
                item.status = MigrationStatus.ERROR
                item.error = "destination exists with different content; refusing overwrite"
                item.message = item.error
                return item
            item.status = MigrationStatus.ALREADY_MIGRATED
            item.message = "destination exists with identical content"
            item.needs_db_update = key != item.destination_key
            return item

        item.status = MigrationStatus.PENDING
        item.message = "ready to copy and update DB"
        item.needs_db_update = True
        return item

    def _apply_db_update(self, item: ActivationItem) -> None:
        if item.record_type == "contract":
            row = self.db.query(Contract).filter(Contract.id == item.record_id).first()
            if not row:
                raise RuntimeError(f"contract {item.record_id} missing during DB update")
            if normalize_legacy_key(row.file_path or "") != item.legacy_key:
                raise RuntimeError(f"contract {item.record_id} path changed during migration")
            row.file_path = item.destination_key
        elif item.record_type == "education":
            row = self.db.query(Education).filter(Education.id == item.record_id).first()
            if not row:
                raise RuntimeError(f"education {item.record_id} missing during DB update")
            if normalize_legacy_key(row.certificate_path or "") != item.legacy_key:
                raise RuntimeError(f"education {item.record_id} path changed during migration")
            row.certificate_path = item.destination_key
        elif item.record_type == "avatar":
            row = self.db.query(Employee).filter(Employee.user_id == item.record_id).first()
            if not row:
                raise RuntimeError(f"employee {item.record_id} missing during DB update")
            if normalize_legacy_key(row.photo_path or "") != item.legacy_key:
                raise RuntimeError(f"employee {item.record_id} photo changed during migration")
            row.photo_path = item.destination_key
        else:
            raise RuntimeError(f"unknown record_type {item.record_type}")


def resolve_media_disk(storage_key: str, *, storage: Optional[FileStorage] = None) -> Path:
    """Resolve a DB media key (legacy or unified) to a disk path."""
    store = storage or get_default_storage()
    return store.resolve(normalize_legacy_key(storage_key))


def delete_media_file(storage_key: Optional[str], *, storage: Optional[FileStorage] = None) -> None:
    """Delete a stored media file (unified or legacy static) if present."""
    if not storage_key:
        return
    store = storage or get_default_storage()
    try:
        path = store.resolve(normalize_legacy_key(storage_key))
        if path.is_file():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


def save_media_bytes(
    category: str,
    data: bytes,
    *,
    original_filename: str,
    storage: Optional[FileStorage] = None,
) -> str:
    """Save new media under Unified Storage; returns storage_key."""
    store = storage or get_default_storage()
    return store.save(category, data, original_filename=original_filename)
