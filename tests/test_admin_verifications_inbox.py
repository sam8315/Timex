"""Tests for unified admin verification inbox."""
from datetime import date
from urllib.parse import unquote

import pytest

from models.education import Education
from models.employee import Employee
from models.employee_document_type import EmployeeDocumentType
from models.user_permission import UserPermission
from web.services.employee_document_service import create_document
from web.services.employee_relative_service import create_relative
from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "timex_storage"
    monkeypatch.setenv("TIMEX_STORAGE_ROOT", str(root))
    yield root


def _revoke(db, user_id: str, permission: str):
    db.add(
        UserPermission(
            user_id=user_id,
            permission=permission,
            granted=False,
        )
    )
    db.commit()


def _type_id(db, code: str = "NATIONAL_ID") -> int:
    row = (
        db.query(EmployeeDocumentType)
        .filter(EmployeeDocumentType.code == code)
        .first()
    )
    assert row is not None
    return row.id


def _make_document(db, user_id: str, title: str = "کارت ملی"):
    return create_document(
        db,
        user_id=user_id,
        uploaded_by=user_id,
        document_type_id=_type_id(db),
        title=title,
        file_bytes=b"%PDF-1.4\ndoc",
        original_filename="id.pdf",
    )


def _make_relative(db, user_id: str, first_name: str = "سارا", last_name: str = "احمدی"):
    return create_relative(
        db,
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        relationship_type="CHILD",
        birth_date=date(2018, 3, 15),
    )


def _make_education(db, user_id: str, major: str = "مهندسی نرم‌افزار"):
    edu = Education(
        user_id=user_id,
        education_group="TECH",
        degree_level="BACHELOR",
        major=major,
        graduation_date=date(2020, 1, 1),
        verified=False,
    )
    db.add(edu)
    db.commit()
    db.refresh(edu)
    return edu


def _login_admin(client, make_user, role="super_admin"):
    admin = make_user(role=role)
    login_as(client, admin["national_code"])
    return admin


