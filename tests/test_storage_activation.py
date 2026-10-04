"""DB-backed Unified Storage activation — migration + secure serving."""
from io import BytesIO
from pathlib import Path

import pytest

from models.contract import Contract
from models.education import Education
from models.employee import Employee
from web.services.file_storage import FileStorage
from web.services.storage_activation import (
    ActivationReport,
    StorageActivationService,
    is_legacy_key,
    is_unified_storage_key,
)
from web.services.storage_migration import (
    LegacySourceRoot,
    MigrationStatus,
    StorageMigrationService,
    build_destination_key,
)
from .conftest import login_as


@pytest.fixture
def activation_env(tmp_path, monkeypatch, db):
    contracts_static = tmp_path / "static" / "uploads" / "contracts"
    contracts_private = tmp_path / "private_uploads" / "contracts"
    education_dir = tmp_path / "static" / "uploads" / "certificates"
    avatars_dir = tmp_path / "static" / "uploads" / "avatars"
    for d in (contracts_static, contracts_private, education_dir, avatars_dir):
        d.mkdir(parents=True)

    storage_root = tmp_path / "unified_storage"
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
    return {
        "tmp": tmp_path,
        "storage": storage,
        "storage_root": storage_root,
        "service": service,
        "contracts_static": contracts_static,
        "education_dir": education_dir,
        "avatars_dir": avatars_dir,
        "db": db,
    }


def _seed_legacy_files(env, user_id: str):
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


def test_db_reference_category_mapping():
    assert is_legacy_key("/static/uploads/contracts/a.pdf")
    assert is_legacy_key("/static/uploads/certificates/a.pdf")
    assert is_legacy_key("/static/uploads/avatars/a.jpg")
    assert is_legacy_key("bare.pdf")
    assert not is_legacy_key(None)
    assert not is_legacy_key("")
    assert not is_legacy_key("/private/contracts/abc.pdf")
    assert is_unified_storage_key("/private/education/abc.pdf")


def test_null_path_skipped(activation_env, make_user):
    user = make_user(role="user")
    db = activation_env["db"]
    # contract without file_path exists from make_user — should not appear as migratable
    report = activation_env["service"].preflight()
    for item in report.items:
        if item.user_id == user["user_id"] and item.record_type == "contract":
            assert item.legacy_key  # only non-empty collected
            assert item.status != MigrationStatus.SKIPPED or item.message


def test_legacy_contract_education_avatar_migration(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])

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
        major="CS",
        graduation_date=__import__("datetime").date(2020, 1, 1),
        certificate_path=paths["education"],
        certificate_type="pdf",
    )
    db.add(edu)
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    emp.photo_path = paths["avatar"]
    db.commit()

    dry = activation_env["service"].execute(dry_run=True)
    assert dry.dry_run is True
    assert "contracts" in dry.format_summary()
    assert dry.count_status(MigrationStatus.PENDING) >= 3
    assert dry.count_db_updated() == 0

    # sources still present after dry-run
    assert (activation_env["contracts_static"] / Path(paths["contract"]).name).is_file()

    report = activation_env["service"].execute(dry_run=False)
    assert not report.aborted
    assert report.count_db_updated() >= 3

    db.expire_all()
    contract = db.query(Contract).filter(Contract.id == contract.id).first()
    edu = db.query(Education).filter(Education.id == edu.id).first()
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()

    assert contract.file_path.startswith("/private/contracts/")
    assert edu.certificate_path.startswith("/private/education/")
    assert emp.photo_path.startswith("/private/avatars/")

    # deterministic keys
    assert contract.file_path == build_destination_key("contracts", paths["contract"])
    assert edu.certificate_path == build_destination_key("education", paths["education"])
    assert emp.photo_path == build_destination_key("avatars", paths["avatar"])

    # source retained
    assert (activation_env["contracts_static"] / Path(paths["contract"]).name).is_file()
    assert (activation_env["education_dir"] / Path(paths["education"]).name).is_file()
    assert (activation_env["avatars_dir"] / Path(paths["avatar"]).name).is_file()

    # destinations exist with matching content
    assert activation_env["storage"].resolve(contract.file_path).read_bytes() == b"%PDF-contract-legacy"
    assert activation_env["storage"].resolve(edu.certificate_path).read_bytes() == b"%PDF-education-legacy"
    assert activation_env["storage"].resolve(emp.photo_path).read_bytes() == b"jpeg-avatar-legacy"


