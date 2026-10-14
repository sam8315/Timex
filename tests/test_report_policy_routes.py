"""مسیرهای سیاست گزارش: دسترسی، ذخیره و audit."""
import pytest

from models.policy import PolicyAuditLog
from models.report_policy import ReportPolicy
from .conftest import login_as


@pytest.fixture(autouse=True)
def _clean(db):
    def wipe():
        db.rollback()
        db.query(ReportPolicy).delete()
        db.query(PolicyAuditLog).filter(
            PolicyAuditLog.entity_type == "report_policy").delete()
        db.commit()
    wipe()
    yield
    wipe()


def _super(client, make_user):
    creds = make_user(role="super_admin", balance_al=None)
    assert login_as(client, creds["national_code"]).status_code == 302
    return creds


def test_card_and_pages_render(client, make_user):
    _super(client, make_user)
    assert "سیاست گزارش" in client.get("/admin/policies").text
    assert client.get("/admin/policies/reports").status_code == 200
    r = client.get("/admin/policies/reports/legal-overtime")
    assert r.status_code == 200 and "اضافه‌کار عادی در تعدیل کسر کار" in r.text


def test_save_creates_version_and_audit(client, db, make_user):
    _super(client, make_user)
    r = client.post("/admin/policies/reports/legal-overtime/save", data={
        "effective_from": "1405/08/01", "deficit_adjust_friday_work": "on",
    }, follow_redirects=False)
    assert r.status_code == 302 and "success=saved" in r.headers["location"]
    row = db.query(ReportPolicy).one()
    assert row.settings["deficit_adjust_friday_work"] is True
    assert row.settings["deficit_adjust_holiday_work"] is False
    assert db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "report_policy").count() == 1


def test_save_rejects_bad_date(client, db, make_user):
    _super(client, make_user)
    r = client.post("/admin/policies/reports/legal-overtime/save",
                    data={"effective_from": "1405/08/05"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert db.query(ReportPolicy).count() == 0


def test_non_super_admin_rejected(client, db, make_user):
    creds = make_user(role="user", balance_al=None)
    login_as(client, creds["national_code"])
    r = client.post("/admin/policies/reports/legal-overtime/save",
                    data={"effective_from": "1405/08/01"}, follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)
    assert db.query(ReportPolicy).count() == 0
