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


def test_defaults_deficit_keys():
    p = svc.default_policy(KEY)
    assert p.source == "default"
    assert p.settings["deficit_adjust_ordinary_overtime"] is False
    assert p.settings["deficit_separate_non_working"] is True
    deficit_keys = {k for k in p.settings if k.startswith("deficit_") and k != "deficit_method"}
    assert deficit_keys == {"deficit_separate_non_working", "deficit_adjust_ordinary_overtime"}


def test_legacy_deficit_keys_dropped():
    out = svc.validate_settings(KEY, {
        "deficit_adjust_friday_work": True, "deficit_adjust_holiday_work": False,
        "deficit_separate_friday": False, "deficit_separate_leave": True,
        "deficit_separate_mission": True,
    })
    for k in ("deficit_adjust_friday_work", "deficit_adjust_holiday_work",
              "deficit_separate_friday", "deficit_separate_leave",
              "deficit_separate_mission"):
        assert k not in out
    assert out["deficit_separate_non_working"] is True


def test_validation_rejects_unknown_and_bad_types():
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"bogus": True})
    with pytest.raises(svc.ReportPolicyError):
        svc.validate_settings(KEY, {"deficit_separate_non_working": "yes"})
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
    svc.create_policy_version(db, KEY, {"deficit_separate_non_working": False}, s1, "u1")
    svc.create_policy_version(db, KEY, {"deficit_adjust_ordinary_overtime": True}, s2, "u1")
    db.commit()
    mid = svc.resolve_report_policy(db, KEY, _g(1405, 3, 15))
    late = svc.resolve_report_policy(db, KEY, _g(1405, 9, 1))
    before = svc.resolve_report_policy(db, KEY, _g(1404, 12, 29))
    assert mid.source == "db" and mid.settings["deficit_separate_non_working"] is False
    assert late.settings["deficit_adjust_ordinary_overtime"] is True
    # نسخهٔ دوم از روی پیش‌فرض ساخته شده، نه از نسخهٔ اول
    assert late.settings["deficit_separate_non_working"] is True
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
    svc.create_policy_version(db, KEY, {"deficit_separate_non_working": False},
                              _g(1405, 1, 1), "u9")
    db.commit()
    log = db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "report_policy").one()
    assert log.changed_by == "u9" and "deficit_separate_non_working" in log.new_value


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


def test_old_saved_rows_get_new_keys_from_defaults(db):
    """نسخهٔ ذخیره‌شدهٔ schema 1 (بدون کلیدهای موظفی) همان رفتار قبلی را دارد."""
    db.add(ReportPolicy(
        report_key=KEY, effective_from_date=_g(1405, 1, 1), is_active=True,
        schema_version=1, settings={"deficit_adjust_friday_work": True},
    ))
    db.commit()
    p = svc.resolve_report_policy(db, KEY, _g(1405, 2, 1))
    assert p.source == "db"
    assert p.settings["duty_reduce_leave"] is True
    assert p.settings["duty_reduce_absent"] is False
    assert p.settings["deficit_separate_non_working"] is True
    assert "deficit_adjust_friday_work" not in p.settings


def test_schema3_saved_row_with_per_type_keys_still_resolves(db):
    db.add(ReportPolicy(
        report_key=KEY, effective_from_date=_g(1405, 1, 1), is_active=True,
        schema_version=3, settings={
            "deficit_separate_non_working": False,
            "deficit_separate_leave": True, "deficit_separate_friday": False,
        },
    ))
    db.commit()
    p = svc.resolve_report_policy(db, KEY, _g(1405, 2, 1))
    assert p.source == "db"
    assert p.settings["deficit_separate_non_working"] is False
    assert "deficit_separate_leave" not in p.settings


def test_schema4_saved_row_with_work_keys_still_resolves(db):
    """کلیدهای work_separate_* (تفکیک کارکرد، اکنون ثابت) در نسخهٔ قدیمی نادیده گرفته می‌شوند."""
    db.add(ReportPolicy(
        report_key=KEY, effective_from_date=_g(1405, 1, 1), is_active=True,
        schema_version=4, settings={
            "duty_reduce_absent": True,
            "work_separate_friday": False, "work_separate_holiday": False,
            "work_separate_rest": False, "work_separate_leave": True,
        },
    ))
    db.commit()
    p = svc.resolve_report_policy(db, KEY, _g(1405, 2, 1))
    assert p.source == "db"
    assert p.settings["duty_reduce_absent"] is True
    assert not any(k.startswith("work_separate_") for k in p.settings)


