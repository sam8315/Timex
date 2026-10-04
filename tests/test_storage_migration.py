"""Tests for legacy → Unified Storage migration preparation (dry-run first)."""
from pathlib import Path

import pytest

from web.services.file_storage import FileStorage
from web.services.storage_migration import (
    LegacySourceRoot,
    MigrationStatus,
    StorageMigrationService,
    build_destination_key,
    category_for_legacy_key,
    run_dry_run_report,
)


@pytest.fixture
def legacy_layout(tmp_path: Path):
    contracts_private = tmp_path / "private_uploads" / "contracts"
    contracts_static = tmp_path / "static" / "uploads" / "contracts"
    education = tmp_path / "static" / "uploads" / "certificates"
    avatars = tmp_path / "static" / "uploads" / "avatars"
    for d in (contracts_private, contracts_static, education, avatars):
        d.mkdir(parents=True)

    (contracts_private / "old-contract.pdf").write_bytes(b"%PDF-contract-private")
    (contracts_static / "static-contract.pdf").write_bytes(b"%PDF-contract-static")
    (education / "degree.pdf").write_bytes(b"%PDF-education")
    (avatars / "face.jpg").write_bytes(b"jpeg-bytes")
    (avatars / ".gitkeep").write_text("", encoding="utf-8")

    roots = [
        LegacySourceRoot("contracts", contracts_private, "/private/contracts/"),
        LegacySourceRoot("contracts", contracts_static, "/static/uploads/contracts/"),
        LegacySourceRoot("education", education, "/static/uploads/certificates/"),
        LegacySourceRoot("avatars", avatars, "/static/uploads/avatars/"),
    ]
    storage = FileStorage(root=tmp_path / "unified_storage")
    service = StorageMigrationService(storage=storage, legacy_roots=roots)
    return {
        "tmp": tmp_path,
        "roots": roots,
        "storage": storage,
        "service": service,
        "contracts_private": contracts_private,
        "education": education,
        "avatars": avatars,
    }


def test_category_mapping():
    assert category_for_legacy_key("/static/uploads/contracts/a.pdf") == "contracts"
    assert category_for_legacy_key("/private/contracts/a.pdf") == "contracts"
    assert category_for_legacy_key("/static/uploads/certificates/a.pdf") == "education"
    assert category_for_legacy_key("/static/uploads/avatars/a.jpg") == "avatars"
    assert category_for_legacy_key("/private/education/a.pdf") == "education"
    assert category_for_legacy_key("/private/avatars/a.jpg") == "avatars"
    assert category_for_legacy_key("bare-file.pdf") == "contracts"
    assert category_for_legacy_key("/static/js/app.js") is None


def test_uuid_destination_not_legacy_filename(legacy_layout):
    source = legacy_layout["education"] / "degree.pdf"
    key = build_destination_key("education", source)
    assert key.startswith("/private/education/")
    name = Path(key).name
    assert name != "degree.pdf"
    assert legacy_layout["storage"].is_uuid_filename(name)
    # deterministic
    assert build_destination_key("education", source) == key


def test_dry_run_summary(legacy_layout):
    report = legacy_layout["service"].dry_run()
    assert report.dry_run is True
    summary = report.format_summary()
    assert "contracts: 2 files" in summary
    assert "education: 1 files" in summary
    assert "avatars: 1 files" in summary
    assert "missing: 0" in summary
    assert "already migrated: 0" in summary
    assert "errors: 0" in summary
    assert "pending: 4" in summary

    # dry-run must not create destinations or remove sources
    assert not (legacy_layout["tmp"] / "unified_storage").exists() or not any(
        (legacy_layout["tmp"] / "unified_storage").rglob("*")
        if (legacy_layout["tmp"] / "unified_storage").exists()
        else []
    )
    assert (legacy_layout["education"] / "degree.pdf").is_file()
    assert (legacy_layout["contracts_private"] / "old-contract.pdf").is_file()


def test_run_dry_run_report_helper(legacy_layout):
    text = run_dry_run_report(
        storage=legacy_layout["storage"],
        legacy_roots=legacy_layout["roots"],
    )
    assert "contracts: 2 files" in text
    assert "education: 1 files" in text
    assert "avatars: 1 files" in text


def test_missing_source(legacy_layout):
    report = legacy_layout["service"].dry_run(
        extra_legacy_keys=["/static/uploads/certificates/missing.pdf"]
    )
    missing = [i for i in report.items if i.status == MigrationStatus.MISSING]
    assert missing
    assert any("missing.pdf" in i.legacy_key for i in missing)
    assert report.count_status(MigrationStatus.MISSING) >= 1


