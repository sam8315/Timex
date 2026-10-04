"""Controlled production migration CLI for Unified Storage.

Safety model
------------
``--execute`` is allowed only after hard Go/No-Go gates:

1. Backup manifest verification (existence + optional SHA-256)
2. Fresh preflight + dry-run via ``StorageActivationService``
3. Storage outside source tree (blocker for execute)
4. Zero conflicts / invalid refs / missing (unless ``--allow-missing``)
5. Free disk space >= total ready candidate source bytes
6. Explicit ``--confirm-production``

This module never deletes legacy sources and never accepts arbitrary source paths.
Migration logic is delegated entirely to ``StorageActivationService``.

Usage::

    python -m web.services.storage_production_migration --preflight
    python -m web.services.storage_production_migration --execute \\
        --backup-manifest backups/storage_migration_backup.json \\
        --confirm-production
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from web.services.file_storage import (
    PROJECT_ROOT,
    FileStorage,
    get_default_storage,
)
from web.services.storage_activation import (
    ActivationReport,
    StorageActivationService,
)
from web.services.storage_migration import MigrationStatus
from web.services.storage_production_preflight import (
    CandidateCounts,
    ProductionPreflightReport,
    classify_activation_items,
    format_human_report,
    run_production_preflight,
)


DEFAULT_BACKUP_MANIFEST = Path("backups") / "storage_migration_backup.json"
DEFAULT_JOURNAL_DIR = Path("backups")
DEFAULT_MAX_BACKUP_AGE_HOURS = 24.0


@dataclass
class BackupArtifactReport:
    path: str
    exists: bool
    size_bytes: int
    non_empty: bool
    size_bytes_expected: Optional[int]
    size_ok: Optional[bool]
    sha256_expected: Optional[str]
    sha256_actual: Optional[str]
    checksum_ok: Optional[bool]
    errors: list[str] = field(default_factory=list)


@dataclass
class BackupManifestReport:
    path: str
    exists: bool
    valid_json: bool
    operator: str = ""
    created_at: str = ""
    created_at_parsed: Optional[str] = None
    target: dict[str, Any] = field(default_factory=dict)
    database_backup: Optional[BackupArtifactReport] = None
    legacy_backup: Optional[BackupArtifactReport] = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.exists
            and self.valid_json
            and not self.errors
            and self.database_backup is not None
            and self.legacy_backup is not None
            and not self.database_backup.errors
            and not self.legacy_backup.errors
        )


@dataclass
class TargetIdentity:
    database: str
    storage_root: str
    environment: str
    target_id: str
    candidate_count: int = 0
    total_ready_bytes: int = 0


@dataclass
class GateEvaluation:
    allowed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    target: Optional[TargetIdentity] = None
    backup: Optional[BackupManifestReport] = None
    preflight: Optional[ProductionPreflightReport] = None
    dry_run: Optional[ProductionPreflightReport] = None
    activation_dry_run: Optional[ActivationReport] = None
    candidates: CandidateCounts = field(default_factory=CandidateCounts)
    ready_bytes: int = 0
    free_bytes: Optional[int] = None
    headroom_bytes: Optional[int] = None
    confirm_production: bool = False
    allow_missing: int = 0
    max_backup_age_hours: float = DEFAULT_MAX_BACKUP_AGE_HOURS


@dataclass
class ExecutionJournal:
    started_at: str
    finished_at: str = ""
    mode: str = "execute"
    phase: str = "started"  # started | executing | completed | blocked | aborted
    target: dict[str, Any] = field(default_factory=dict)
    target_id: str = ""
    backup_manifest: dict[str, Any] = field(default_factory=dict)
    dry_run_result: dict[str, Any] = field(default_factory=dict)
    candidate_counts: dict[str, Any] = field(default_factory=dict)
    ready_bytes: int = 0
    free_bytes: Optional[int] = None
    gates: dict[str, Any] = field(default_factory=dict)
    copied: int = 0
    already_migrated: int = 0
    missing: int = 0
    conflicts: int = 0
    errors: int = 0
    db_updated: int = 0
    aborted: bool = False
    abort_reason: str = ""
    executed: bool = False
    sources_deleted: bool = False  # always False — invariant
    journal_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stat_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def database_identity(db: Optional[Session] = None) -> str:
    """Return a non-secret DB identity string for operator visibility."""
    # Prefer live bind URL when a session is provided (tests / alternate engines).
    if db is not None:
        try:
            url = db.get_bind().url
            user = url.username or ""
            host = url.host or ""
            port = url.port or ""
            name = url.database or ""
            return f"{user}@{host}:{port}/{name}"
        except Exception:  # noqa: BLE001
            pass
    try:
        from config.settings import DB_HOST, DB_NAME, DB_PORT, DB_USER

        return f"{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    except Exception:  # noqa: BLE001
        return "unknown"


def environment_label() -> str:
    return (
        os.getenv("TIMEX_ENV")
        or os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or "unspecified"
    )


def build_target_identity(
    *,
    db: Session,
    storage_root: Path,
    candidate_count: int = 0,
    total_ready_bytes: int = 0,
) -> TargetIdentity:
    db_id = database_identity(db)
    root = str(Path(storage_root).resolve())
    env = environment_label()
    material = f"{db_id}|{root}|{env}".encode("utf-8")
    target_id = hashlib.sha256(material).hexdigest()[:16]
    return TargetIdentity(
        database=db_id,
        storage_root=root,
        environment=env,
        target_id=target_id,
        candidate_count=candidate_count,
        total_ready_bytes=total_ready_bytes,
    )


def _empty_artifact(label: str, errors: list[str], *, expected_sha: Optional[str] = None) -> BackupArtifactReport:
    return BackupArtifactReport(
        path="",
        exists=False,
        size_bytes=0,
        non_empty=False,
        size_bytes_expected=None,
        size_ok=None,
        sha256_expected=expected_sha,
        sha256_actual=None,
        checksum_ok=None,
        errors=errors,
    )


def path_is_within_root(path: Path, root: Path) -> bool:
    """True when ``path`` resolves to ``root`` or a descendant (not a sibling)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def coerce_max_backup_age_hours(value: Any) -> tuple[Optional[float], Optional[str]]:
    """Return ``(hours, error)``. Negative / non-numeric values are rejected."""
    if value is None:
        return DEFAULT_MAX_BACKUP_AGE_HOURS, None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None, "max_backup_age_hours must be a non-negative number"
    if hours != hours or hours < 0:  # NaN or negative
        return None, "max_backup_age_hours must be a non-negative number"
    return hours, None


