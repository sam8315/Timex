"""آپلود و مشاهده فایل قرارداد — ذخیره private و دسترسی محافظت‌شده."""
from io import BytesIO
from pathlib import Path

import jdatetime
import pytest

from models.contract import Contract
from web.services.contract_file_storage import (
    PRIVATE_PATH_PREFIX,
    UPLOAD_DIR,
    resolve_contract_file_disk,
)
from .conftest import login_as


def _year_bounds_j():
    from web.services.leave_entitlement_service import jalali_year_bounds_g
    year = jdatetime.date.today().year
    start_g, end_g = jalali_year_bounds_g(year)
    return (
        jdatetime.date.fromgregorian(date=start_g).strftime("%Y/%m/%d"),
        jdatetime.date.fromgregorian(date=end_g).strftime("%Y/%m/%d"),
    )


@pytest.fixture(autouse=True)
def _cleanup_upload_dir():
    before = set(UPLOAD_DIR.glob("*")) if UPLOAD_DIR.exists() else set()
    yield
    if UPLOAD_DIR.exists():
        for p in UPLOAD_DIR.glob("*"):
            if p.name == ".gitkeep" or p in before:
                continue
            try:
                p.unlink()
            except OSError:
                pass


def test_add_contract_with_pdf_and_view(client, db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    start_j, end_j = _year_bounds_j()
    pdf_bytes = b"%PDF-1.4\n%fake contract file\n"
    resp = client.post(
        "/admin/contracts/add",
        data={
            "user_id": user["user_id"],
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": end_j,
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
        },
        files={
            "contract_file": ("contract.pdf", BytesIO(pdf_bytes), "application/pdf"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]

    db.expire_all()
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract is not None
    assert contract.file_path
    assert contract.file_path.startswith(PRIVATE_PATH_PREFIX)
    assert "/static/" not in contract.file_path
    disk = resolve_contract_file_disk(contract.file_path)
    assert disk.is_file()
    assert UPLOAD_DIR in disk.parents or disk.parent == UPLOAD_DIR

    # مسیر استاتیک عمومی دیگر فایل را سرو نمی‌کند
    public_guess = f"/static/uploads/contracts/{Path(contract.file_path).name}"
    leaked = client.get(public_guess, follow_redirects=False)
    assert leaked.status_code == 404

    view = client.get(f"/admin/contracts/{contract.id}/file", follow_redirects=False)
    assert view.status_code == 200
    assert view.content.startswith(b"%PDF")


def test_owner_can_view_own_contract_file(client, db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    start_j, end_j = _year_bounds_j()
    pdf_bytes = b"%PDF-1.4\n%owner file\n"
    client.post(
        "/admin/contracts/add",
        data={
            "user_id": user["user_id"],
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": end_j,
            "stored_leave_days": "0",
        },
        files={
            "contract_file": ("contract.pdf", BytesIO(pdf_bytes), "application/pdf"),
        },
        follow_redirects=False,
    )
    db.expire_all()
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract and contract.file_path

    login_as(client, user["national_code"])
    own = client.get(f"/contract/{contract.id}/file", follow_redirects=False)
    assert own.status_code == 200
    assert own.content.startswith(b"%PDF")


def test_other_user_cannot_view_contract_file(client, db, make_user):
    admin = make_user(role="super_admin")
    owner = make_user(role="user", balance_al=None, contract_type_code="4")
    other = make_user(role="user", balance_al=None, contract_type_code="4")
    db.query(Contract).filter(Contract.user_id == owner["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    start_j, end_j = _year_bounds_j()
    client.post(
        "/admin/contracts/add",
        data={
            "user_id": owner["user_id"],
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": end_j,
            "stored_leave_days": "0",
        },
        files={
            "contract_file": ("contract.pdf", BytesIO(b"%PDF-1.4\nsec\n"), "application/pdf"),
        },
        follow_redirects=False,
    )
    db.expire_all()
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == owner["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract and contract.file_path

    login_as(client, other["national_code"])
    denied = client.get(f"/contract/{contract.id}/file", follow_redirects=False)
    assert denied.status_code == 302
    assert "/contract" in denied.headers["location"]


def test_reject_invalid_extension(client, db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", balance_al=None, contract_type_code="4")
    db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
    db.commit()

    login_as(client, admin["national_code"])
    start_j, end_j = _year_bounds_j()
    resp = client.post(
        "/admin/contracts/add",
        data={
            "user_id": user["user_id"],
            "contract_type_code": "4",
            "start_date_str": start_j,
            "end_date_str": end_j,
            "stored_leave_days": "0",
        },
        files={
            "contract_file": ("evil.exe", BytesIO(b"MZ"), "application/octet-stream"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    db.expire_all()
    assert db.query(Contract).filter(Contract.user_id == user["user_id"]).count() == 0