def test_destination_already_exists_same_content(legacy_layout):
    service = legacy_layout["service"]
    source = legacy_layout["education"] / "degree.pdf"
    dest_key = build_destination_key("education", source)
    dest_path = legacy_layout["storage"].resolve(dest_key)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(source.read_bytes())

    report = service.dry_run()
    edu = [i for i in report.items if i.legacy_key.endswith("degree.pdf")][0]
    assert edu.status == MigrationStatus.ALREADY_MIGRATED
    assert "identical" in edu.message


def test_destination_already_exists_different_content_no_overwrite(legacy_layout):
    service = legacy_layout["service"]
    source = legacy_layout["education"] / "degree.pdf"
    dest_key = build_destination_key("education", source)
    dest_path = legacy_layout["storage"].resolve(dest_key)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(b"%PDF-OTHER-CONTENT")

    report = service.dry_run()
    edu = [i for i in report.items if i.legacy_key.endswith("degree.pdf")][0]
    assert edu.status == MigrationStatus.ERROR
    assert "refusing overwrite" in edu.message
    # source untouched
    assert source.read_bytes() == b"%PDF-education"
    assert dest_path.read_bytes() == b"%PDF-OTHER-CONTENT"


def test_no_source_deletion_during_preparation(legacy_layout):
    service = legacy_layout["service"]
    sources = [
        legacy_layout["contracts_private"] / "old-contract.pdf",
        legacy_layout["education"] / "degree.pdf",
        legacy_layout["avatars"] / "face.jpg",
    ]
    before = {p: p.read_bytes() for p in sources}

    # dry-run
    service.dry_run()
    for p, data in before.items():
        assert p.is_file()
        assert p.read_bytes() == data

    # optional copy execute still keeps sources
    report = service.execute(dry_run=False)
    assert report.dry_run is False
    assert report.count_status(MigrationStatus.COPIED) == 4
    for p, data in before.items():
        assert p.is_file()
        assert p.read_bytes() == data


def test_idempotent_execute(legacy_layout):
    service = legacy_layout["service"]
    first = service.execute(dry_run=False)
    assert first.count_status(MigrationStatus.COPIED) == 4

    second = service.execute(dry_run=False)
    assert second.count_status(MigrationStatus.COPIED) == 0
    assert second.count_status(MigrationStatus.ALREADY_MIGRATED) == 4
    assert second.count_status(MigrationStatus.ERROR) == 0

    # no duplicate files beyond the 4 destinations
    stored = list((legacy_layout["tmp"] / "unified_storage").rglob("*.*"))
    assert len(stored) == 4


def test_legacy_paths_still_resolvable_via_file_storage(legacy_layout):
    """Compatibility layer must keep resolving legacy keys (no removal)."""
    storage = legacy_layout["storage"]
    # Place a legacy-style file using real LEGACY paths? Use isolated FileStorage
    # resolve against the service's storage + monkeypatched isn't needed —
    # verify planner preserves legacy_key prefixes that FileStorage understands.
    report = legacy_layout["service"].dry_run()
    keys = {i.legacy_key for i in report.items if i.status == MigrationStatus.PENDING}
    assert any(k.startswith("/private/contracts/") for k in keys)
    assert any(k.startswith("/static/uploads/contracts/") for k in keys)
    assert any(k.startswith("/static/uploads/certificates/") for k in keys)
    assert any(k.startswith("/static/uploads/avatars/") for k in keys)

    # Unified FileStorage still resolves static legacy prefixes on real web tree
    from web.services.file_storage import LEGACY_STATIC_UPLOAD_PREFIXES

    assert "/static/uploads/contracts/" in LEGACY_STATIC_UPLOAD_PREFIXES
    assert "/static/uploads/certificates/" in LEGACY_STATIC_UPLOAD_PREFIXES
    assert "/static/uploads/avatars/" in LEGACY_STATIC_UPLOAD_PREFIXES

    # Destination keys use private prefixes
    for item in report.items:
        if item.status == MigrationStatus.PENDING:
            assert item.destination_key.startswith("/private/")
            assert storage.is_uuid_filename(Path(item.destination_key).name)


def test_dry_run_default_execute_is_safe(legacy_layout):
    report = legacy_layout["service"].execute()  # dry_run defaults True
    assert report.dry_run is True
    assert report.count_status(MigrationStatus.COPIED) == 0
    assert not list((legacy_layout["tmp"] / "unified_storage").rglob("*"))
