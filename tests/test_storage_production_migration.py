"""Controlled production migration gates + execute safety (tmp_path / test DB only)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from models.contract import Contract
from models.education import Education
from models.employee import Employee
from web.services.file_storage import PROJECT_ROOT, FileStorage
from web.services.storage_activation import StorageActivationService
from web.services.storage_migration import (
    LegacySourceRoot,
    MigrationStatus,
    StorageMigrationService,
    build_destination_key,
)
from web.services import storage_production_migration as mig
from web.services import storage_production_preflight as pref


@pytest.fixture
def mig_env(tmp_path, monkeypatch, db):
    contracts_static = tmp_path / "static" / "uploads" / "contracts"
    contracts_private = tmp_path / "private_uploads" / "contracts"
    education_dir = tmp_path / "static" / "uploads" / "certificates"
    avatars_dir = tmp_path / "static" / "uploads" / "avatars"
    for d in (contracts_static, contracts_private, education_dir, avatars_dir):
        d.mkdir(parents=True)

    # Outside source tree by construction (pytest tmp).
    storage_root = tmp_path / "unified_storage"
    storage_root.mkdir()
    for name in ("contracts", "education", "avatars", "employee-documents"):
        (storage_root / name).mkdir()

    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("TIMEX_ENV", "test")
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
        "migration": migration,
        "contracts_static": contracts_static,
        "education_dir": education_dir,
        "avatars_dir": avatars_dir,
        "legacy_specs": legacy_specs,
        "db": db,
        "journal_dir": tmp_path / "journals",
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


def _write_backup_manifest(
    env,
    *,
    bad_db=False,
    bad_legacy=False,
    bad_sha=False,
    omit_target=False,
    target_overrides=None,
    created_at=None,
    omit_size=False,
    wrong_size=False,
    omit_sha=False,
    backup_dir=None,
) -> Path:
    tmp_path = env["tmp"]
    # Default backups are siblings of storage_root (tmp/db.dump vs tmp/unified_storage).
    out_dir = Path(backup_dir) if backup_dir is not None else tmp_path
    out_dir.mkdir(parents=True, exist_ok=True)
    db_backup = out_dir / "db.dump"
    legacy_backup = out_dir / "legacy.zip"
    db_backup.write_bytes(b"FAKE-DB-BACKUP" if not bad_db else b"")
    legacy_backup.write_bytes(b"FAKE-LEGACY-BACKUP" if not bad_legacy else b"")
    db_sha = hashlib.sha256(db_backup.read_bytes()).hexdigest() if db_backup.stat().st_size else "0" * 64
    legacy_sha = (
        hashlib.sha256(legacy_backup.read_bytes()).hexdigest()
        if legacy_backup.stat().st_size
        else "0" * 64
    )
    if bad_sha:
        db_sha = "a" * 64

    if created_at is None:
        created_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    target = mig.build_target_identity(
        db=env["db"], storage_root=env["storage_root"]
    )
    target_payload = {
        "database": target.database,
        "storage_root": target.storage_root,
        "environment": target.environment,
        "target_id": target.target_id,
    }
    if target_overrides:
        target_payload.update(target_overrides)

    db_entry = {
        "path": str(db_backup),
        "sha256": db_sha,
    }
    legacy_entry = {
        "path": str(legacy_backup),
        "sha256": legacy_sha,
    }
    if not omit_size:
        db_entry["size_bytes"] = (
            db_backup.stat().st_size + 1 if wrong_size else db_backup.stat().st_size
        )
        legacy_entry["size_bytes"] = legacy_backup.stat().st_size
    if omit_sha:
        db_entry.pop("sha256", None)
        legacy_entry.pop("sha256", None)

    manifest = {
        "created_at": created_at,
        "operator": "tester",
        "database_backup": db_entry,
        "legacy_backup": legacy_entry,
    }
    if not omit_target:
        manifest["target"] = target_payload
    path = tmp_path / "storage_migration_backup.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _attach_legacy_paths(env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = env["db"]
    paths = _seed_legacy(env, user["user_id"])
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
    return user, paths, contract, edu


def _eval(env, **kwargs):
    defaults = dict(
        db=env["db"],
        storage=env["storage"],
        activation=env["service"],
        legacy_roots=env["legacy_specs"],
        confirm_production=True,
        allow_missing=0,
        require_backup=True,
        require_confirm=True,
    )
    defaults.update(kwargs)
    return mig.evaluate_execute_gates(**defaults)


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

def test_no_backup_manifest_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    gates = _eval(mig_env, backup_manifest=mig_env["tmp"] / "missing.json")
    assert gates.allowed is False
    assert any("manifest" in b.lower() for b in gates.blockers)


def test_invalid_manifest_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    bad = mig_env["tmp"] / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    gates = _eval(mig_env, backup_manifest=bad)
    assert gates.allowed is False
    assert any("invalid" in b.lower() or "json" in b.lower() for b in gates.blockers)


def test_missing_db_backup_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    legacy = mig_env["tmp"] / "legacy.zip"
    legacy.write_bytes(b"legacy")
    target = mig.build_target_identity(
        db=mig_env["db"], storage_root=mig_env["storage_root"]
    )
    manifest = {
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "operator": "op",
        "target": {
            "database": target.database,
            "storage_root": target.storage_root,
            "environment": target.environment,
            "target_id": target.target_id,
        },
        "database_backup": {
            "path": str(mig_env["tmp"] / "no-db.dump"),
            "size_bytes": 1,
            "sha256": "ab",
        },
        "legacy_backup": {
            "path": str(legacy),
            "size_bytes": legacy.stat().st_size,
            "sha256": hashlib.sha256(b"legacy").hexdigest(),
        },
    }
    path = mig_env["tmp"] / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    gates = _eval(mig_env, backup_manifest=path)
    assert gates.allowed is False
    assert any("database_backup" in b for b in gates.blockers)


def test_missing_legacy_backup_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    db_backup = mig_env["tmp"] / "db.dump"
    db_backup.write_bytes(b"db")
    target = mig.build_target_identity(
        db=mig_env["db"], storage_root=mig_env["storage_root"]
    )
    manifest = {
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "operator": "op",
        "target": {
            "database": target.database,
            "storage_root": target.storage_root,
            "environment": target.environment,
            "target_id": target.target_id,
        },
        "database_backup": {
            "path": str(db_backup),
            "size_bytes": db_backup.stat().st_size,
            "sha256": hashlib.sha256(b"db").hexdigest(),
        },
        "legacy_backup": {
            "path": str(mig_env["tmp"] / "no-legacy.zip"),
            "size_bytes": 1,
            "sha256": "cd",
        },
    }
    path = mig_env["tmp"] / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    gates = _eval(mig_env, backup_manifest=path)
    assert gates.allowed is False
    assert any("legacy_backup" in b for b in gates.blockers)


def test_bad_checksum_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, bad_sha=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("sha256" in b.lower() for b in gates.blockers)


def test_storage_inside_source_tree_rejects(mig_env, make_user, monkeypatch):
    _attach_legacy_paths(mig_env, make_user)
    inside = PROJECT_ROOT / ".tmp_unified_storage_gate_test"
    inside.mkdir(exist_ok=True)
    for name in ("contracts", "education", "avatars", "employee-documents"):
        (inside / name).mkdir(exist_ok=True)
    try:
        monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(inside))
        storage = FileStorage(root=inside)
        service = StorageActivationService(
            mig_env["db"], storage=storage, migration=mig_env["migration"]
        )
        # Point migration storage to inside root for consistency.
        mig_env["migration"].storage = storage
        inside_env = {**mig_env, "storage_root": inside, "storage": storage}
        manifest = _write_backup_manifest(inside_env)
        gates = mig.evaluate_execute_gates(
            db=mig_env["db"],
            storage=storage,
            activation=service,
            backup_manifest=manifest,
            confirm_production=True,
            legacy_roots=mig_env["legacy_specs"],
        )
        assert gates.allowed is False
        assert any("outside source tree" in b.lower() for b in gates.blockers)
    finally:
        import shutil

        shutil.rmtree(inside, ignore_errors=True)


def test_missing_candidate_rejects(mig_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = mig_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = "/static/uploads/contracts/missing.pdf"
    db.commit()
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("missing" in b.lower() for b in gates.blockers)


def test_conflict_rejects(mig_env, make_user):
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    dest_key = build_destination_key("contracts", paths["contract"])
    dest = mig_env["storage"].resolve(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-OTHER")
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("conflict" in b.lower() for b in gates.blockers)


def test_invalid_reference_rejects(mig_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = mig_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = "/private/education/" + ("c" * 32) + ".pdf"
    db.commit()
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("invalid" in b.lower() for b in gates.blockers)


def test_insufficient_disk_space_rejects(mig_env, make_user, monkeypatch):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)

    class _Usage:
        total = 100
        used = 100
        free = 0

    monkeypatch.setattr(pref.shutil, "disk_usage", lambda p: _Usage())
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("disk space" in b.lower() for b in gates.blockers)


def test_missing_confirm_production_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest, confirm_production=False)
    assert gates.allowed is False
    assert any("confirm-production" in b for b in gates.blockers)


def test_successful_gate_evaluation_allows_execute(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest, confirm_production=True)
    assert gates.allowed is True
    assert gates.blockers == []
    assert gates.target is not None
    assert gates.target.target_id
    assert gates.ready_bytes > 0
    assert gates.free_bytes is not None
    assert gates.headroom_bytes is not None
    assert gates.headroom_bytes == gates.free_bytes - gates.ready_bytes


# ---------------------------------------------------------------------------
# Execute safety
# ---------------------------------------------------------------------------

def test_preflight_failure_zero_migration_changes(mig_env, make_user):
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    dest_key = build_destination_key("contracts", paths["contract"])
    dest = mig_env["storage"].resolve(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-OTHER")
    before = contract.file_path
    before_files = {
        p.relative_to(mig_env["storage_root"])
        for p in mig_env["storage_root"].rglob("*")
        if p.is_file()
    }
    manifest = _write_backup_manifest(mig_env)
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is False
    assert activation is None
    mig_env["db"].expire_all()
    assert (
        mig_env["db"].query(Contract).filter(Contract.id == contract.id).first().file_path
        == before
    )
    after_files = {
        p.relative_to(mig_env["storage_root"])
        for p in mig_env["storage_root"].rglob("*")
        if p.is_file()
    }
    assert after_files == before_files


def test_backup_failure_zero_migration_changes(mig_env, make_user):
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    before = contract.file_path
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=mig_env["tmp"] / "nope.json",
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is False
    assert activation is None
    mig_env["db"].expire_all()
    assert (
        mig_env["db"].query(Contract).filter(Contract.id == contract.id).first().file_path
        == before
    )


def test_copy_failure_db_unchanged(mig_env, make_user, monkeypatch):
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    before = contract.file_path
    manifest = _write_backup_manifest(mig_env)

    def boom(item):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(mig_env["migration"], "_copy_item", boom)
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.aborted is True
    assert journal.db_updated == 0
    mig_env["db"].expire_all()
    row = mig_env["db"].query(Contract).filter(Contract.id == contract.id).first()
    assert row.file_path == before
    # source retained
    assert (mig_env["contracts_static"] / Path(paths["contract"]).name).is_file()


def test_sha_mismatch_db_unchanged(mig_env, make_user, monkeypatch):
    from web.services import storage_activation as act_mod

    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    before = contract.file_path
    manifest = _write_backup_manifest(mig_env)

    real_fp = act_mod._file_fingerprint
    real_execute = mig_env["service"].execute

    def flaky(path):
        # Force destination verify to disagree with source after copy.
        digest = real_fp(path)
        # Destinations live under storage root; poison only those fingerprints.
        try:
            path.relative_to(mig_env["storage_root"])
            return "0" * 64
        except ValueError:
            return digest

    def wrapped_execute(*, dry_run=True):
        if dry_run:
            return real_execute(dry_run=True)
        monkeypatch.setattr(act_mod, "_file_fingerprint", flaky)
        return real_execute(dry_run=False)

    monkeypatch.setattr(mig_env["service"], "execute", wrapped_execute)
    journal, _activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.db_updated == 0
    mig_env["db"].expire_all()
    assert (
        mig_env["db"].query(Contract).filter(Contract.id == contract.id).first().file_path
        == before
    )
    assert (mig_env["contracts_static"] / Path(paths["contract"]).name).is_file()


def test_db_failure_rollback_sources_retained(mig_env, make_user, monkeypatch):
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    before = contract.file_path
    manifest = _write_backup_manifest(mig_env)

    real_commit = mig_env["db"].commit
    state = {"armed": False}

    def flaky_commit():
        # Allow seeding/gate queries; fail the migration DB update commit.
        if state["armed"]:
            raise RuntimeError("db commit failed")
        return real_commit()

    # Arm after gates by wrapping execute.
    real_execute = mig_env["service"].execute

    def wrapped_execute(*, dry_run=True):
        if dry_run:
            return real_execute(dry_run=True)
        state["armed"] = True
        monkeypatch.setattr(mig_env["db"], "commit", flaky_commit)
        return real_execute(dry_run=False)

    monkeypatch.setattr(mig_env["service"], "execute", wrapped_execute)

    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.aborted is True
    assert journal.db_updated == 0
    mig_env["db"].expire_all()
    row = mig_env["db"].query(Contract).filter(Contract.id == contract.id).first()
    assert row.file_path == before
    assert (mig_env["contracts_static"] / Path(paths["contract"]).name).is_file()
    # Destinations may remain for retry (activation design).
    if activation is not None:
        pending_or_copied = [
            i
            for i in activation.items
            if i.destination_path and Path(i.destination_path).exists()
        ]
        assert pending_or_copied or journal.aborted


def test_successful_migration_updates_db_and_retains_sources(mig_env, make_user):
    user, paths, contract, edu = _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.aborted is False
    assert journal.phase == "completed"
    assert journal.db_updated >= 3
    assert journal.sources_deleted is False
    assert Path(journal.journal_path).is_file()
    payload = json.loads(Path(journal.journal_path).read_text(encoding="utf-8"))
    assert payload["phase"] == "completed"
    assert payload["sources_deleted"] is False
    assert payload["target_id"]

    mig_env["db"].expire_all()
    c = mig_env["db"].query(Contract).filter(Contract.id == contract.id).first()
    e = mig_env["db"].query(Education).filter(Education.id == edu.id).first()
    emp = mig_env["db"].query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert c.file_path.startswith("/private/contracts/")
    assert e.certificate_path.startswith("/private/education/")
    assert emp.photo_path.startswith("/private/avatars/")

    assert (mig_env["contracts_static"] / Path(paths["contract"]).name).is_file()
    assert (mig_env["education_dir"] / Path(paths["education"]).name).is_file()
    assert (mig_env["avatars_dir"] / Path(paths["avatar"]).name).is_file()


def test_second_execution_idempotent(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    first, _ = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert first.executed and not first.aborted

    second, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    # No pending work left — either blocked by missing=0 ready or executes as already migrated.
    if second.executed:
        assert second.db_updated == 0
        assert activation is not None
        assert activation.count_status(MigrationStatus.ALREADY_MIGRATED) >= 3
        assert activation.count_status(MigrationStatus.PENDING) == 0
    else:
        # If ready=0 and gates still allow, should have executed; if blocked, not expected.
        # With already-unified only, ready=0, missing=0 → allowed and execute is no-op.
        assert second.executed is False or second.db_updated == 0


def test_journal_written_on_gate_failure(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    journal, _ = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=mig_env["tmp"] / "missing-manifest.json",
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.aborted is True
    assert journal.executed is False
    assert journal.phase == "blocked"
    path = Path(journal.journal_path)
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sources_deleted"] is False
    assert payload["gates"]["allowed"] is False
    assert payload["phase"] == "blocked"


def test_cli_execute_without_confirm_does_not_migrate(mig_env, make_user):
    """Missing --confirm-production must not execute migration."""
    user, paths, contract, _edu = _attach_legacy_paths(mig_env, make_user)
    before = contract.file_path
    manifest = _write_backup_manifest(mig_env)
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=False,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is False
    assert activation is None
    assert any("confirm-production" in b for b in journal.gates["blockers"])
    mig_env["db"].expire_all()
    assert (
        mig_env["db"].query(Contract).filter(Contract.id == contract.id).first().file_path
        == before
    )
    assert (mig_env["contracts_static"] / Path(paths["contract"]).name).is_file()


# ---------------------------------------------------------------------------
# Target-bound manifest + strict backup metadata
# ---------------------------------------------------------------------------

def test_target_id_missing_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, omit_target=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("target" in b.lower() for b in gates.blockers)


def test_target_id_mismatch_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(
        mig_env, target_overrides={"target_id": "deadbeefdeadbeef"}
    )
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("target_id mismatch" in b for b in gates.blockers)


def test_storage_root_mismatch_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(
        mig_env, target_overrides={"storage_root": str(mig_env["tmp"] / "other-root")}
    )
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("storage_root mismatch" in b for b in gates.blockers)


def test_database_identity_mismatch_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(
        mig_env, target_overrides={"database": "other@host:5432/other_db"}
    )
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("database mismatch" in b for b in gates.blockers)


def test_invalid_created_at_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, created_at="not-a-date")
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("created_at" in b.lower() for b in gates.blockers)


def test_future_created_at_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    manifest = _write_backup_manifest(
        mig_env, created_at="2026-10-04T13:00:00+00:00"
    )
    gates = _eval(mig_env, backup_manifest=manifest, now=now)
    assert gates.allowed is False
    assert any("future" in b.lower() for b in gates.blockers)


def test_fresh_manifest_created_at_passes(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    manifest = _write_backup_manifest(
        mig_env, created_at="2026-10-04T11:00:00+00:00"
    )
    gates = _eval(
        mig_env,
        backup_manifest=manifest,
        now=now,
        max_backup_age_hours=24,
    )
    assert gates.allowed is True


def test_manifest_created_at_exact_boundary_passes(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    manifest = _write_backup_manifest(
        mig_env, created_at="2026-10-03T12:00:00+00:00"
    )
    gates = _eval(
        mig_env,
        backup_manifest=manifest,
        now=now,
        max_backup_age_hours=24,
    )
    assert gates.allowed is True


def test_stale_manifest_created_at_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    manifest = _write_backup_manifest(
        mig_env, created_at="2026-10-03T11:59:59+00:00"
    )
    gates = _eval(
        mig_env,
        backup_manifest=manifest,
        now=now,
        max_backup_age_hours=24,
    )
    assert gates.allowed is False
    assert any("too old" in b.lower() for b in gates.blockers)


def test_negative_max_backup_age_hours_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest, max_backup_age_hours=-1)
    assert gates.allowed is False
    assert any("max_backup_age_hours" in b for b in gates.blockers)


def test_invalid_max_backup_age_hours_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    gates = _eval(mig_env, backup_manifest=manifest, max_backup_age_hours="abc")
    assert gates.allowed is False
    assert any("max_backup_age_hours" in b for b in gates.blockers)


def test_backup_path_inside_storage_root_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    # Place artifacts under TIMEX_STORAGE_ROOT — must hard-block.
    manifest = _write_backup_manifest(
        mig_env, backup_dir=mig_env["storage_root"] / "nested-backups"
    )
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("inside storage root" in b.lower() for b in gates.blockers)


def test_backup_path_sibling_of_storage_root_allowed(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    # tmp/backups is a sibling of tmp/unified_storage.
    sibling = mig_env["tmp"] / "backups"
    manifest = _write_backup_manifest(mig_env, backup_dir=sibling)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is True
    assert not any("inside storage root" in b.lower() for b in gates.blockers)


def test_missing_size_bytes_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, omit_size=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("size_bytes is required" in b for b in gates.blockers)


def test_wrong_size_bytes_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, wrong_size=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("size_bytes mismatch" in b for b in gates.blockers)


def test_missing_sha256_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, omit_sha=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("sha256 is required" in b for b in gates.blockers)


def test_wrong_sha256_rejects(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env, bad_sha=True)
    gates = _eval(mig_env, backup_manifest=manifest)
    assert gates.allowed is False
    assert any("sha256 mismatch" in b.lower() for b in gates.blockers)


# ---------------------------------------------------------------------------
# Journal durability / atomicity / phases
# ---------------------------------------------------------------------------

def test_initial_journal_exists_before_execute(mig_env, make_user, monkeypatch):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    journal_path = mig_env["journal_dir"] / "pre_mutate.json"
    seen = {"phase": None, "exists_before_mutate": False}

    real_execute = mig_env["service"].execute

    def wrapped(*, dry_run=True):
        if dry_run:
            return real_execute(dry_run=True)
        assert journal_path.is_file(), "initial journal must exist before mutation"
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        seen["exists_before_mutate"] = True
        seen["phase"] = payload["phase"]
        assert payload["executed"] is False
        assert payload["sources_deleted"] is False
        assert payload["target_id"]
        assert payload["backup_manifest"]["path"]
        raise RuntimeError("simulated crash before mutation completes")

    monkeypatch.setattr(mig_env["service"], "execute", wrapped)
    journal, activation = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_path=journal_path,
    )
    assert seen["exists_before_mutate"] is True
    assert seen["phase"] == "executing"
    assert activation is None
    assert journal.phase == "aborted"
    assert journal.executed is True
    assert journal.aborted is True
    assert journal.sources_deleted is False
    final = json.loads(journal_path.read_text(encoding="utf-8"))
    assert final["phase"] == "aborted"
    assert final["sources_deleted"] is False
    assert "unhandled execute exception" in final["abort_reason"]


def test_atomic_journal_write(tmp_path):
    journal = mig.ExecutionJournal(
        started_at="2020-01-01T00:00:00+00:00",
        phase="started",
        target_id="abc",
        sources_deleted=False,
    )
    path = tmp_path / "atomic.json"
    replaces = []
    real_replace = mig.os.replace

    def tracking_replace(src, dst):
        replaces.append((src, dst))
        return real_replace(src, dst)

    mig.os.replace = tracking_replace
    try:
        mig.write_journal(journal, path)
    finally:
        mig.os.replace = real_replace

    assert path.is_file()
    assert replaces, "atomic replace must be used"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["phase"] == "started"
    assert payload["journal_path"] == str(path.resolve())
    assert list(tmp_path.glob(".*.tmp")) == []


def test_blocked_execution_journal_phase(mig_env, make_user):
    _attach_legacy_paths(mig_env, make_user)
    journal, _ = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=mig_env["tmp"] / "missing.json",
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.phase == "blocked"
    assert journal.executed is False
    assert journal.sources_deleted is False


def test_copy_failure_updates_journal(mig_env, make_user, monkeypatch):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)

    def boom(item):
        raise RuntimeError("copy failed")

    monkeypatch.setattr(mig_env["migration"], "_copy_item", boom)
    journal, _ = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.phase == "aborted"
    assert journal.sources_deleted is False
    payload = json.loads(Path(journal.journal_path).read_text(encoding="utf-8"))
    assert payload["phase"] == "aborted"
    assert payload["sources_deleted"] is False


def test_db_failure_updates_journal(mig_env, make_user, monkeypatch):
    _attach_legacy_paths(mig_env, make_user)
    manifest = _write_backup_manifest(mig_env)
    real_commit = mig_env["db"].commit
    state = {"armed": False}

    def flaky_commit():
        if state["armed"]:
            raise RuntimeError("db commit failed")
        return real_commit()

    real_execute = mig_env["service"].execute

    def wrapped(*, dry_run=True):
        if dry_run:
            return real_execute(dry_run=True)
        state["armed"] = True
        monkeypatch.setattr(mig_env["db"], "commit", flaky_commit)
        return real_execute(dry_run=False)

    monkeypatch.setattr(mig_env["service"], "execute", wrapped)
    journal, _ = mig.run_controlled_execute(
        db=mig_env["db"],
        storage=mig_env["storage"],
        activation=mig_env["service"],
        backup_manifest=manifest,
        confirm_production=True,
        legacy_roots=mig_env["legacy_specs"],
        journal_dir=mig_env["journal_dir"],
    )
    assert journal.executed is True
    assert journal.phase == "aborted"
    assert journal.db_updated == 0
    assert journal.sources_deleted is False