def test_work_keys_not_editable():
    assert not any(
        k.startswith("work_separate_") for k in svc.get_definition(KEY).editable_keys
    )
    titles = [g[0] for g in svc.LEGAL_OT_FIELD_GROUPS]
    assert "کارکرد" not in titles
    with pytest.raises(svc.ReportPolicyError):
        svc.apply_overrides(svc.default_policy(KEY), {"work_separate_rest": True})


def test_apply_overrides_is_temporary(db):
    base = svc.resolve_report_policy(db, KEY, date(2026, 1, 1))
    out = svc.apply_overrides(base, {"duty_reduce_absent": True, "duty_reduce_rest": False})
    assert out.source == "override" and out.label == "تنظیمات موقت"
    assert out.settings["duty_reduce_absent"] is True
    assert out.settings["duty_reduce_rest"] is False
    assert base.settings["duty_reduce_absent"] is False
    assert svc.apply_overrides(base, None) is base
    assert db.query(ReportPolicy).count() == 0


def test_apply_overrides_rejects_non_editable_and_bad_values():
    base = svc.default_policy(KEY)
    with pytest.raises(svc.ReportPolicyError):
        svc.apply_overrides(base, {"deficit_method": "legacy"})
    with pytest.raises(svc.ReportPolicyError):
        svc.apply_overrides(base, {"bogus": True})
    with pytest.raises(svc.ReportPolicyError):
        svc.apply_overrides(base, {"duty_reduce_leave": "yes"})


def test_update_version_changes_settings_and_audits(db):
    row = svc.create_policy_version(db, KEY, {}, _g(1405, 1, 1), "u1")
    db.commit()
    svc.update_policy_version(
        db, KEY, row.id, {"duty_reduce_absent": True}, "u2", notes="اصلاح",
    )
    db.commit()
    p = svc.resolve_report_policy(db, KEY, _g(1405, 2, 1))
    assert p.policy_id == row.id and p.settings["duty_reduce_absent"] is True
    assert db.query(ReportPolicy).one().notes == "اصلاح"
    log = db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "report_policy",
        PolicyAuditLog.action == "UPDATE_VERSION").one()
    assert log.changed_by == "u2"
    with pytest.raises(svc.ReportPolicyError):
        svc.update_policy_version(db, KEY, row.id, {"bogus": True})


def test_delete_latest_reopens_previous(db):
    first = svc.create_policy_version(db, KEY, {"deficit_separate_non_working": False},
                                      _g(1405, 1, 1))
    second = svc.create_policy_version(db, KEY, {}, _g(1405, 7, 1))
    db.commit()
    svc.delete_policy_version(db, KEY, second.id, "u3")
    db.commit()
    db.refresh(first)
    assert first.effective_to_date is None
    p = svc.resolve_report_policy(db, KEY, _g(1405, 9, 1))
    assert p.policy_id == first.id
    assert db.query(PolicyAuditLog).filter(
        PolicyAuditLog.action == "DELETE_VERSION").count() == 1
    with pytest.raises(svc.ReportPolicyError):
        svc.delete_policy_version(db, KEY, second.id)
    # همان تاریخ پس از حذف دوباره قابل ثبت است
    svc.create_policy_version(db, KEY, {}, _g(1405, 7, 1))
    db.commit()


def test_delete_middle_extends_previous_to_next(db):
    a = svc.create_policy_version(db, KEY, {}, _g(1405, 1, 1))
    b = svc.create_policy_version(db, KEY, {"duty_reduce_absent": True}, _g(1405, 4, 1))
    c = svc.create_policy_version(db, KEY, {}, _g(1405, 7, 1))
    db.commit()
    svc.delete_policy_version(db, KEY, b.id)
    db.commit()
    db.refresh(a)
    assert a.effective_to_date == _g(1405, 6, 31)
    assert svc.resolve_report_policy(db, KEY, _g(1405, 5, 1)).policy_id == a.id
    assert svc.resolve_report_policy(db, KEY, _g(1405, 8, 1)).policy_id == c.id


def test_delete_only_version_falls_back_to_default(db):
    row = svc.create_policy_version(db, KEY, {}, _g(1405, 1, 1))
    db.commit()
    svc.delete_policy_version(db, KEY, row.id)
    db.commit()
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
