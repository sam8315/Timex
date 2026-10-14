"""سیاست گزارش: اعتبارسنجی، resolve، نسخه‌گذاری و جداسازی گزارش‌ها."""
from datetime import date

import jdatetime
import pytest

from models.policy import PolicyAuditLog
from models.report_policy import ReportPolicy
from web.services import report_policy_service as svc

KEY = svc.LEGAL_OVERTIME_MONTHLY


def _g(y, m, d):
    return jdatetime.date(y, m, d).togregorian()


@pytest.fixture(autouse=True)
def _clean(db):
    def wipe():
        db.rollback()
        db.query(ReportPolicy).delete()
        db.query(PolicyAuditLog).filter(
            PolicyAuditLog.entity_type == "report_policy"
        ).delete()
        db.commit()
    wipe()
    yield
    wipe()


def test_defaults_all_adjustments_false():
    p = svc.default_policy(KEY)
    assert p.source == "default"
    for k in ("deficit_adjust_ordinary_overtime", "deficit_adjust_holiday_work",
              "deficit_adjust_friday_work"):
        assert p.settings[k] is False


def test_validation_rejects_unknown_and_bad_types():
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"bogus": True})
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"deficit_adjust_friday_work": "yes"})
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"deficit_method": "x"})
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"exclude_future_days": False})
    with pytest.raises(svc.ReportPolicyError):
        svc.get_definition("unknown_report")


def test_resolve_without_row_is_default(db):
    assert svc.resolve_report_policy(db, KEY, date(2026, 1, 1)).source == "default"


def test_create_and_resolve_by_date(db):
    s1 = _g(1405, 1, 1)
    s2 = _g(1405, 7, 1)
    svc.create_policy_version(db, KEY, {"deficit_adjust_friday_work": True}, s1, "u1")
    svc.create_policy_version(db, KEY, {"deficit_adjust_holiday_work": True}, s2, "u1")
    db.commit()
    mid = svc.resolve_report_policy(db, KEY, _g(1405, 3, 15))
    late = svc.resolve_report_policy(db, KEY, _g(1405, 9, 1))
    before = svc.resolve_report_policy(db, KEY, _g(1404, 12, 29))
    assert mid.source == "db" and mid.settings["deficit_adjust_friday_work"] is True
    assert late.settings["deficit_adjust_holiday_work"] is True
    # نسخهٔ دوم از روی پیش‌فرض ساخته شده، نه از نسخهٔ اول
    assert late.settings["deficit_adjust_friday_work"] is False
    assert before.source == "default"
    first = db.query(ReportPolicy).filter(ReportPolicy.effective_from_date == s1).one()
    assert first.effective_to_date == _g(1405, 6, 31)


def test_rejects_non_month_start_and_overlap(db):
    with pytest.raises(svc.ReportPolicyError):
        svc.create_policy_version(db, KEY, {}, _g(1405, 1, 5))
    svc.create_policy_version(db, KEY, {}, _g(1405, 4, 1))
    db.commit()
    with pytest.raises(svc.ReportPolicyError):
        svc.create_policy_version(db, KEY, {}, _g(1405, 4, 1))
    with pytest.raises(svc.ReportPolicyError):
        svc.create_policy_version(db, KEY, {}, _g(1405, 2, 1))


def test_audit_log_written(db):
    svc.create_policy_version(db, KEY, {"deficit_adjust_friday_work": True},
                              _g(1405, 1, 1), "u9")
    db.commit()
    log = db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "report_policy").one()
    assert log.changed_by == "u9" and "deficit_adjust_friday_work" in log.new_value


def test_reports_are_isolated(db, monkeypatch):
    """سیاست یک report_key روی کلید دیگر اثر نمی‌گذارد."""
    other = svc.ReportPolicyDefinition(
        key="other_report", label="x", schema_version=1,
        defaults={"flag": False}, editable_keys=("flag",),
        validate=lambda raw: {"flag": bool(raw.get("flag", False))},
    )
    monkeypatch.setitem(svc.REPORT_DEFINITIONS, "other_report", other)
    svc.create_policy_version(db, "other_report", {"flag": True}, _g(1405, 1, 1))
    db.commit()
    assert svc.resolve_report_policy(db, "other_report", _g(1405, 2, 1)).settings["flag"]
    assert svc.resolve_report_policy(db, KEY, _g(1405, 2, 1)).source == "default"


def test_month_end_handles_esfand():
    assert svc.month_end(1405, 1) == _g(1405, 1, 31)
    assert svc.month_end(1405, 12) == _g(1405, 12, 29)


def test_payroll_shadow_path_uses_report_policy_and_reference():
    """مسیر استعلاجی نامشخص در friday_adapter همان سیاست و زمان مرجع را می‌گیرد."""
    from datetime import datetime
    from web.services.payroll.friday_adapter import _payroll_summary

    d = date(2024, 3, 16)
    day = {
        'date': d, 'work_hours': 0.0, 'is_friday': False, 'is_day_off': False,
        'is_holiday': False, 'person_status': 'N', 'daily_duty': 7 + 20 / 60,
        'sick_payment_unknown': True,
    }
    report = {
        'days': [day],
        'summary': {'duty_hours': 7 + 20 / 60, 'total_work_hours': 0.0},
        'reference_at': datetime(2024, 3, 20, 12, 0),
        'report_policy': svc.default_policy(KEY),
    }
    out = _payroll_summary(report)
    assert out['monthly_deficit'] == pytest.approx(7 + 20 / 60, abs=0.02)
    report2 = dict(report, reference_at=datetime(2024, 3, 10, 12, 0))
    report2['days'] = [dict(day)]
    assert _payroll_summary(report2)['monthly_deficit'] == 0
