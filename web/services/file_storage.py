"""Unified private file storage for Timex.

Logical storage keys (e.g. ``/private/contracts/<uuid>.pdf``) are stored in the
DB. Physical files live under ``TIMEX_STORAGE_ROOT`` (default: ``<project>/storage``),
outside the public ``/static`` mount.

Categories prepared for future use: contracts, employee-documents, education, avatars.
This module does not implement Employee Documents workflows.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4

WEB_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = WEB_ROOT.parent

# Legacy locations kept for resolve/delete compatibility (no migration in this phase).
LEGACY_PRIVATE_UPLOADS = WEB_ROOT / "private_uploads"
LEGACY_STATIC_ROOT = WEB_ROOT / "static"

CATEGORIES = (
    "contracts",
    "employee-documents",
    "education",
    "avatars",
)


@dataclass(frozen=True)
class CategoryConfig:
    name: str
    allowed_extensions: frozenset[str]
    max_file_size: int
    key_prefix: str


CATEGORY_CONFIGS: dict[str, CategoryConfig] = {
    "contracts": CategoryConfig(
        name="contracts",
        allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".pdf"}),
        max_file_size=10 * 1024 * 1024,
        key_prefix="/private/contracts/",
    ),
    "employee-documents": CategoryConfig(
        name="employee-documents",
        allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".pdf"}),
        max_file_size=10 * 1024 * 1024,
        key_prefix="/private/employee-documents/",
    ),
    "education": CategoryConfig(
        name="education",
        allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".pdf"}),
        max_file_size=5 * 1024 * 1024,
        key_prefix="/private/education/",
    ),
    "avatars": CategoryConfig(
        name="avatars",
        allowed_extensions=frozenset({".jpg", ".jpeg", ".png", ".webp"}),
        max_file_size=2 * 1024 * 1024,
        key_prefix="/private/avatars/",
    ),
}

_UUID_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]+$")


class FileStorageError(ValueError):
    """Validation / safety error for file storage operations."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def get_storage_root() -> Path:
    """Return configured storage root (preferably outside the source tree)."""
    configured = (os.getenv("TIMEX_STORAGE_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (PROJECT_ROOT / "storage").resolve()


def get_default_storage() -> "FileStorage":
    return FileStorage(root=get_storage_root())


class FileStorage:
    """Simple category-based private file storage."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root).resolve() if root is not None else get_storage_root()

    def category_dir(self, category: str) -> Path:
        cfg = self._config(category)
        return self.root / cfg.name

    def save(
        self,
        category: str,
        data: bytes,
        *,
        original_filename: str,
        allowed_extensions: Optional[Iterable[str]] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Validate and store ``data``; return a logical ``storage_key``."""
        cfg = self._config(category)
        if not original_filename:
            raise FileStorageError("invalid_filename", "filename is required")

        ext = Path(original_filename).suffix.lower()
        allowed = frozenset(
            e.lower() if e.startswith(".") else f".{e.lower()}"
            for e in (allowed_extensions if allowed_extensions is not None else cfg.allowed_extensions)
        )
        if ext not in allowed:
            raise FileStorageError("invalid_extension", f"extension not allowed: {ext or '(none)'}")

        if not data:
            raise FileStorageError("empty_file", "file is empty")

        limit = cfg.max_file_size if max_file_size is None else max_file_size
        if len(data) > limit:
            raise FileStorageError("file_too_large", f"file exceeds {limit} bytes")

        filename = f"{uuid4().hex}{ext}"
        dest_dir = self.category_dir(category)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self._safe_join(dest_dir, filename)
        dest.write_bytes(data)
        return f"{cfg.key_prefix}{filename}"

    def resolve(self, storage_key: str) -> Path:
        """Map a logical key to an absolute disk path (may not exist yet)."""
        normalized = self._normalize_key(storage_key)

        if normalized.startswith("/static/"):
            return self._resolve_legacy_static(normalized)

        category, filename = self._parse_private_key(normalized)
        preferred = self._safe_join(self.category_dir(category), filename)
        if preferred.is_file():
            return preferred

        for legacy in self._legacy_candidates(category, filename):
            if legacy.is_file():
                return legacy

        return preferred

    def exists(self, storage_key: str) -> bool:
        try:
            return self.resolve(storage_key).is_file()
        except (OSError, FileStorageError):
            return False

    def delete(self, storage_key: str) -> None:
        if not storage_key:
            return
        try:
            path = self.resolve(storage_key)
            if path.is_file():
                path.unlink()
        except (OSError, FileStorageError):
            pass

    def is_uuid_filename(self, filename: str) -> bool:
        return bool(_UUID_FILENAME_RE.match(filename or ""))

    def _config(self, category: str) -> CategoryConfig:
        if category not in CATEGORY_CONFIGS:
            raise FileStorageError("unknown_category", f"unknown category: {category}")
        return CATEGORY_CONFIGS[category]

    def _normalize_key(self, storage_key: str) -> str:
        normalized = (storage_key or "").replace("\\", "/").strip()
        if not normalized:
            raise FileStorageError("invalid_key", "storage key is empty")
        if "\x00" in normalized:
            raise FileStorageError("path_traversal", "NUL in storage key")
        parts = [p for p in normalized.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise FileStorageError("path_traversal", "path traversal rejected")
        return normalized

    def _parse_private_key(self, normalized: str) -> tuple[str, str]:
        for category, cfg in CATEGORY_CONFIGS.items():
            if normalized.startswith(cfg.key_prefix):
                rest = normalized[len(cfg.key_prefix) :]
                # Only a single filename component is allowed after the prefix.
                if not rest or "/" in rest or "\\" in rest or rest in {".", ".."}:
                    raise FileStorageError("path_traversal", "invalid storage key path")
                self._assert_safe_filename(rest)
                return category, rest

        # Legacy contract bare filename → contracts category.
        filename = Path(normalized).name
        if filename != normalized.lstrip("/") or not filename or filename in {".", ".."}:
            raise FileStorageError("invalid_key", "unrecognized storage key")
        self._assert_safe_filename(filename)
        return "contracts", filename

    def _resolve_legacy_static(self, normalized: str) -> Path:
        rel = normalized[len("/static/") :].lstrip("/")
        if not rel:
            raise FileStorageError("invalid_key", "empty static path")
        return self._safe_join(LEGACY_STATIC_ROOT, rel)

    def _legacy_candidates(self, category: str, filename: str) -> list[Path]:
        candidates: list[Path] = []
        if category == "contracts":
            candidates.append(self._safe_join(LEGACY_PRIVATE_UPLOADS / "contracts", filename))
            # Older public layout (still resolve for download/delete compatibility).
            candidates.append(self._safe_join(LEGACY_STATIC_ROOT / "uploads" / "contracts", filename))
        elif category == "education":
            candidates.append(self._safe_join(LEGACY_STATIC_ROOT / "uploads" / "certificates", filename))
        elif category == "avatars":
            candidates.append(self._safe_join(LEGACY_STATIC_ROOT / "uploads" / "avatars", filename))
        return candidates

    def _assert_safe_filename(self, filename: str) -> None:
        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise FileStorageError("path_traversal", "unsafe filename")
        if ".." in filename:
            raise FileStorageError("path_traversal", "unsafe filename")

    def _safe_join(self, base: Path, *parts: str) -> Path:
        base_resolved = base.resolve()
        candidate = base_resolved.joinpath(*parts).resolve()
        try:
            candidate.relative_to(base_resolved)
        except ValueError as exc:
            raise FileStorageError("path_traversal", "path escapes storage root") from exc
        return candidate
