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
    assert r.status_code == 200 and "تهاتر اضافه‌کار عادی با کسر کار ماهانه" in r.text
    assert "مبنای محاسبهٔ کسر کار" in r.text
    assert "کل کارکرد" in r.text and "کارکرد روز کاری" in r.text
    assert 'id="deficit_separate_non_working_1"' in r.text


def test_save_creates_version_and_audit(client, db, make_user):
    _super(client, make_user)
    r = client.post("/admin/policies/reports/legal-overtime/save", data={
        "effective_from": "1405/08/01", "deficit_separate_non_working": "1",
        "deficit_adjust_ordinary_overtime": "on",
    }, follow_redirects=False)
    assert r.status_code == 302 and "success=saved" in r.headers["location"]
    row = db.query(ReportPolicy).one()
    assert row.settings["deficit_separate_non_working"] is True
    assert row.settings["deficit_adjust_ordinary_overtime"] is True
    assert "deficit_separate_friday" not in row.settings
    assert db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "report_policy").count() == 1


def test_save_handles_duty_fields_and_ignores_work_fields(client, db, make_user):
    _super(client, make_user)
    r = client.post("/admin/policies/reports/legal-overtime/save", data={
        "effective_from": "1405/08/01",
        "duty_reduce_leave": "on",
        "duty_reduce_absent": "on",
        "work_separate_rest": "1",
        "work_separate_holiday": "0",
        "deficit_separate_non_working": "0",
    }, follow_redirects=False)
    assert "success=saved" in r.headers["location"]
    s = db.query(ReportPolicy).one().settings
    assert s["duty_reduce_leave"] is True and s["duty_reduce_absent"] is True
    assert s["duty_reduce_rest"] is False
    assert not any(k.startswith("work_separate_") for k in s)
    # مبنای کسر کار «کل کارکرد»
    assert s["deficit_separate_non_working"] is False


def test_policy_page_has_no_work_card(client, make_user):
    _super(client, make_user)
    for url in ("/admin/policies/reports/legal-overtime", "/reports/monthly-legal-ot"):
        r = client.get(url)
        assert r.status_code == 200
        assert "work_separate_" not in r.text
        assert "جزو کارکرد" not in r.text


def test_legal_ot_page_has_settings_modal(client, make_user):
    _super(client, make_user)
    r = client.get("/reports/monthly-legal-ot")
    assert r.status_code == 200
    assert 'id="legalOtSettingsModal"' in r.text
    assert 'name="ovr_duty_reduce_absent"' in r.text
    assert 'name="ovr_duty_reduce_no_punch_future"' in r.text


def test_save_and_override_future_no_punch_separately(client, db, make_user):
    from web.routes.reports import _legal_ot_overrides

    _super(client, make_user)
    r = client.post("/admin/policies/reports/legal-overtime/save", data={
        "effective_from": "1405/08/01",
        "duty_reduce_no_punch_future": "on",
    }, follow_redirects=False)
    assert "success=saved" in r.headers["location"]
    s = db.query(ReportPolicy).one().settings
    assert s["duty_reduce_no_punch"] is False
    assert s["duty_reduce_no_punch_future"] is True

    page = client.get("/admin/policies/reports/legal-overtime")
    assert "بدون تردد (روزهای گذشته)" in page.text
    assert "بدون تردد (امروز و آینده)" in page.text

    overrides = _legal_ot_overrides({"ovr": "1", "ovr_duty_reduce_no_punch_future": "1"})
    assert overrides["duty_reduce_no_punch_future"] is True
    assert overrides["duty_reduce_no_punch"] is False


def test_override_query_string_roundtrip():
    from web.routes.reports import _legal_ot_override_qs, _legal_ot_overrides

    assert _legal_ot_overrides({}) is None
    assert _legal_ot_overrides({"ovr": "0", "ovr_duty_reduce_absent": "1"}) is None
    overrides = _legal_ot_overrides({"ovr": "1", "ovr_duty_reduce_absent": "1"})
    assert overrides["duty_reduce_absent"] is True
    assert overrides["duty_reduce_leave"] is False
    qs = _legal_ot_override_qs(overrides)
    parsed = dict(p.split("=") for p in qs.lstrip("&").split("&"))
    assert _legal_ot_overrides(parsed) == overrides


def test_exports_forward_overrides(client, make_user, monkeypatch):
    import web.routes.reports as reports_routes

    seen = []

    def fake(target_user_id, year, month, overrides=None):
        seen.append(overrides)
        raise ValueError("stop")

    monkeypatch.setattr(reports_routes, "_monthly_legal_ot_report_data", fake)
    _super(client, make_user)
    # ovr_work_separate_rest از لینک‌های قدیمی بی‌اثر است
    qs = ("target_user_id=1&year=1405&month=1&ovr=1&ovr_duty_reduce_absent=1"
          "&ovr_work_separate_rest=1")
    for path in ("export-excel", "export-pdf"):
        r = client.get(f"/reports/monthly-legal-ot/{path}?{qs}", follow_redirects=False)
        assert r.status_code == 302
    r = client.get("/reports/monthly-legal-ot/export-excel?target_user_id=1&year=1405&month=1",
                   follow_redirects=False)
    for overrides in seen[:2]:
        assert overrides["duty_reduce_absent"] is True
        assert "work_separate_rest" not in overrides
    assert seen[2] is None


def test_group_generate_redirect_keeps_overrides(client, make_user):
    _super(client, make_user)
    r = client.post("/reports/monthly-legal-ot", data={
        "year": "1405", "month": "1", "employment_type": "all",
        "ovr": "1", "ovr_duty_reduce_absent": "1",
    }, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "/print-group?" in loc and "ovr=1" in loc
    assert "ovr_duty_reduce_absent=1" in loc


def test_edit_and_delete_version(client, db, make_user):
    _super(client, make_user)
    client.post("/admin/policies/reports/legal-overtime/save", data={
        "effective_from": "1405/08/01", "duty_reduce_leave": "on",
    }, follow_redirects=False)
    row = db.query(ReportPolicy).one()

    page = client.get(f"/admin/policies/reports/legal-overtime?edit={row.id}")
    assert page.status_code == 200
    assert f"/legal-overtime/{row.id}/update" in page.text
    assert f"/legal-overtime/{row.id}/delete" in page.text

    r = client.post(f"/admin/policies/reports/legal-overtime/{row.id}/update", data={
        "notes": "ویرایش‌شده", "duty_reduce_absent": "on", "duty_reduce_rest": "on",
    }, follow_redirects=False)
    assert "success=updated" in r.headers["location"]
    db.expire_all()
    row = db.query(ReportPolicy).one()
    assert row.settings["duty_reduce_absent"] is True
    assert row.settings["duty_reduce_rest"] is True
    assert row.settings["duty_reduce_leave"] is False
    assert row.notes == "ویرایش‌شده"

    r = client.post(f"/admin/policies/reports/legal-overtime/{row.id}/delete",
                    follow_redirects=False)
    assert "success=deleted" in r.headers["location"]
    db.expire_all()
    assert db.query(ReportPolicy).one().is_active is False

    r = client.post(f"/admin/policies/reports/legal-overtime/{row.id}/delete",
                    follow_redirects=False)
    assert "error=" in r.headers["location"]


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