def verify_backup_artifact(
    spec: Any,
    *,
    label: str,
    storage_root: Optional[Path] = None,
) -> BackupArtifactReport:
    """Verify a backup artifact for production execute.

    Requires exists, non-empty, size_bytes match, sha256 match, and that the
    artifact path is not inside ``storage_root``.
    """
    errors: list[str] = []
    if not isinstance(spec, dict):
        return _empty_artifact(label, [f"{label}: missing or invalid object"])

    raw_path = str(spec.get("path") or "").strip()
    expected_raw = spec.get("sha256")
    expected = str(expected_raw).strip().lower() if expected_raw else None
    size_raw = spec.get("size_bytes")
    size_expected: Optional[int]
    if size_raw is None or size_raw == "":
        size_expected = None
        errors.append(f"{label}: size_bytes is required")
    else:
        try:
            size_expected = int(size_raw)
        except (TypeError, ValueError):
            size_expected = None
            errors.append(f"{label}: size_bytes must be an integer")

    if not expected:
        errors.append(f"{label}: sha256 is required")

    if not raw_path:
        errors.append(f"{label}: path is required")
        return BackupArtifactReport(
            path="",
            exists=False,
            size_bytes=0,
            non_empty=False,
            size_bytes_expected=size_expected,
            size_ok=None,
            sha256_expected=expected,
            sha256_actual=None,
            checksum_ok=None,
            errors=errors,
        )

    # Reject path traversal tricks in the declared path string itself.
    if ".." in Path(raw_path).parts:
        errors.append(f"{label}: path traversal rejected")
        return BackupArtifactReport(
            path=raw_path,
            exists=False,
            size_bytes=0,
            non_empty=False,
            size_bytes_expected=size_expected,
            size_ok=None,
            sha256_expected=expected,
            sha256_actual=None,
            checksum_ok=None,
            errors=errors,
        )

    path = Path(raw_path)
    if storage_root is not None and path_is_within_root(path, storage_root):
        errors.append(
            f"{label}: backup path must not be inside storage root "
            f"(path={path.resolve()} root={Path(storage_root).resolve()})"
        )

    if not path.exists():
        errors.append(f"{label}: file not found: {path}")
        return BackupArtifactReport(
            path=str(path),
            exists=False,
            size_bytes=0,
            non_empty=False,
            size_bytes_expected=size_expected,
            size_ok=None,
            sha256_expected=expected,
            sha256_actual=None,
            checksum_ok=None,
            errors=errors,
        )

    if not path.is_file():
        errors.append(f"{label}: path is not a file: {path}")
        return BackupArtifactReport(
            path=str(path),
            exists=True,
            size_bytes=0,
            non_empty=False,
            size_bytes_expected=size_expected,
            size_ok=None,
            sha256_expected=expected,
            sha256_actual=None,
            checksum_ok=None,
            errors=errors,
        )

    size = _safe_stat_size(path)
    non_empty = size > 0
    if not non_empty:
        errors.append(f"{label}: backup file is empty: {path}")

    size_ok: Optional[bool] = None
    if size_expected is not None:
        size_ok = size == size_expected
        if not size_ok:
            errors.append(
                f"{label}: size_bytes mismatch (expected {size_expected}, got {size})"
            )

    actual: Optional[str] = None
    checksum_ok: Optional[bool] = None
    if expected:
        actual = _sha256_file(path)
        checksum_ok = actual == expected
        if not checksum_ok:
            errors.append(
                f"{label}: sha256 mismatch (expected {expected}, got {actual})"
            )

    return BackupArtifactReport(
        path=str(path.resolve()),
        exists=True,
        size_bytes=size,
        non_empty=non_empty,
        size_bytes_expected=size_expected,
        size_ok=size_ok,
        sha256_expected=expected,
        sha256_actual=actual,
        checksum_ok=checksum_ok,
        errors=errors,
    )