def test_already_unified_path_skipped(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    key = "/private/contracts/" + ("a" * 32) + ".pdf"
    dest = activation_env["storage"].resolve(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-already")
    contract.file_path = key
    db.commit()

    report = activation_env["service"].execute(dry_run=False)
    item = next(i for i in report.items if i.record_type == "contract" and i.record_id == contract.id)
    assert item.status == MigrationStatus.ALREADY_MIGRATED
    assert item.needs_db_update is False
    assert item.db_updated is False
    db.expire_all()
    assert db.query(Contract).filter(Contract.id == contract.id).first().file_path == key


def test_missing_source(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = "/static/uploads/contracts/missing.pdf"
    db.commit()
    report = activation_env["service"].preflight()
    item = next(i for i in report.items if i.record_id == contract.id)
    assert item.status == MigrationStatus.MISSING


def test_invalid_extension(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    junk = activation_env["contracts_static"] / "notes.exe"
    junk.write_bytes(b"MZ")
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = "/static/uploads/contracts/notes.exe"
    db.commit()
    report = activation_env["service"].preflight()
    item = next(i for i in report.items if i.record_id == contract.id)
    assert item.status == MigrationStatus.SKIPPED
    assert "extension" in item.message


def test_destination_conflict_aborts_db(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()

    dest_key = build_destination_key("contracts", paths["contract"])
    dest = activation_env["storage"].resolve(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-OTHER")

    report = activation_env["service"].execute(dry_run=False)
    assert report.aborted
    assert report.count_db_updated() == 0
    db.expire_all()
    assert db.query(Contract).filter(Contract.id == contract.id).first().file_path == paths["contract"]


def test_identical_destination_updates_db_only(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()

    dest_key = build_destination_key("contracts", paths["contract"])
    dest = activation_env["storage"].resolve(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-contract-legacy")

    report = activation_env["service"].execute(dry_run=False)
    assert not report.aborted
    item = next(i for i in report.items if i.record_id == contract.id)
    assert item.status == MigrationStatus.ALREADY_MIGRATED
    assert item.db_updated is True
    db.expire_all()
    assert db.query(Contract).filter(Contract.id == contract.id).first().file_path == dest_key
    # source retained
    assert (activation_env["contracts_static"] / Path(paths["contract"]).name).is_file()


def test_db_rollback_on_failure(activation_env, make_user, monkeypatch):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()
    original = paths["contract"]

    svc = activation_env["service"]

    def boom(item):
        raise RuntimeError("forced db failure")

    monkeypatch.setattr(svc, "_apply_db_update", boom)
    report = svc.execute(dry_run=False)
    assert report.aborted
    assert "rolled back" in report.abort_reason.lower() or "DB" in report.abort_reason
    db.expire_all()
    assert db.query(Contract).filter(Contract.id == contract.id).first().file_path == original
    # destination retained for retry
    dest_key = build_destination_key("contracts", original)
    assert activation_env["storage"].resolve(dest_key).is_file()
    assert (activation_env["contracts_static"] / Path(original).name).is_file()


def test_idempotent_second_run(activation_env, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    contract.file_path = paths["contract"]
    db.commit()

    first = activation_env["service"].execute(dry_run=False)
    assert first.count_db_updated() >= 1
    db.expire_all()
    new_key = db.query(Contract).filter(Contract.id == contract.id).first().file_path

    second = activation_env["service"].execute(dry_run=False)
    item = next(i for i in second.items if i.record_id == contract.id)
    assert item.status == MigrationStatus.ALREADY_MIGRATED
    assert item.db_updated is False
    stored = list(activation_env["storage_root"].rglob("*.pdf"))
    # only one destination for this contract key
    assert sum(1 for p in stored if p.name == Path(new_key).name) == 1


def test_education_secure_download_and_access(client, activation_env, make_user):
    owner = make_user(role="user")
    other = make_user(role="user")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, owner["user_id"])
    edu = Education(
        user_id=owner["user_id"],
        education_group="TECH",
        degree_level="BACHELOR",
        major="IT",
        graduation_date=__import__("datetime").date(2019, 5, 1),
        certificate_path=paths["education"],
        certificate_type="pdf",
    )
    db.add(edu)
    db.commit()

    report = activation_env["service"].execute(dry_run=False)
    assert not report.aborted
    db.expire_all()
    edu = db.query(Education).filter(Education.id == edu.id).first()
    assert edu.certificate_path.startswith("/private/education/")

    login_as(client, owner["national_code"])
    ok = client.get(f"/education/{edu.id}/file", follow_redirects=False)
    assert ok.status_code == 200
    assert ok.content.startswith(b"%PDF-education")

    login_as(client, other["national_code"])
    denied = client.get(f"/education/{edu.id}/file", follow_redirects=False)
    assert denied.status_code == 302
    assert "error=" in denied.headers["location"]

    anon = client.get(f"/education/{edu.id}/file", follow_redirects=False)
    # session cleared? login_as for other still logged in — use fresh client cookie clear
    client.cookies.clear()
    anon = client.get(f"/education/{edu.id}/file", follow_redirects=False)
    assert anon.status_code in (302, 307)
    assert "/login" in anon.headers.get("location", "")

    # no direct static access to migrated private key filename
    leaked = client.get(
        f"/static/uploads/certificates/{Path(edu.certificate_path).name}",
        follow_redirects=False,
    )
    assert leaked.status_code == 404


def test_avatar_secure_serving(client, activation_env, make_user):
    user = make_user(role="user")
    admin = make_user(role="admin")
    db = activation_env["db"]
    paths = _seed_legacy_files(activation_env, user["user_id"])
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    emp.photo_path = paths["avatar"]
    db.commit()

    activation_env["service"].execute(dry_run=False)
    db.expire_all()
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.photo_path.startswith("/private/avatars/")

    login_as(client, user["national_code"])
    resp = client.get("/profile/avatar", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"jpeg-avatar-legacy"

    login_as(client, admin["national_code"])
    admin_resp = client.get(
        f"/admin/profile/{user['user_id']}/avatar",
        follow_redirects=False,
    )
    assert admin_resp.status_code == 200
    assert admin_resp.content == b"jpeg-avatar-legacy"

    leaked = client.get(
        f"/static/uploads/avatars/{Path(emp.photo_path).name}",
        follow_redirects=False,
    )
    assert leaked.status_code == 404


def test_existing_unified_contract_still_works(client, activation_env, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    key = "/private/contracts/" + ("b" * 32) + ".pdf"
    dest = activation_env["storage"].resolve(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-unified-existing")
    contract.file_path = key
    db.commit()

    # activation leaves it alone
    report = activation_env["service"].execute(dry_run=False)
    item = next(i for i in report.items if i.record_id == contract.id)
    assert item.status == MigrationStatus.ALREADY_MIGRATED

    login_as(client, admin["national_code"])
    view = client.get(f"/admin/contracts/{contract.id}/file", follow_redirects=False)
    assert view.status_code == 200
    assert view.content.startswith(b"%PDF-unified")


def test_preflight_error_blocks_all_db_updates(activation_env, make_user):
    u1 = make_user(role="user", balance_al=None, contract_type_code="4")
    u2 = make_user(role="user", balance_al=None, contract_type_code="4")
    db = activation_env["db"]
    paths1 = _seed_legacy_files(activation_env, u1["user_id"])
    c1 = (
        db.query(Contract)
        .filter(Contract.user_id == u1["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    c2 = (
        db.query(Contract)
        .filter(Contract.user_id == u2["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    c1.file_path = paths1["contract"]
    # conflict for c2
    bad = "/static/uploads/contracts/conflict.pdf"
    (activation_env["contracts_static"] / "conflict.pdf").write_bytes(b"%PDF-A")
    dest = activation_env["storage"].resolve(build_destination_key("contracts", bad))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-B")
    c2.file_path = bad
    db.commit()

    report = activation_env["service"].execute(dry_run=False)
    assert report.aborted
    assert report.count_db_updated() == 0
    db.expire_all()
    assert db.query(Contract).filter(Contract.id == c1.id).first().file_path == paths1["contract"]