def test_inbox_lists_all_three_kinds(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    doc = _make_document(db, target["user_id"], title="مدرک صف")
    rel = _make_relative(db, target["user_id"])
    edu = _make_education(db, target["user_id"])

    resp = client.get("/admin/verifications", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert "صف تأیید مدارک" in body
    assert "تأیید مدارک" in body  # sidebar
    assert "مدرک صف" in body
    assert "سارا احمدی" in body
    assert "مهندسی نرم‌افزار" in body
    assert f"/admin/verifications/documents/{doc.id}/verify" in body
    assert f"/admin/verifications/relatives/{rel.id}/verify" in body
    assert f"/admin/verifications/education/{edu.id}/verify" in body
    assert f"/employee-documents/{doc.id}/file" in body


def test_inbox_filter_kind(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    _make_document(db, target["user_id"], title="فقط مدرک")
    _make_relative(db, target["user_id"], first_name="فقط", last_name="بسته")
    _make_education(db, target["user_id"], major="فقط‌تحصیلی")

    docs = client.get("/admin/verifications?kind=document", headers=HTML_ACCEPT)
    assert docs.status_code == 200
    assert "فقط مدرک" in docs.text
    assert "فقط بسته" not in docs.text
    assert "فقط‌تحصیلی" not in docs.text

    rels = client.get("/admin/verifications?kind=relative", headers=HTML_ACCEPT)
    assert "فقط بسته" in rels.text
    assert "فقط مدرک" not in rels.text

    edus = client.get("/admin/verifications?kind=education", headers=HTML_ACCEPT)
    assert "فقط‌تحصیلی" in edus.text
    assert "فقط مدرک" not in edus.text


def test_inbox_search_by_employee_name(client, db, make_user):
    _login_admin(client, make_user)
    a = make_user(role="user", balance_al=None)
    b = make_user(role="user", balance_al=None)
    emp_a = db.query(Employee).filter(Employee.user_id == a["user_id"]).first()
    emp_b = db.query(Employee).filter(Employee.user_id == b["user_id"]).first()
    emp_a.first_name = "علی‌جستجو"
    emp_a.last_name = "رضایی"
    emp_b.first_name = "مریم"
    emp_b.last_name = "دیگر"
    db.commit()

    _make_document(db, a["user_id"], title="مدرک علی")
    _make_document(db, b["user_id"], title="مدرک مریم")

    resp = client.get(
        "/admin/verifications?search=علی‌جستجو",
        headers=HTML_ACCEPT,
    )
    assert resp.status_code == 200
    assert "مدرک علی" in resp.text
    assert "مدرک مریم" not in resp.text


def test_inbox_verify_reject_document(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    doc = _make_document(db, target["user_id"])

    ok = client.post(
        f"/admin/verifications/documents/{doc.id}/verify",
        data={"kind": "document", "search": ""},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    assert "/admin/verifications" in ok.headers["location"]
    db.refresh(doc)
    assert doc.status == "VERIFIED"

    doc2 = _make_document(db, target["user_id"], title="رد از صف")
    bad = client.post(
        f"/admin/verifications/documents/{doc2.id}/reject",
        data={
            "rejection_reason": "ناقص",
            "kind": "all",
            "search": "",
        },
        follow_redirects=False,
    )
    assert bad.status_code == 302
    db.refresh(doc2)
    assert doc2.status == "REJECTED"
    assert doc2.rejection_reason == "ناقص"


def test_inbox_verify_reject_relative(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    rel = _make_relative(db, target["user_id"])

    ok = client.post(
        f"/admin/verifications/relatives/{rel.id}/verify",
        data={"kind": "relative"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    db.refresh(rel)
    assert rel.status == "VERIFIED"

    rel2 = _make_relative(db, target["user_id"], first_name="رد", last_name="شده")
    bad = client.post(
        f"/admin/verifications/relatives/{rel2.id}/reject",
        data={"rejection_reason": "اطلاعات نادرست", "kind": "all"},
        follow_redirects=False,
    )
    assert bad.status_code == 302
    db.refresh(rel2)
    assert rel2.status == "REJECTED"


def test_inbox_verify_education(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    edu = _make_education(db, target["user_id"])

    ok = client.post(
        f"/admin/verifications/education/{edu.id}/verify",
        data={"kind": "education"},
        follow_redirects=False,
    )
    assert ok.status_code == 302
    loc = unquote(ok.headers["location"])
    assert "/admin/verifications" in loc
    db.refresh(edu)
    assert edu.verified is True


def test_inbox_hides_kind_without_permission(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "verify_employee_documents")
    _revoke(db, admin["user_id"], "verify_employee_relatives")
    # view_dashboard kept → only education
    login_as(client, admin["national_code"])

    target = make_user(role="user", balance_al=None)
    _make_document(db, target["user_id"], title="پنهان‌مدرک")
    _make_relative(db, target["user_id"], first_name="پنهان", last_name="بسته")
    _make_education(db, target["user_id"], major="نمایان‌تحصیلی")

    resp = client.get("/admin/verifications", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    assert "نمایان‌تحصیلی" in resp.text
    assert "پنهان‌مدرک" not in resp.text
    assert "پنهان بسته" not in resp.text
    assert 'value="document"' not in resp.text
    assert 'value="relative"' not in resp.text


def test_inbox_forbidden_when_no_relevant_permission(client, db, make_user):
    admin = make_user(role="admin")
    _revoke(db, admin["user_id"], "verify_employee_documents")
    _revoke(db, admin["user_id"], "verify_employee_relatives")
    _revoke(db, admin["user_id"], "view_dashboard")
    login_as(client, admin["national_code"])

    resp = client.get("/admin/verifications", headers=HTML_ACCEPT)
    assert resp.status_code == 403


def test_admin_dashboard_shows_verification_card(client, db, make_user):
    _login_admin(client, make_user)
    target = make_user(role="user", balance_al=None)
    doc = _make_document(db, target["user_id"], title="مدرک داشبورد")

    resp = client.get("/admin", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert "تأیید مدارک" in body
    assert 'href="/admin/verifications"' in body
    assert "badge-count" in body
    assert "مدرک داشبورد" in body
    assert "آخرین کاربران ربات بله" not in body
    assert f"/admin/verifications/documents/{doc.id}/verify" in body
