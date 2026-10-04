"""Read-only / dry-run production preflight tooling tests (no real production)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.contract import Contract
from models.education import Education
from models.employee import Employee
from web.services.file_storage import FileStorage
from web.services.storage_activation import StorageActivationService
from web.services.storage_migration import (
    LegacySourceRoot,
    MigrationStatus,
    StorageMigrationService,
    build_destination_key,
)
from web.services.storage_production_preflight import (
    classify_activation_items,
    format_human_report,
    inspect_legacy_roots,
    inspect_storage_root,
    main,
    run_production_preflight,
)


@pytest.fixture
def preflight_env(tmp_path, monkeypatch, db):
    contracts_static = tmp_path / "static" / "uploads" / "contracts"
    contracts_private = tmp_path / "private_uploads" / "contracts"
    education_dir = tmp_path / "static" / "uploads" / "certificates"
    avatars_dir = tmp_path / "static" / "uploads" / "avatars"
    for d in (contracts_static, contracts_private, education_dir, avatars_dir):
        d.mkdir(parents=True)

    storage_root = tmp_path / "unified_storage"
    storage_root.mkdir()
    for name in ("contracts", "education", "avatars", "employee-documents"):
        (storage_root / name).mkdir()

    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(storage_root))
    storage = FileStorage(root=storage_root)
    roots = [
        LegacySourceRoot("contracts", contracts_private, "/private/contracts/"),
        LegacySourceRoot("contracts", contracts_static, "/static/uploads/contracts/"),
        LegacySourceRoot("education", education_dir, "/static/uploads/certificates/"),
        LegacySourceRoot("avatars", avatars_dir, "/static/uploads/avatars/"),
    ]
    migration = StorageMigrationService(storage=storage, legacy_roots=roots)
    service = StorageActivationService(db, storage=storage, migration=migration)
    legacy_specs = (
        ("contracts_static", contracts_static),
        ("education", education_dir),
        ("avatars", avatars_dir),
        ("contracts_private", contracts_private),
    )
    return {
        "tmp": tmp_path,
        "storage": storage,
        "storage_root": storage_root,
        "service": service,
        "contracts_static": contracts_static,
        "education_dir": education_dir,
        "avatars_dir": avatars_dir,
        "legacy_specs": legacy_specs,
        "db": db,
    }


def _seed_legacy(env, user_id: str) -> dict[str, str]:
    c_name = f"{user_id}-contract.pdf"
    e_name = f"{user_id}-degree.pdf"
    a_name = f"{user_id}-face.jpg"
    (env["contracts_static"] / c_name).write_bytes(b"%PDF-contract-legacy")
    (env["education_dir"] / e_name).write_bytes(b"%PDF-education-legacy")
    (env["avatars_dir"] / a_name).write_bytes(b"jpeg-avatar-legacy")
    return {
        "contract": f"/static/uploads/contracts/{c_name}",
        "education": f"/static/uploads/certificates/{e_name}",
        "avatar": f"/static/uploads/avatars/{a_name}",
    }


def test_missing_storage_root(tmp_path):
    missing = tmp_path / "does-not-exist"
    report = inspect_storage_root(missing)
    assert report.exists is False
    assert report.writable is False
    assert any("does not exist" in e for e in report.errors)


def test_invalid_storage_root_file(tmp_path):
    file_path = tmp_path / "not-a-dir"
    file_path.write_text("x", encoding="utf-8")
    report = inspect_storage_root(file_path)
    assert report.exists is True
    assert report.is_directory is False
    assert any("not a directory" in e for e in report.errors)


def test_db_connection_read_failure(preflight_env):
    class BrokenSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("db down")

    report = run_production_preflight(
        db=BrokenSession(),  # type: ignore[arg-type]
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=False,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    assert report.overall == "NOT READY"
    assert report.db_error
    assert any("database" in b.lower() for b in report.blockers)


def test_counts_are_reported(preflight_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = preflight_env["db"]
    paths = _seed_legacy(preflight_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    edu = Education(
        user_id=user["user_id"],
        education_group="TECH",
        degree_level="BACHELOR",
        major="Net",
        graduation_date=__import__("datetime").date(2018, 1, 1),
        certificate_path=paths["education"],
        certificate_type="pdf",
    )
    db.add(edu)
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    emp.photo_path = paths["avatar"]
    db.commit()

    report = run_production_preflight(
        db=db,
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=False,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    assert report.database["contracts"]["with_path"] >= 1
    assert report.database["education"]["with_path"] >= 1
    assert report.database["avatars"]["with_path"] >= 1
    assert report.candidates.ready >= 3
    assert report.candidates.total_scanned >= 3
    text = format_human_report(report)
    assert "Migration candidates:" in text
    assert "Database:" in text


def test_legacy_roots_reported(preflight_env):
    (preflight_env["contracts_static"] / "a.pdf").write_bytes(b"%PDF-a")
    (preflight_env["education_dir"] / "b.pdf").write_bytes(b"%PDF-b")
    reports = inspect_legacy_roots(preflight_env["legacy_specs"])
    by_name = {r.name: r for r in reports}
    assert by_name["contracts_static"].exists is True
    assert by_name["contracts_static"].file_count >= 1
    assert by_name["education"].file_count >= 1
    assert by_name["avatars"].exists is True


def test_dry_run_causes_zero_db_and_fs_changes(preflight_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = preflight_env["db"]
    paths = _seed_legacy(preflight_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()
    before_path = contract.file_path

    storage_root = preflight_env["storage_root"]
    before_files = {p.relative_to(storage_root) for p in storage_root.rglob("*") if p.is_file()}
    legacy_file = preflight_env["contracts_static"] / Path(paths["contract"]).name
    legacy_mtime = legacy_file.stat().st_mtime_ns
    legacy_bytes = legacy_file.read_bytes()

    report = run_production_preflight(
        db=db,
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=True,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=storage_root,
    )
    assert report.mode == "dry_run"
    assert report.db_changed is False
    assert report.filesystem_changed is False
    assert report.activation_summary.get("db_updated") == 0

    db.expire_all()
    after = db.query(Contract).filter(Contract.id == contract.id).first()
    assert after.file_path == before_path

    after_files = {p.relative_to(storage_root) for p in storage_root.rglob("*") if p.is_file()}
    assert after_files == before_files
    assert legacy_file.read_bytes() == legacy_bytes
    assert legacy_file.stat().st_mtime_ns == legacy_mtime


def test_conflict_makes_not_ready(preflight_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = preflight_env["db"]
    paths = _seed_legacy(preflight_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()

    dest_key = build_destination_key("contracts", paths["contract"])
    dest = preflight_env["storage"].resolve(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-OTHER-CONTENT")

    report = run_production_preflight(
        db=db,
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=True,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    assert report.candidates.conflicts >= 1
    assert report.overall == "NOT READY"
    assert any("conflict" in b.lower() for b in report.blockers)


def test_missing_source_is_reported(preflight_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = preflight_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = "/static/uploads/contracts/missing-source.pdf"
    db.commit()

    report = run_production_preflight(
        db=db,
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=False,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    assert report.candidates.missing >= 1
    assert any("missing" in w.lower() for w in report.warnings)


def test_already_unified_reported_correctly(preflight_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = preflight_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    filename = ("f" * 32) + ".pdf"
    key = f"/private/contracts/{filename}"
    dest = preflight_env["storage_root"] / "contracts" / filename
    dest.write_bytes(b"%PDF-unified")
    contract.file_path = key
    db.commit()

    report = run_production_preflight(
        db=db,
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=False,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    assert report.candidates.already_unified >= 1
    assert report.candidates.conflicts == 0


def test_classify_destination_identical():
    from web.services.storage_activation import ActivationItem, ActivationReport

    item = ActivationItem(
        record_type="contract",
        record_id=1,
        user_id="u",
        field_name="file_path",
        category="contracts",
        legacy_key="/static/uploads/contracts/x.pdf",
        status=MigrationStatus.ALREADY_MIGRATED,
        message="destination exists with identical content",
    )
    report = ActivationReport(items=[item], dry_run=True)
    counts = classify_activation_items(report)
    assert counts.destination_identical == 1
    assert counts.already_unified == 0
    assert counts.legacy == 1


def test_cli_rejects_execute(monkeypatch, capsys):
    code = main(["--execute"])
    captured = capsys.readouterr()
    assert code == 2
    assert "--execute" in captured.err


def test_ready_report_json_roundtrip(preflight_env, tmp_path):
    report = run_production_preflight(
        db=preflight_env["db"],
        storage=preflight_env["storage"],
        activation=preflight_env["service"],
        dry_run=True,
        legacy_roots=preflight_env["legacy_specs"],
        storage_root=preflight_env["storage_root"],
    )
    payload = report.to_dict()
    out = tmp_path / "report.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["mode"] == "dry_run"
    assert "candidates" in loaded
    assert loaded["filesystem_changed"] is False
    assert loaded["db_changed"] is False