def parse_manifest_created_at(value: str) -> datetime:
    """Parse ISO-8601 created_at; raise ValueError if invalid."""
    text = (value or "").strip()
    if not text:
        raise ValueError("created_at is empty")
    normalized = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_manifest_target(
    manifest_target: Any, current: TargetIdentity
) -> list[str]:
    """Hard-bind backup manifest to the live execute target."""
    errors: list[str] = []
    if not isinstance(manifest_target, dict) or not manifest_target:
        return [
            "manifest.target is required "
            "(legacy manifests without target are rejected)"
        ]

    tid = str(manifest_target.get("target_id") or "").strip()
    if not tid:
        errors.append("manifest.target.target_id is required")
    elif tid != current.target_id:
        errors.append(
            f"manifest.target.target_id mismatch: "
            f"manifest={tid} current={current.target_id}"
        )

    m_root = str(manifest_target.get("storage_root") or "").strip()
    if not m_root:
        errors.append("manifest.target.storage_root is required")
    else:
        try:
            if Path(m_root).resolve() != Path(current.storage_root).resolve():
                errors.append(
                    f"manifest.target.storage_root mismatch: "
                    f"manifest={m_root} current={current.storage_root}"
                )
        except OSError as exc:
            errors.append(f"manifest.target.storage_root invalid: {exc}")

    m_db = str(manifest_target.get("database") or "").strip()
    if not m_db:
        errors.append("manifest.target.database is required")
    elif m_db != current.database:
        errors.append(
            f"manifest.target.database mismatch: "
            f"manifest={m_db} current={current.database}"
        )

    m_env = str(manifest_target.get("environment") or "").strip()
    if m_env and m_env != current.environment:
        errors.append(
            f"manifest.target.environment mismatch: "
            f"manifest={m_env} current={current.environment}"
        )

    return errors


