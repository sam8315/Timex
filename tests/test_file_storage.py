"""Unit tests for unified private FileStorage."""
from pathlib import Path

import pytest

from web.services.file_storage import (
    CATEGORY_CONFIGS,
    FileStorage,
    FileStorageError,
    LEGACY_PRIVATE_UPLOADS,
    LEGACY_STATIC_ROOT,
)
from web.services.contract_file_storage import (
    PRIVATE_PATH_PREFIX,
    resolve_contract_file_disk,
    save_contract_file,
)


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(root=tmp_path / "timex_storage")


def test_save_success(storage: FileStorage):
    key = storage.save("contracts", b"%PDF-1.4\ndata", original_filename="c.pdf")
    assert key.startswith("/private/contracts/")
    assert key.endswith(".pdf")
    filename = Path(key).name
    assert storage.is_uuid_filename(filename)
    disk = storage.resolve(key)
    assert disk.is_file()
    assert disk.read_bytes().startswith(b"%PDF")
    assert disk.parent == storage.category_dir("contracts")


def test_resolve_success(storage: FileStorage):
    key = storage.save("education", b"cert", original_filename="x.png")
    path = storage.resolve(key)
    assert path.is_file()
    assert path.suffix == ".png"


def test_exists_and_delete(storage: FileStorage):
    key = storage.save("avatars", b"img", original_filename="a.jpg")
    assert storage.exists(key) is True
    storage.delete(key)
    assert storage.exists(key) is False
    # delete is idempotent
    storage.delete(key)


def test_invalid_extension(storage: FileStorage):
    with pytest.raises(FileStorageError) as exc:
        storage.save("contracts", b"MZ", original_filename="evil.exe")
    assert exc.value.code == "invalid_extension"


def test_file_size_over_limit(storage: FileStorage):
    limit = CATEGORY_CONFIGS["contracts"].max_file_size
    with pytest.raises(FileStorageError) as exc:
        storage.save(
            "contracts",
            b"x" * (limit + 1),
            original_filename="big.pdf",
        )
    assert exc.value.code == "file_too_large"


def test_path_traversal_rejected(storage: FileStorage):
    with pytest.raises(FileStorageError) as exc:
        storage.resolve("/private/contracts/../../etc/passwd")
    assert exc.value.code == "path_traversal"

    with pytest.raises(FileStorageError):
        storage.resolve("/private/contracts/foo/../bar.pdf")

    with pytest.raises(FileStorageError):
        storage.resolve("/static/uploads/../../../etc/passwd")


def test_uuid_filename_is_secure(storage: FileStorage):
    key = storage.save("contracts", b"ok", original_filename="My Contract (1).PDF")
    name = Path(key).name
    assert storage.is_uuid_filename(name)
    assert " " not in name
    assert "(" not in name
    assert name.endswith(".pdf")


def test_contract_legacy_private_uploads_compatibility(storage: FileStorage, monkeypatch):
    """Existing files under web/private_uploads/contracts must still resolve."""
    filename = "a" * 32 + ".pdf"
    legacy_dir = LEGACY_PRIVATE_UPLOADS / "contracts"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / filename
    legacy_file.write_bytes(b"%PDF-legacy-private")

    try:
        key = f"{PRIVATE_PATH_PREFIX}{filename}"
        # Point contract adapter at this storage instance via env root... 
        # resolve on FileStorage directly:
        resolved = storage.resolve(key)
        assert resolved == legacy_file.resolve()
        assert storage.exists(key)

        # contract adapter uses process-wide default storage; also verify
        # resolve_contract_file_disk against the same key when root has no copy.
        monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(storage.root))
        disk = resolve_contract_file_disk(key)
        assert disk.is_file()
        assert disk.read_bytes() == b"%PDF-legacy-private"
    finally:
        if legacy_file.exists():
            legacy_file.unlink()


def test_contract_legacy_static_path_compatibility(storage: FileStorage):
    filename = "b" * 32 + ".pdf"
    legacy_dir = LEGACY_STATIC_ROOT / "uploads" / "contracts"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = legacy_dir / filename
    legacy_file.write_bytes(b"%PDF-legacy-static")

    try:
        key = f"/static/uploads/contracts/{filename}"
        resolved = storage.resolve(key)
        assert resolved == legacy_file.resolve()
        assert storage.exists(key)
    finally:
        if legacy_file.exists():
            legacy_file.unlink()


def test_new_contract_files_not_under_static(storage: FileStorage):
    key = storage.save("contracts", b"%PDF-new", original_filename="n.pdf")
    disk = storage.resolve(key)
    assert "static" not in disk.parts
    assert key.startswith(PRIVATE_PATH_PREFIX)
    assert "/static/" not in key


def test_save_contract_file_adapter(tmp_path: Path, monkeypatch):
    import asyncio
    from io import BytesIO
    from fastapi import UploadFile

    root = tmp_path / "root"
    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(root))

    upload = UploadFile(filename="contract.pdf", file=BytesIO(b"%PDF-adapter"))
    key = asyncio.run(save_contract_file(upload))
    assert key.startswith(PRIVATE_PATH_PREFIX)
    disk = resolve_contract_file_disk(key)
    assert disk.is_file()
    assert disk.read_bytes() == b"%PDF-adapter"
    assert disk.parent == root.resolve() / "contracts"
