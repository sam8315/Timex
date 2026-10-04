"""Read-only / dry-run production readiness tooling for Unified Storage.

This module NEVER executes a real migration:
- no ``dry_run=False``
- no ``--execute``
- no DB writes
- no permanent filesystem writes (writable probe uses a temp file that is deleted)

Usage::

    python -m web.services.storage_production_preflight
    python -m web.services.storage_production_preflight --dry-run
    python -m web.services.storage_production_preflight --dry-run --json-out report.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.contract import Contract
from models.education import Education
from models.employee import Employee
from web.services.file_storage import (
    PROJECT_ROOT,
    WEB_ROOT,
    FileStorage,
    get_default_storage,
    get_storage_root,
)
from web.services.storage_activation import (
    ActivationReport,
    StorageActivationService,
    is_unified_storage_key,
)
from web.services.storage_migration import MigrationStatus


STORAGE_SUBDIRS = ("contracts", "education", "avatars", "employee-documents")

LEGACY_ROOT_SPECS: tuple[tuple[str, Path], ...] = (
    ("contracts_static", WEB_ROOT / "static" / "uploads" / "contracts"),
    ("education", WEB_ROOT / "static" / "uploads" / "certificates"),
    ("avatars", WEB_ROOT / "static" / "uploads" / "avatars"),
    ("contracts_private", WEB_ROOT / "private_uploads" / "contracts"),
)


@dataclass
class StorageRootReport:
    env_value: str
    path: str
    exists: bool
    is_directory: bool
    accessible: bool
    writable: bool
    free_bytes: Optional[int]
    free_human: str
    outside_source_tree: bool
    subdirectories: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class LegacyRootReport:
    name: str
    path: str
    exists: bool
    file_count: int
    total_bytes: int
    total_human: str


@dataclass
class FieldPathCounts:
    total_rows: int
    empty_or_null: int
    with_path: int


@dataclass
class CandidateCounts:
    ready: int = 0
    already_unified: int = 0
    destination_identical: int = 0
    missing: int = 0
    conflicts: int = 0
    invalid: int = 0
    skipped: int = 0
    legacy: int = 0
    total_scanned: int = 0


@dataclass
class ProductionPreflightReport:
    generated_at: str
    mode: str  # "preflight" | "dry_run"
    overall: str  # "READY" | "NOT READY"
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    storage: Optional[StorageRootReport] = None
    database: dict[str, Any] = field(default_factory=dict)
    candidates: CandidateCounts = field(default_factory=CandidateCounts)
    legacy_roots: list[LegacyRootReport] = field(default_factory=list)
    activation_summary: dict[str, Any] = field(default_factory=dict)
    db_error: str = ""
    filesystem_changed: bool = False
    db_changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "mode": self.mode,
            "overall": self.overall,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "storage": asdict(self.storage) if self.storage else None,
            "database": self.database,
            "candidates": asdict(self.candidates),
            "legacy_roots": [asdict(r) for r in self.legacy_roots],
            "activation_summary": self.activation_summary,
            "db_error": self.db_error,
            "filesystem_changed": self.filesystem_changed,
            "db_changed": self.db_changed,
        }


def _human_bytes(num: Optional[int]) -> str:
    if num is None:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num} B"


def inspect_storage_root(root: Optional[Path] = None) -> StorageRootReport:
    """Inspect TIMEX_STORAGE_ROOT (or provided root) without permanent writes."""
    env_value = (os.getenv("TIMEX_STORAGE_ROOT") or "").strip()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        resolved = Path(root).resolve() if root is not None else get_storage_root()
    except Exception as exc:  # noqa: BLE001
        return StorageRootReport(
            env_value=env_value or "(unset → default <project>/storage)",
            path="",
            exists=False,
            is_directory=False,
            accessible=False,
            writable=False,
            free_bytes=None,
            free_human="unknown",
            outside_source_tree=False,
            errors=[f"invalid storage root: {exc}"],
        )

    exists = resolved.exists()
    is_directory = resolved.is_dir() if exists else False
    accessible = False
    writable = False
    free_bytes: Optional[int] = None

    if not exists:
        errors.append(f"storage root does not exist: {resolved}")
    elif not is_directory:
        errors.append(f"storage root is not a directory: {resolved}")
    else:
        try:
            next(resolved.iterdir(), None)
            accessible = True
        except OSError as exc:
            errors.append(f"storage root not accessible: {exc}")

        if accessible:
            try:
                # Temporary probe file — deleted immediately (no permanent write).
                fd, probe_name = tempfile.mkstemp(prefix=".timex_preflight_", dir=str(resolved))
                try:
                    os.write(fd, b"ok")
                finally:
                    os.close(fd)
                    Path(probe_name).unlink(missing_ok=True)
                writable = True
            except OSError as exc:
                writable = False
                errors.append(f"storage root not writable: {exc}")

            try:
                free_bytes = shutil.disk_usage(resolved).free
            except OSError as exc:
                warnings.append(f"could not read free disk space: {exc}")

    outside = True
    try:
        project = PROJECT_ROOT.resolve()
        outside = project not in resolved.parents and resolved != project
    except OSError:
        outside = False
    if exists and is_directory and not outside:
        warnings.append(
            f"storage root is inside the source tree ({PROJECT_ROOT}); "
            "prefer a path outside the repository"
        )

    subdirs: dict[str, bool] = {}
    for name in STORAGE_SUBDIRS:
        sub = resolved / name
        present = sub.is_dir()
        subdirs[name] = present
        if exists and is_directory and not present:
            # employee-documents is reported only; others are expected for migration.
            if name == "employee-documents":
                warnings.append(
                    "subdirectory employee-documents missing (reported only; not migrated)"
                )
            else:
                warnings.append(f"subdirectory missing (will be created on first save): {name}")

    if not env_value:
        warnings.append("TIMEX_STORAGE_ROOT unset; using default <project>/storage")

    return StorageRootReport(
        env_value=env_value or "(unset → default <project>/storage)",
        path=str(resolved),
        exists=exists,
        is_directory=is_directory,
        accessible=accessible,
        writable=writable,
        free_bytes=free_bytes,
        free_human=_human_bytes(free_bytes),
        outside_source_tree=outside,
        subdirectories=subdirs,
        errors=errors,
        warnings=warnings,
    )


def _count_files_and_size(directory: Path) -> tuple[int, int]:
    if not directory.is_dir():
        return 0, 0
    count = 0
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            count += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return count, total


def inspect_legacy_roots(
    roots: Optional[tuple[tuple[str, Path], ...]] = None,
) -> list[LegacyRootReport]:
    """Read-only inventory of legacy upload directories."""
    reports: list[LegacyRootReport] = []
    for name, path in roots or LEGACY_ROOT_SPECS:
        resolved = Path(path)
        exists = resolved.is_dir()
        file_count, total_bytes = _count_files_and_size(resolved) if exists else (0, 0)
        reports.append(
            LegacyRootReport(
                name=name,
                path=str(resolved.resolve()) if exists or resolved.exists() else str(resolved),
                exists=exists,
                file_count=file_count,
                total_bytes=total_bytes,
                total_human=_human_bytes(total_bytes),
            )
        )
    return reports


def _empty_or_null_filter(column):
    return or_(column.is_(None), column == "")


def query_path_field_counts(db: Session) -> dict[str, FieldPathCounts]:
    """Count empty/NULL vs populated path fields (read-only)."""
    out: dict[str, FieldPathCounts] = {}

    specs = (
        ("contracts", Contract, Contract.file_path),
        ("education", Education, Education.certificate_path),
        ("avatars", Employee, Employee.photo_path),
    )
    for name, model, column in specs:
        total = db.query(func.count()).select_from(model).scalar() or 0
        empty = (
            db.query(func.count()).select_from(model).filter(_empty_or_null_filter(column)).scalar()
            or 0
        )
        out[name] = FieldPathCounts(
            total_rows=int(total),
            empty_or_null=int(empty),
            with_path=int(total) - int(empty),
        )
    return out


def classify_activation_items(report: ActivationReport) -> CandidateCounts:
    """Summarize ActivationReport without duplicating preflight logic."""
    counts = CandidateCounts(total_scanned=len(report.items))
    for item in report.items:
        unified = is_unified_storage_key(item.legacy_key)
        if not unified:
            counts.legacy += 1

        if item.status == MigrationStatus.PENDING:
            counts.ready += 1
        elif item.status == MigrationStatus.MISSING:
            counts.missing += 1
        elif item.status == MigrationStatus.SKIPPED:
            counts.skipped += 1
            counts.invalid += 1
        elif item.status == MigrationStatus.ALREADY_MIGRATED:
            if "identical content" in (item.message or ""):
                counts.destination_identical += 1
            else:
                counts.already_unified += 1
        elif item.status == MigrationStatus.ERROR:
            err = f"{item.error or ''} {item.message or ''}".lower()
            if "destination exists with different content" in err:
                counts.conflicts += 1
            else:
                counts.invalid += 1
    return counts


def run_production_preflight(
    *,
    db: Session,
    storage: Optional[FileStorage] = None,
    activation: Optional[StorageActivationService] = None,
    dry_run: bool = False,
    legacy_roots: Optional[tuple[tuple[str, Path], ...]] = None,
    storage_root: Optional[Path] = None,
) -> ProductionPreflightReport:
    """Build a read-only (or dry-run) production readiness report.

    Always uses ``StorageActivationService`` for migration candidate classification.
    When ``dry_run=True``, calls ``execute(dry_run=True)`` (never False).
    """
    report = ProductionPreflightReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode="dry_run" if dry_run else "preflight",
        overall="NOT READY",
    )

    store = storage or get_default_storage()
    if storage_root is not None:
        storage_report = inspect_storage_root(storage_root)
    else:
        storage_report = inspect_storage_root(store.root)
    report.storage = storage_report
    report.warnings.extend(storage_report.warnings)
    report.blockers.extend(storage_report.errors)

    report.legacy_roots = inspect_legacy_roots(legacy_roots)

    service = activation or StorageActivationService(db, storage=store)

    try:
        field_counts = query_path_field_counts(db)
        report.database = {
            name: asdict(counts) for name, counts in field_counts.items()
        }

        if dry_run:
            activation_report = service.execute(dry_run=True)
        else:
            activation_report = service.preflight()

        report.candidates = classify_activation_items(activation_report)
        report.activation_summary = {
            "dry_run": activation_report.dry_run,
            "aborted": activation_report.aborted,
            "abort_reason": activation_report.abort_reason,
            "pending": activation_report.count_status(MigrationStatus.PENDING),
            "already_migrated": activation_report.count_status(MigrationStatus.ALREADY_MIGRATED),
            "missing": activation_report.count_status(MigrationStatus.MISSING),
            "errors": activation_report.count_status(MigrationStatus.ERROR),
            "skipped": activation_report.count_status(MigrationStatus.SKIPPED),
            "db_updated": activation_report.count_db_updated(),
            "human": activation_report.format_summary(),
        }
        # Hard guarantee for this phase.
        report.db_changed = activation_report.count_db_updated() > 0
        if report.db_changed:
            report.blockers.append("unexpected DB updates during read-only/dry-run preflight")
        if activation_report.aborted and activation_report.count_status(MigrationStatus.ERROR):
            # aborted on preflight errors is expected; still a readiness blocker via conflicts/invalid
            pass
    except Exception as exc:  # noqa: BLE001
        report.db_error = str(exc)
        report.blockers.append(f"database read/preflight failed: {exc}")

    c = report.candidates
    if c.conflicts:
        report.blockers.append(f"{c.conflicts} destination conflict(s)")
    if c.invalid:
        report.blockers.append(f"{c.invalid} invalid/unrecognized reference(s)")
    if c.missing:
        report.warnings.append(
            f"{c.missing} missing source/destination file(s) — review before execute phase"
        )

    report.overall = "READY" if not report.blockers else "NOT READY"
    # Explicit invariants for this tooling phase.
    report.filesystem_changed = False
    return report


def format_human_report(report: ProductionPreflightReport) -> str:
    lines: list[str] = [
        "Timex Unified Storage Production Preflight",
        "",
        f"Mode: {report.mode}",
        f"Generated: {report.generated_at}",
        "",
        "Storage Root:",
    ]
    s = report.storage
    if s is None:
        lines.append("  (unavailable)")
    else:
        lines.append(f"  env: {s.env_value}")
        lines.append(f"  path: {s.path}")
        lines.append(f"  exists: {'YES' if s.exists else 'NO'}")
        lines.append(f"  directory: {'YES' if s.is_directory else 'NO'}")
        lines.append(f"  accessible: {'YES' if s.accessible else 'NO'}")
        lines.append(f"  writable: {'YES' if s.writable else 'NO'}")
        lines.append(f"  free_space: {s.free_human}")
        lines.append(f"  outside_source_tree: {'YES' if s.outside_source_tree else 'NO'}")
        lines.append("  subdirectories:")
        for name in STORAGE_SUBDIRS:
            present = s.subdirectories.get(name, False)
            note = " (report only)" if name == "employee-documents" else ""
            lines.append(f"    {name}: {'YES' if present else 'NO'}{note}")

    lines.extend(["", "Database:"])
    if report.db_error and not report.database:
        lines.append(f"  ERROR: {report.db_error}")
    else:
        for name in ("contracts", "education", "avatars"):
            row = report.database.get(name) or {}
            lines.append(
                f"  {name}: total={row.get('total_rows', 0)} "
                f"empty_null={row.get('empty_or_null', 0)} "
                f"with_path={row.get('with_path', 0)}"
            )

    c = report.candidates
    lines.extend(
        [
            "",
            "Migration candidates:",
            f"  ready: {c.ready}",
            f"  already_unified: {c.already_unified}",
            f"  destination_identical: {c.destination_identical}",
            f"  missing: {c.missing}",
            f"  conflicts: {c.conflicts}",
            f"  invalid: {c.invalid}",
            f"  skipped: {c.skipped}",
            f"  legacy_keys: {c.legacy}",
            f"  total_scanned: {c.total_scanned}",
        ]
    )

    lines.extend(["", "Legacy roots:"])
    for root in report.legacy_roots:
        lines.append(
            f"  {root.name}: exists={'YES' if root.exists else 'NO'} "
            f"files={root.file_count} size={root.total_human}"
        )
        lines.append(f"    path: {root.path}")

    lines.extend(["", f"Overall: {report.overall}"])
    if report.blockers:
        lines.append("Blockers:")
        for b in report.blockers:
            lines.append(f"  - {b}")
    if report.warnings:
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")

    lines.extend(
        [
            "",
            "Safety:",
            f"  db_changed: {'YES' if report.db_changed else 'NO'}",
            f"  filesystem_changed: {'YES' if report.filesystem_changed else 'NO'}",
            "  production execute: use python -m web.services.storage_production_migration",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m web.services.storage_production_preflight",
        description=(
            "Read-only / dry-run production readiness check for Unified Storage. "
            "Does not migrate files or update the database."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run StorageActivationService.execute(dry_run=True) and include the report",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write machine-readable JSON report to this path",
    )
    # Intentionally unsupported — reject explicitly if present.
    parser.add_argument(
        "--execute",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if getattr(args, "execute", False):
        print(
            "ERROR: --execute is not available in this phase. "
            "Only read-only preflight and --dry-run are supported.",
            file=sys.stderr,
        )
        return 2

    from database.engine import SessionLocal

    db = SessionLocal()
    try:
        report = run_production_preflight(db=db, dry_run=bool(args.dry_run))
    finally:
        db.close()

    text = format_human_report(report)
    print(text)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON report written: {args.json_out}")

    return 0 if report.overall == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