def verify_backup_manifest(
    manifest_path: Path,
    *,
    current_target: Optional[TargetIdentity] = None,
    now: Optional[datetime] = None,
    max_backup_age_hours: float = DEFAULT_MAX_BACKUP_AGE_HOURS,
    storage_root: Optional[Path] = None,
) -> BackupManifestReport:
    """Validate backup manifest for production execute (strict; no legacy accept)."""
    report = BackupManifestReport(
        path=str(manifest_path),
        exists=manifest_path.is_file(),
        valid_json=False,
    )
    if not report.exists:
        report.errors.append(f"backup manifest not found: {manifest_path}")
        return report

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.errors.append(f"invalid backup manifest JSON: {exc}")
        return report

    if not isinstance(payload, dict):
        report.errors.append("backup manifest root must be a JSON object")
        return report

    report.valid_json = True
    report.created_at = str(payload.get("created_at") or "")
    report.operator = str(payload.get("operator") or "")
    if not report.operator:
        report.errors.append("manifest.operator is required")

    if not report.created_at:
        report.errors.append("manifest.created_at is required")
    else:
        try:
            created = parse_manifest_created_at(report.created_at)
            report.created_at_parsed = created.isoformat()
            reference = now or datetime.now(timezone.utc)
            if created > reference:
                report.errors.append(
                    f"manifest.created_at is in the future: {report.created_at}"
                )
            else:
                age = reference - created
                max_age = timedelta(hours=float(max_backup_age_hours))
                # Boundary (== max_age) is allowed; only strictly older fails.
                if age > max_age:
                    report.errors.append(
                        f"manifest.created_at is too old: age={age} "
                        f"max_age={max_age} (max_backup_age_hours={max_backup_age_hours})"
                    )
        except ValueError as exc:
            report.errors.append(f"manifest.created_at is invalid ISO datetime: {exc}")

    if current_target is not None:
        report.target = (
            dict(payload["target"]) if isinstance(payload.get("target"), dict) else {}
        )
        report.errors.extend(
            validate_manifest_target(payload.get("target"), current_target)
        )
    else:
        # Execute path always supplies current_target; missing target is still invalid.
        if not isinstance(payload.get("target"), dict):
            report.errors.append(
                "manifest.target is required "
                "(legacy manifests without target are rejected)"
            )
        else:
            report.target = dict(payload["target"])

    root = storage_root
    if root is None and current_target is not None and current_target.storage_root:
        root = Path(current_target.storage_root)

    report.database_backup = verify_backup_artifact(
        payload.get("database_backup"),
        label="database_backup",
        storage_root=root,
    )
    report.legacy_backup = verify_backup_artifact(
        payload.get("legacy_backup"),
        label="legacy_backup",
        storage_root=root,
    )
    return report


def sum_ready_source_bytes(activation: ActivationReport) -> int:
    """Sum bytes of PENDING candidate source files (DB-backed activation only)."""
    total = 0
    for item in activation.items:
        if item.status != MigrationStatus.PENDING:
            continue
        if item.source_path is None:
            continue
        try:
            if item.source_path.is_file():
                total += int(item.source_path.stat().st_size)
        except OSError:
            continue
    return total


def _activation_to_summary(report: ActivationReport) -> dict[str, Any]:
    return {
        "dry_run": report.dry_run,
        "aborted": report.aborted,
        "abort_reason": report.abort_reason,
        "pending": report.count_status(MigrationStatus.PENDING),
        "copied": report.count_status(MigrationStatus.COPIED),
        "already_migrated": report.count_status(MigrationStatus.ALREADY_MIGRATED),
        "missing": report.count_status(MigrationStatus.MISSING),
        "errors": report.count_status(MigrationStatus.ERROR),
        "skipped": report.count_status(MigrationStatus.SKIPPED),
        "db_updated": report.count_db_updated(),
        "human": report.format_summary(),
    }


