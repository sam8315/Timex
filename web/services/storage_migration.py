"""Prepare / dry-run migration of legacy files into Unified File Storage.

Phase scope (this module):
- Scan known legacy locations for contracts, education certificates, and avatars.
- Build portable deterministic destination keys from ``category + legacy_key``.
- Support **dry-run** reporting with no file or DB changes.
- Optional execute mode **copies** (never deletes/moves source, never updates DB).
- Phase 3B can pass DB path columns via ``extra_legacy_keys`` with
  ``scan_filesystem=False`` (still no DB writes in this module).

For DB-backed activation (copy + verify + DB update), see
``web.services.storage_activation.StorageActivationService``.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence
from uuid import UUID, uuid5

from web.services.file_storage import (
    CATEGORY_CONFIGS,
    LEGACY_PRIVATE_UPLOADS,
    LEGACY_STATIC_ROOT,
    FileStorage,
    get_default_storage,
)

# Stable namespace so the same logical legacy key always maps to the same destination.
_MIGRATION_NAMESPACE = UUID("6f1c8b2e-4a7d-4f91-9c3e-2d8a5b6e7f10")

MIGRATABLE_CATEGORIES = ("contracts", "education", "avatars")

SKIP_FILENAMES = {".gitkeep", ".gitignore", "thumbs.db", "desktop.ini"}


class MigrationStatus(str, Enum):
    PENDING = "pending"
    MISSING = "missing"
    ALREADY_MIGRATED = "already_migrated"
    ERROR = "error"
    SKIPPED = "skipped"
    COPIED = "copied"


@dataclass(frozen=True)
class LegacySourceRoot:
    """A filesystem directory that may contain legacy files for one category."""

    category: str
    directory: Path
    legacy_key_prefix: str


@dataclass
class MigrationItem:
    category: str
    source_path: Optional[Path]
    legacy_key: str
    destination_key: str
    destination_path: Path
    status: MigrationStatus
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "source_path": str(self.source_path) if self.source_path else None,
            "legacy_key": self.legacy_key,
            "destination_key": self.destination_key,
            "destination_path": str(self.destination_path),
            "status": self.status.value,
            "message": self.message,
        }


@dataclass
class MigrationReport:
    items: list[MigrationItem] = field(default_factory=list)
    dry_run: bool = True

    def counts_by_category(self) -> dict[str, int]:
        counts = {c: 0 for c in MIGRATABLE_CATEGORIES}
        for item in self.items:
            if item.status == MigrationStatus.SKIPPED:
                continue
            if item.category in counts:
                counts[item.category] += 1
        return counts

    def count_status(self, status: MigrationStatus) -> int:
        return sum(1 for i in self.items if i.status == status)

    def format_summary(self) -> str:
        by_cat = self.counts_by_category()
        lines = [
            f"contracts: {by_cat['contracts']} files",
            f"education: {by_cat['education']} files",
            f"avatars: {by_cat['avatars']} files",
            "",
            f"missing: {self.count_status(MigrationStatus.MISSING)}",
            f"already migrated: {self.count_status(MigrationStatus.ALREADY_MIGRATED)}",
            f"errors: {self.count_status(MigrationStatus.ERROR)}",
        ]
        if not self.dry_run:
            lines.append(f"copied: {self.count_status(MigrationStatus.COPIED)}")
            lines.append(f"pending: {self.count_status(MigrationStatus.PENDING)}")
        else:
            lines.append(f"pending: {self.count_status(MigrationStatus.PENDING)}")
        return "\n".join(lines)


def default_legacy_roots() -> list[LegacySourceRoot]:
    """Known on-disk legacy locations (no Unified Storage root)."""
    return [
        LegacySourceRoot(
            category="contracts",
            directory=LEGACY_PRIVATE_UPLOADS / "contracts",
            legacy_key_prefix="/private/contracts/",
        ),
        LegacySourceRoot(
            category="contracts",
            directory=LEGACY_STATIC_ROOT / "uploads" / "contracts",
            legacy_key_prefix="/static/uploads/contracts/",
        ),
        LegacySourceRoot(
            category="education",
            directory=LEGACY_STATIC_ROOT / "uploads" / "certificates",
            legacy_key_prefix="/static/uploads/certificates/",
        ),
        LegacySourceRoot(
            category="avatars",
            directory=LEGACY_STATIC_ROOT / "uploads" / "avatars",
            legacy_key_prefix="/static/uploads/avatars/",
        ),
    ]


def category_for_legacy_key(legacy_key: str) -> Optional[str]:
    """Map a stored path/key to a migratable category, or None."""
    normalized = (legacy_key or "").replace("\\", "/").strip()
    if not normalized:
        return None
    if normalized.startswith("/static/uploads/contracts/") or normalized.startswith(
        "/private/contracts/"
    ):
        return "contracts"
    if normalized.startswith("/static/uploads/certificates/") or normalized.startswith(
        "/private/education/"
    ):
        return "education"
    if normalized.startswith("/static/uploads/avatars/") or normalized.startswith(
        "/private/avatars/"
    ):
        return "avatars"
    # Bare contract filenames historically stored without a prefix.
    name = Path(normalized).name
    if name == normalized.lstrip("/") and Path(name).suffix:
        return "contracts"
    return None


def normalize_legacy_key(legacy_key: str) -> str:
    return (legacy_key or "").replace("\\", "/").strip()


def build_destination_key(category: str, legacy_key: str) -> str:
    """Deterministic UUID storage key from category + logical legacy key.

    Portable across hosts/install paths: does not hash absolute filesystem paths.
    """
    if category not in CATEGORY_CONFIGS:
        raise ValueError(f"unknown category: {category}")
    normalized = normalize_legacy_key(legacy_key)
    if not normalized:
        raise ValueError("legacy key is empty")
    ext = Path(normalized).suffix.lower() or ".bin"
    digest = uuid5(_MIGRATION_NAMESPACE, f"{category}:{normalized}")
    return f"{CATEGORY_CONFIGS[category].key_prefix}{digest.hex}{ext}"


def extension_allowed_for_category(category: str, legacy_key_or_name: str) -> bool:
    """True when the file extension is allowed by CATEGORY_CONFIGS."""
    if category not in CATEGORY_CONFIGS:
        return False
    ext = Path(normalize_legacy_key(legacy_key_or_name)).suffix.lower()
    return ext in CATEGORY_CONFIGS[category].allowed_extensions


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class StorageMigrationService:
    """Plan and optionally copy legacy files into Unified Storage (no DB writes)."""

    def __init__(
        self,
        *,
        storage: Optional[FileStorage] = None,
        legacy_roots: Optional[Sequence[LegacySourceRoot]] = None,
    ) -> None:
        self.storage = storage or get_default_storage()
        self.legacy_roots = list(legacy_roots) if legacy_roots is not None else default_legacy_roots()

    def plan(
        self,
        *,
        extra_legacy_keys: Optional[Iterable[str]] = None,
        scan_filesystem: bool = True,
    ) -> MigrationReport:
        """Classify migration items.

        Parameters
        ----------
        extra_legacy_keys:
            Logical keys (e.g. DB ``file_path`` / ``certificate_path`` /
            ``photo_path`` values). Phase 3B can pass only the keys that still
            need migration — no DB writes happen here.
        scan_filesystem:
            When True (default), scan configured legacy directories.
            When False, only ``extra_legacy_keys`` are planned (DB-driven mode
            for Phase 3B).
        """
        report = MigrationReport(dry_run=True)
        seen_sources: set[Path] = set()
        seen_keys: set[str] = set()

        if scan_filesystem:
            for root in self.legacy_roots:
                report.items.extend(self._scan_root(root, seen_sources, seen_keys))

        if extra_legacy_keys:
            for key in extra_legacy_keys:
                normalized = normalize_legacy_key(key)
                if not normalized or normalized in seen_keys:
                    continue
                item = self._plan_from_legacy_key(normalized)
                if item is None:
                    continue
                if item.source_path and item.source_path.resolve() in seen_sources:
                    seen_keys.add(normalized)
                    continue
                if item.source_path:
                    seen_sources.add(item.source_path.resolve())
                seen_keys.add(normalized)
                report.items.append(item)

        return report

    def dry_run(
        self,
        *,
        extra_legacy_keys: Optional[Iterable[str]] = None,
        scan_filesystem: bool = True,
    ) -> MigrationReport:
        """Alias for ``plan`` — never mutates files or DB."""
        return self.plan(
            extra_legacy_keys=extra_legacy_keys,
            scan_filesystem=scan_filesystem,
        )

    def execute(
        self,
        *,
        dry_run: bool = True,
        extra_legacy_keys: Optional[Iterable[str]] = None,
        scan_filesystem: bool = True,
    ) -> MigrationReport:
        """Run a plan. With ``dry_run=True`` (default) nothing is written.

        When ``dry_run=False``, pending files are **copied** to Unified Storage.
        Sources are never deleted; DB columns are never updated.

        Phase 3B can call with ``scan_filesystem=False`` and DB-sourced
        ``extra_legacy_keys`` only.
        """
        report = self.plan(
            extra_legacy_keys=extra_legacy_keys,
            scan_filesystem=scan_filesystem,
        )
        report.dry_run = dry_run
        if dry_run:
            return report

        for item in report.items:
            if item.status != MigrationStatus.PENDING:
                continue
            try:
                self._copy_item(item)
                item.status = MigrationStatus.COPIED
                item.message = "copied; source retained; DB unchanged"
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                item.status = MigrationStatus.ERROR
                item.message = f"copy failed: {exc}"
        return report

    def _scan_root(
        self,
        root: LegacySourceRoot,
        seen_sources: set[Path],
        seen_keys: set[str],
    ) -> list[MigrationItem]:
        items: list[MigrationItem] = []
        directory = root.directory
        if not directory.exists() or not directory.is_dir():
            return items

        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            legacy_key = f"{root.legacy_key_prefix}{path.name}"
            if path.name.lower() in SKIP_FILENAMES or path.name.startswith("."):
                items.append(
                    MigrationItem(
                        category=root.category,
                        source_path=path,
                        legacy_key=legacy_key,
                        destination_key="",
                        destination_path=Path(),
                        status=MigrationStatus.SKIPPED,
                        message="ignored auxiliary file",
                    )
                )
                seen_keys.add(legacy_key)
                continue

            resolved = path.resolve()
            if resolved in seen_sources or legacy_key in seen_keys:
                continue
            seen_sources.add(resolved)
            seen_keys.add(legacy_key)

            items.append(self._classify(root.category, path, legacy_key))
        return items

    def _plan_from_legacy_key(self, legacy_key: str) -> Optional[MigrationItem]:
        category = category_for_legacy_key(legacy_key)
        if category is None or category not in MIGRATABLE_CATEGORIES:
            return MigrationItem(
                category="unknown",
                source_path=None,
                legacy_key=legacy_key,
                destination_key="",
                destination_path=Path(),
                status=MigrationStatus.ERROR,
                message="unrecognized legacy key",
            )

        normalized = normalize_legacy_key(legacy_key)
        if not extension_allowed_for_category(category, normalized):
            ext = Path(normalized).suffix.lower() or "(none)"
            return MigrationItem(
                category=category,
                source_path=None,
                legacy_key=normalized,
                destination_key="",
                destination_path=Path(),
                status=MigrationStatus.SKIPPED,
                message=f"extension not allowed for category: {ext}",
            )

        # Already a unified private key living under storage root → migrated.
        cfg = CATEGORY_CONFIGS[category]
        if normalized.startswith(cfg.key_prefix):
            dest = self.storage.resolve(normalized)
            if dest.is_file() and self._is_under_storage(dest):
                return MigrationItem(
                    category=category,
                    source_path=dest,
                    legacy_key=normalized,
                    destination_key=normalized,
                    destination_path=dest,
                    status=MigrationStatus.ALREADY_MIGRATED,
                    message="already under unified storage",
                )

        source = self._resolve_legacy_source(category, normalized)
        if source is None or not source.is_file():
            dest_key = build_destination_key(category, normalized)
            dest_path = self.storage.resolve(dest_key)
            return MigrationItem(
                category=category,
                source_path=source,
                legacy_key=normalized,
                destination_key=dest_key,
                destination_path=dest_path,
                status=MigrationStatus.MISSING,
                message="source file not found",
            )
        return self._classify(category, source, normalized)

    def _classify(
        self,
        category: str,
        source: Path,
        legacy_key: str,
    ) -> MigrationItem:
        normalized = normalize_legacy_key(legacy_key)
        if not extension_allowed_for_category(category, normalized):
            ext = Path(normalized).suffix.lower() or "(none)"
            return MigrationItem(
                category=category,
                source_path=source,
                legacy_key=normalized,
                destination_key="",
                destination_path=Path(),
                status=MigrationStatus.SKIPPED,
                message=f"extension not allowed for category: {ext}",
            )

        try:
            dest_key = build_destination_key(category, normalized)
            dest_path = self.storage.resolve(dest_key)
        except Exception as exc:  # noqa: BLE001
            return MigrationItem(
                category=category,
                source_path=source,
                legacy_key=normalized,
                destination_key="",
                destination_path=Path(),
                status=MigrationStatus.ERROR,
                message=str(exc),
            )

        # Source already sits in unified storage with a private key → done.
        if self._is_under_storage(source) and normalized.startswith(
            CATEGORY_CONFIGS[category].key_prefix
        ):
            return MigrationItem(
                category=category,
                source_path=source,
                legacy_key=normalized,
                destination_key=normalized,
                destination_path=source,
                status=MigrationStatus.ALREADY_MIGRATED,
                message="source already in unified storage",
            )

        if dest_path.is_file():
            try:
                if _file_fingerprint(source) == _file_fingerprint(dest_path):
                    return MigrationItem(
                        category=category,
                        source_path=source,
                        legacy_key=normalized,
                        destination_key=dest_key,
                        destination_path=dest_path,
                        status=MigrationStatus.ALREADY_MIGRATED,
                        message="destination exists with identical content",
                    )
                return MigrationItem(
                    category=category,
                    source_path=source,
                    legacy_key=normalized,
                    destination_key=dest_key,
                    destination_path=dest_path,
                    status=MigrationStatus.ERROR,
                    message="destination exists with different content; refusing overwrite",
                )
            except OSError as exc:
                return MigrationItem(
                    category=category,
                    source_path=source,
                    legacy_key=normalized,
                    destination_key=dest_key,
                    destination_path=dest_path,
                    status=MigrationStatus.ERROR,
                    message=f"could not compare files: {exc}",
                )

        if not source.is_file():
            return MigrationItem(
                category=category,
                source_path=source,
                legacy_key=normalized,
                destination_key=dest_key,
                destination_path=dest_path,
                status=MigrationStatus.MISSING,
                message="source file not found",
            )

        return MigrationItem(
            category=category,
            source_path=source,
            legacy_key=normalized,
            destination_key=dest_key,
            destination_path=dest_path,
            status=MigrationStatus.PENDING,
            message="ready to copy",
        )

    def _copy_item(self, item: MigrationItem) -> None:
        """Copy source → destination via a temp file; clean up on failure."""
        if item.source_path is None or not item.source_path.is_file():
            raise FileNotFoundError("source missing")
        dest = item.destination_path
        if dest.is_file():
            raise FileExistsError("destination already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".migrating")
        try:
            if tmp.exists():
                tmp.unlink()
            # Copy only — never move/delete source (rollback-friendly).
            shutil.copy2(item.source_path, tmp)
            tmp.replace(dest)
        except Exception:
            for path in (tmp, dest):
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass
            raise

    def _resolve_legacy_source(self, category: str, legacy_key: str) -> Optional[Path]:
        """Best-effort locate a legacy file without requiring Unified Storage."""
        normalized = legacy_key.replace("\\", "/").strip()
        filename = Path(normalized).name
        candidates: list[Path] = []
        for root in self.legacy_roots:
            if root.category != category:
                continue
            if normalized.startswith(root.legacy_key_prefix):
                candidates.append(root.directory / filename)
            else:
                candidates.append(root.directory / filename)
        # Also ask FileStorage (keeps current compatibility layer).
        try:
            candidates.append(self.storage.resolve(normalized))
        except Exception:  # noqa: BLE001
            pass
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
        return candidates[0].resolve() if candidates else None

    def _is_under_storage(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.storage.root.resolve())
            return True
        except ValueError:
            return False


def run_dry_run_report(
    *,
    storage: Optional[FileStorage] = None,
    legacy_roots: Optional[Sequence[LegacySourceRoot]] = None,
    extra_legacy_keys: Optional[Iterable[str]] = None,
    scan_filesystem: bool = True,
) -> str:
    """Convenience helper used by ops/scripts — dry-run only."""
    service = StorageMigrationService(storage=storage, legacy_roots=legacy_roots)
    report = service.dry_run(
        extra_legacy_keys=extra_legacy_keys,
        scan_filesystem=scan_filesystem,
    )
    return report.format_summary()


if __name__ == "__main__":
    print(run_dry_run_report())