def evaluate_execute_gates(
    *,
    db: Session,
    storage: Optional[FileStorage] = None,
    activation: Optional[StorageActivationService] = None,
    backup_manifest: Optional[Path] = None,
    confirm_production: bool = False,
    allow_missing: int = 0,
    max_backup_age_hours: Any = DEFAULT_MAX_BACKUP_AGE_HOURS,
    legacy_roots: Optional[tuple[tuple[str, Path], ...]] = None,
    require_backup: bool = True,
    require_confirm: bool = True,
    now: Optional[datetime] = None,
) -> GateEvaluation:
    """Evaluate hard Go/No-Go gates for a controlled production execute."""
    store = storage or get_default_storage()
    service = activation or StorageActivationService(db, storage=store)
    age_hours, age_error = coerce_max_backup_age_hours(max_backup_age_hours)
    result = GateEvaluation(
        allowed=False,
        confirm_production=confirm_production,
        allow_missing=max(0, int(allow_missing)),
        max_backup_age_hours=(
            age_hours if age_hours is not None else DEFAULT_MAX_BACKUP_AGE_HOURS
        ),
    )
    if age_error:
        result.blockers.append(age_error)

    # 1) Storage + DB preflight (read-only)
    preflight = run_production_preflight(
        db=db,
        storage=store,
        activation=service,
        dry_run=False,
        legacy_roots=legacy_roots,
        storage_root=store.root,
    )
    result.preflight = preflight
    result.warnings.extend(preflight.warnings)

    # 2) Dry-run (must be side-effect free)
    dry = run_production_preflight(
        db=db,
        storage=store,
        activation=service,
        dry_run=True,
        legacy_roots=legacy_roots,
        storage_root=store.root,
    )
    result.dry_run = dry
    # Capture underlying activation report for byte accounting / journal.
    activation_dry = service.execute(dry_run=True)
    result.activation_dry_run = activation_dry
    result.candidates = classify_activation_items(activation_dry)
    result.ready_bytes = sum_ready_source_bytes(activation_dry)

    storage_report = dry.storage or preflight.storage
    free_bytes = storage_report.free_bytes if storage_report else None
    result.free_bytes = free_bytes
    if free_bytes is not None:
        result.headroom_bytes = free_bytes - result.ready_bytes

    target = build_target_identity(
        db=db,
        storage_root=store.root,
        candidate_count=result.candidates.ready,
        total_ready_bytes=result.ready_bytes,
    )
    result.target = target

    # --- Hard blockers ---
    if storage_report is None:
        result.blockers.append("storage root inspection unavailable")
    else:
        if not storage_report.exists:
            result.blockers.append("storage root does not exist")
        if not storage_report.is_directory:
            result.blockers.append("storage root is not a directory")
        if not storage_report.accessible:
            result.blockers.append("storage root is not accessible")
        if not storage_report.writable:
            result.blockers.append("storage root is not writable")
        if not storage_report.outside_source_tree:
            result.blockers.append(
                f"storage root must be outside source tree for execute "
                f"(root={storage_report.path}, project={PROJECT_ROOT})"
            )
        result.blockers.extend(
            e for e in storage_report.errors if e not in result.blockers
        )

    if dry.db_error or preflight.db_error:
        result.blockers.append(dry.db_error or preflight.db_error)

    if dry.db_changed or dry.filesystem_changed:
        result.blockers.append("dry-run reported unexpected mutations")
    if activation_dry.aborted and activation_dry.count_status(MigrationStatus.ERROR):
        # Conflicts / invalid already counted below; keep abort reason visible.
        if activation_dry.abort_reason:
            result.warnings.append(f"dry-run aborted: {activation_dry.abort_reason}")

    c = result.candidates
    if c.conflicts:
        result.blockers.append(f"{c.conflicts} destination conflict(s)")
    if c.invalid:
        result.blockers.append(f"{c.invalid} invalid/unrecognized reference(s)")
    if c.missing > result.allow_missing:
        result.blockers.append(
            f"{c.missing} missing source/destination file(s) "
            f"(allow_missing={result.allow_missing})"
        )
    elif c.missing:
        result.warnings.append(
            f"{c.missing} missing allowed by --allow-missing {result.allow_missing}"
        )

    if free_bytes is None:
        result.blockers.append("unable to determine free disk space for storage root")
    elif free_bytes < result.ready_bytes:
        result.blockers.append(
            f"insufficient disk space: free={free_bytes} < ready_bytes={result.ready_bytes}"
        )

    if require_backup and age_error is None:
        manifest_path = Path(backup_manifest or DEFAULT_BACKUP_MANIFEST)
        backup = verify_backup_manifest(
            manifest_path,
            current_target=target,
            now=now,
            max_backup_age_hours=age_hours if age_hours is not None else DEFAULT_MAX_BACKUP_AGE_HOURS,
            storage_root=store.root,
        )
        result.backup = backup
        if not backup.ok:
            result.blockers.append("backup manifest validation failed")
            result.blockers.extend(backup.errors)
            if backup.database_backup:
                result.blockers.extend(backup.database_backup.errors)
            if backup.legacy_backup:
                result.blockers.extend(backup.legacy_backup.errors)
    elif require_backup and age_error is not None:
        # Still attempt structural manifest load for diagnostics, but age gate already blocks.
        pass

    if require_confirm and not confirm_production:
        result.blockers.append("missing explicit --confirm-production")

    # Deduplicate blockers while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for b in result.blockers:
        if b and b not in seen:
            seen.add(b)
            unique.append(b)
    result.blockers = unique
    result.allowed = len(result.blockers) == 0
    return result


def write_journal(journal: ExecutionJournal, path: Path) -> Path:
    """Atomically persist journal JSON (temp file + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    journal.journal_path = str(path.resolve())
    payload = json.dumps(journal.to_dict(), ensure_ascii=False, indent=2) + "\n"

    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def default_journal_path(journal_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path(journal_dir) / f"storage_migration_{stamp}.json"


def _build_journal_from_gates(
    *,
    started: str,
    gates: GateEvaluation,
    backup_manifest: Optional[Path],
) -> ExecutionJournal:
    return ExecutionJournal(
        started_at=started,
        mode="execute",
        phase="started",
        executed=False,
        aborted=False,
        target=asdict(gates.target) if gates.target else {},
        target_id=gates.target.target_id if gates.target else "",
        backup_manifest={
            "path": gates.backup.path if gates.backup else str(backup_manifest or ""),
            "ok": bool(gates.backup and gates.backup.ok),
            "errors": list(gates.backup.errors) if gates.backup else [],
            "operator": gates.backup.operator if gates.backup else "",
            "created_at": gates.backup.created_at if gates.backup else "",
            "target": dict(gates.backup.target) if gates.backup else {},
        },
        dry_run_result={
            "overall": gates.dry_run.overall if gates.dry_run else "UNKNOWN",
            "db_changed": bool(gates.dry_run.db_changed) if gates.dry_run else True,
            "filesystem_changed": (
                bool(gates.dry_run.filesystem_changed) if gates.dry_run else True
            ),
            "activation": (
                _activation_to_summary(gates.activation_dry_run)
                if gates.activation_dry_run
                else {}
            ),
        },
        candidate_counts=asdict(gates.candidates),
        ready_bytes=gates.ready_bytes,
        free_bytes=gates.free_bytes,
        gates={
            "allowed": gates.allowed,
            "blockers": list(gates.blockers),
            "warnings": list(gates.warnings),
            "ready_bytes": gates.ready_bytes,
            "free_bytes": gates.free_bytes,
            "headroom_bytes": gates.headroom_bytes,
            "allow_missing": gates.allow_missing,
            "confirm_production": gates.confirm_production,
            "max_backup_age_hours": gates.max_backup_age_hours,
        },
        sources_deleted=False,
    )


def _apply_activation_results(
    journal: ExecutionJournal, activation_report: ActivationReport
) -> None:
    journal.copied = activation_report.count_status(MigrationStatus.COPIED)
    journal.already_migrated = activation_report.count_status(
        MigrationStatus.ALREADY_MIGRATED
    )
    journal.missing = activation_report.count_status(MigrationStatus.MISSING)
    journal.errors = activation_report.count_status(MigrationStatus.ERROR)
    journal.conflicts = sum(
        1
        for i in activation_report.items
        if i.status == MigrationStatus.ERROR
        and "destination exists with different content"
        in f"{i.error or ''} {i.message or ''}".lower()
    )
    journal.db_updated = activation_report.count_db_updated()
    journal.aborted = activation_report.aborted
    journal.abort_reason = activation_report.abort_reason
    journal.sources_deleted = False
    journal.phase = "aborted" if activation_report.aborted else "completed"
    journal.finished_at = _utc_now()


def run_controlled_execute(
    *,
    db: Session,
    storage: Optional[FileStorage] = None,
    activation: Optional[StorageActivationService] = None,
    backup_manifest: Optional[Path] = None,
    confirm_production: bool = False,
    allow_missing: int = 0,
    max_backup_age_hours: Any = DEFAULT_MAX_BACKUP_AGE_HOURS,
    legacy_roots: Optional[tuple[tuple[str, Path], ...]] = None,
    journal_path: Optional[Path] = None,
    journal_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> tuple[ExecutionJournal, Optional[ActivationReport]]:
    """Run gated production execute. Returns journal always; activation report if executed.

    Crash-safety: an initial durable journal (``phase=started``) is written
    **before** any ``execute(dry_run=False)`` filesystem/DB mutation.
    """
    started = _utc_now()
    store = storage or get_default_storage()
    service = activation or StorageActivationService(db, storage=store)

    gates = evaluate_execute_gates(
        db=db,
        storage=store,
        activation=service,
        backup_manifest=backup_manifest,
        confirm_production=confirm_production,
        allow_missing=allow_missing,
        max_backup_age_hours=max_backup_age_hours,
        legacy_roots=legacy_roots,
        require_backup=True,
        require_confirm=True,
        now=now,
    )

    journal = _build_journal_from_gates(
        started=started, gates=gates, backup_manifest=backup_manifest
    )
    out_path = journal_path or default_journal_path(journal_dir or DEFAULT_JOURNAL_DIR)

    # Durable initial journal BEFORE any mutation.
    write_journal(journal, out_path)

    if not gates.allowed:
        journal.phase = "blocked"
        journal.aborted = True
        journal.executed = False
        journal.abort_reason = "execute blocked by safety gates: " + "; ".join(
            gates.blockers
        )
        journal.finished_at = _utc_now()
        journal.sources_deleted = False
        write_journal(journal, out_path)
        return journal, None

    # Transition to executing, then mutate via ActivationService only.
    journal.phase = "executing"
    write_journal(journal, out_path)

    try:
        activation_report = service.execute(dry_run=False)
    except Exception as exc:  # noqa: BLE001
        journal.executed = True
        journal.aborted = True
        journal.phase = "aborted"
        journal.abort_reason = f"unhandled execute exception: {exc}"
        journal.sources_deleted = False
        journal.finished_at = _utc_now()
        write_journal(journal, out_path)
        return journal, None

    journal.executed = True
    _apply_activation_results(journal, activation_report)
    write_journal(journal, out_path)
    return journal, activation_report


def format_gate_report(gates: GateEvaluation) -> str:
    lines = [
        "Timex Unified Storage Production Migration Gates",
        "",
        "Target:",
    ]
    if gates.target:
        lines.append(f"  Database target: {gates.target.database}")
        lines.append(f"  Storage root: {gates.target.storage_root}")
        lines.append(f"  Environment: {gates.target.environment}")
        lines.append(f"  Target id: {gates.target.target_id}")
        lines.append(f"  Candidate count (ready): {gates.target.candidate_count}")
        lines.append(f"  Total ready bytes: {gates.target.total_ready_bytes}")
    else:
        lines.append("  (unavailable)")

    lines.extend(
        [
            "",
            "Disk:",
            f"  ready_bytes: {gates.ready_bytes}",
            f"  free_bytes: {gates.free_bytes if gates.free_bytes is not None else 'unknown'}",
            f"  headroom_bytes: {gates.headroom_bytes if gates.headroom_bytes is not None else 'unknown'}",
            "",
            "Candidates:",
            f"  ready: {gates.candidates.ready}",
            f"  already_unified: {gates.candidates.already_unified}",
            f"  destination_identical: {gates.candidates.destination_identical}",
            f"  missing: {gates.candidates.missing}",
            f"  conflicts: {gates.candidates.conflicts}",
            f"  invalid: {gates.candidates.invalid}",
            "",
            f"Backup manifest: {'OK' if gates.backup and gates.backup.ok else 'FAILED'}",
            f"Confirm production: {'YES' if gates.confirm_production else 'NO'}",
            f"Allow missing: {gates.allow_missing}",
            "",
            f"Overall: {'ALLOWED' if gates.allowed else 'BLOCKED'}",
        ]
    )
    if gates.blockers:
        lines.append("Blockers:")
        for b in gates.blockers:
            lines.append(f"  - {b}")
    if gates.warnings:
        lines.append("Warnings:")
        for w in gates.warnings:
            lines.append(f"  - {w}")
    lines.append("")
    lines.append("Source deletion: NEVER")
    return "\n".join(lines).rstrip() + "\n"


def format_execution_report(
    journal: ExecutionJournal, activation: Optional[ActivationReport] = None
) -> str:
    lines = [
        "Timex Unified Storage Production Migration Execution",
        "",
        f"Started: {journal.started_at}",
        f"Finished: {journal.finished_at}",
        f"Phase: {journal.phase}",
        f"Executed: {'YES' if journal.executed else 'NO'}",
        f"Aborted: {'YES' if journal.aborted else 'NO'}",
    ]
    if journal.abort_reason:
        lines.append(f"Abort reason: {journal.abort_reason}")
    if journal.target:
        lines.extend(
            [
                "",
                "Target:",
                f"  Database target: {journal.target.get('database')}",
                f"  Storage root: {journal.target.get('storage_root')}",
                f"  Environment: {journal.target.get('environment')}",
                f"  Target id: {journal.target.get('target_id')}",
                f"  Candidate count: {journal.target.get('candidate_count')}",
                f"  Total bytes: {journal.target.get('total_ready_bytes')}",
            ]
        )
    lines.extend(
        [
            "",
            "Results:",
            f"  copied: {journal.copied}",
            f"  already_migrated: {journal.already_migrated}",
            f"  missing: {journal.missing}",
            f"  conflicts: {journal.conflicts}",
            f"  errors: {journal.errors}",
            f"  db_updated: {journal.db_updated}",
            f"  sources_deleted: {'YES' if journal.sources_deleted else 'NO'}",
            f"  journal: {journal.journal_path}",
        ]
    )
    if activation is not None:
        lines.extend(["", "Activation summary:", activation.format_summary().rstrip()])
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m web.services.storage_production_migration",
        description=(
            "Controlled production migration for Unified Storage. "
            "--execute requires backup manifest verification, dry-run, "
            "hard Go/No-Go gates, and --confirm-production."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Evaluate execute gates without migrating (default if no mode given)",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Execute migration only if all safety gates pass",
    )
    parser.add_argument(
        "--backup-manifest",
        type=Path,
        default=DEFAULT_BACKUP_MANIFEST,
        help=f"Path to backup manifest JSON (default: {DEFAULT_BACKUP_MANIFEST})",
    )
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required explicit operator confirmation for --execute",
    )
    parser.add_argument(
        "--allow-missing",
        type=int,
        default=0,
        metavar="N",
        help="Allow up to N missing candidates (default: 0 = reject any missing)",
    )
    parser.add_argument(
        "--max-backup-age-hours",
        type=float,
        default=DEFAULT_MAX_BACKUP_AGE_HOURS,
        metavar="HOURS",
        help=(
            "Maximum age of backup manifest created_at "
            f"(default: {DEFAULT_MAX_BACKUP_AGE_HOURS:g} hours)"
        ),
    )
    parser.add_argument(
        "--journal-dir",
        type=Path,
        default=DEFAULT_JOURNAL_DIR,
        help="Directory for execution journal JSON files",
    )
    parser.add_argument(
        "--journal-out",
        type=Path,
        default=None,
        help="Explicit journal output path (optional)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write gate/execution summary JSON to this path",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    do_execute = bool(args.execute)

    from database.engine import SessionLocal

    db = SessionLocal()
    try:
        if do_execute:
            journal, activation = run_controlled_execute(
                db=db,
                backup_manifest=args.backup_manifest,
                confirm_production=bool(args.confirm_production),
                allow_missing=int(args.allow_missing),
                max_backup_age_hours=args.max_backup_age_hours,
                journal_path=args.journal_out,
                journal_dir=args.journal_dir,
            )
            print(format_execution_report(journal, activation))
            if args.json_out is not None:
                args.json_out.parent.mkdir(parents=True, exist_ok=True)
                args.json_out.write_text(
                    json.dumps(journal.to_dict(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"JSON report written: {args.json_out}")
            if not journal.executed:
                return 1
            return 1 if journal.aborted else 0

        # Gate evaluation / preflight mode (no execute).
        gates = evaluate_execute_gates(
            db=db,
            backup_manifest=args.backup_manifest,
            confirm_production=bool(args.confirm_production),
            allow_missing=int(args.allow_missing),
            max_backup_age_hours=args.max_backup_age_hours,
            require_backup=True,
            # Preflight mode: confirmation is informational, not required.
            require_confirm=False,
        )
        print(format_gate_report(gates))
        if gates.dry_run is not None:
            print(format_human_report(gates.dry_run))
        if args.json_out is not None:
            payload = {
                "mode": "preflight",
                "allowed": gates.allowed,
                "blockers": gates.blockers,
                "warnings": gates.warnings,
                "target": asdict(gates.target) if gates.target else None,
                "candidates": asdict(gates.candidates),
                "ready_bytes": gates.ready_bytes,
                "free_bytes": gates.free_bytes,
                "headroom_bytes": gates.headroom_bytes,
                "backup": asdict(gates.backup) if gates.backup else None,
            }
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"JSON report written: {args.json_out}")
        return 0 if gates.allowed else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
