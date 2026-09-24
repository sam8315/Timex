"""
Phase 1+2+3+4 tests — hourly mission data model, scoped policies, validation service, daily-status form, admin approve/reject.

Phase 1:
- model import / registration in Base.metadata
- table creation in the test database
- base DB constraints (start < end, valid status)
- four hourly-mission policy settings (save + read, independent)
- policy resolution (override → group → default)
- policies page renders the new card
- detail page shows scopes

Phase 2 (validation service):
- enabled / time order / working hours / holiday / non-working day
- overlap (P/A block; R/D do not; adjacent not overlap)
- same-day / duration / authorized mission minutes

Phase 3 (daily-status form integration):
- hourly_mission option in dropdown + conditional start/end fields
- POST branches to HourlyMission(status=P), never DailyStatus
- validation integration + M/R regression

Phase 4 (admin approve/reject):
- pending list on /admin/daily-status (no separate page)
- P → A with approved_by/approved_at
- P → R with approved_by/approved_at + optional rejection_reason
- invalid transitions (A/R/D) rejected server-side
- permission enforcement (require_admin + view_all_attendance)
- isolation: no DailyStatus / Attendance / LeaveRequest / LeaveBalance side effects
"""
from datetime import date, time, timedelta

import jdatetime
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models import Base, HourlyMission, HourlyMissionPolicy
from models.attendance import AttendancePolicy, AttendancePolicyDay
from models.daily_status import DailyStatus
from models.employee import Employee
from models.holiday import Holiday
from tests.conftest import test_engine
from .conftest import jalali_range, login_as

from web.services.hourly_mission_service import (
    resolve_hourly_mission_policy,
    get_effective_hourly_mission_settings,
    DEFAULT_HOURLY_MISSION_SETTINGS,
    validate_hourly_mission_request,
    compute_mission_minutes,
    get_authorized_mission_minutes,
    is_holiday_for_employee,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_super(client, make_user):
    creds = make_user(role="super_admin", balance_al=None)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def _cleanup_missions(db, user_id):
    db.query(HourlyMission).filter(
        HourlyMission.user_id == user_id).delete()
    db.commit()


def _cleanup_policies(db):
    """Delete all HourlyMissionPolicy rows created by tests."""
    try:
        db.rollback()
    except Exception:
        pass
    db.query(HourlyMissionPolicy).delete()
    db.commit()


def _seed_policy(db, employment_type_code="4", user_id=None, **kwargs):
    """Seed a HourlyMissionPolicy row directly for testing."""
    defaults = {
        "employment_type_code": employment_type_code,
        "user_id": user_id,
        "effective_from_date": date(2020, 1, 1),
        "effective_to_date": None,
        "is_active": True,
        "enabled": True,
        "working_hours_only": True,
        "allowed_on_holidays": False,
        "deduct_from_required_minutes": True,
    }
    defaults.update(kwargs)
    policy = HourlyMissionPolicy(**defaults)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


def _cleanup_attendance_policies(db, department="4"):
    """Delete group AttendancePolicy rows for a department (test isolation)."""
    try:
        db.rollback()
    except Exception:
        pass
    pids = [p[0] for p in db.query(AttendancePolicy.id).filter(
        AttendancePolicy.employment_type_code == department,
        AttendancePolicy.user_id.is_(None),
    ).all()]
    if pids:
        db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id.in_(pids)
        ).delete(synchronize_session=False)
        db.query(AttendancePolicy).filter(
            AttendancePolicy.id.in_(pids)
        ).delete(synchronize_session=False)
        db.commit()


def _seed_attendance_policy(
    db,
    department="4",
    start=date(2020, 1, 1),
    end=None,
    workday_start=time(7, 0),
    workday_end=time(15, 0),
    working_weekdays=(0, 1, 2, 3, 5),  # Mon-Thu, Sat (Friday=4 off by default)
):
    """Create AttendancePolicy + days for working-hours validation tests."""
    _cleanup_attendance_policies(db, department)
    policy = AttendancePolicy(
        employment_type_code=department,
        user_id=None,
        effective_from_date=start,
        effective_to_date=end,
        late_enabled=True,
        late_allowed_minutes=0,
        late_reference_mode="FIXED_TIME",
        early_leave_enabled=True,
        early_leave_allowed_minutes=0,
        early_leave_reference_mode="FIXED_TIME",
        is_active=True,
    )
    db.add(policy)
    db.flush()
    for weekday in range(7):
        is_working = weekday in working_weekdays
        db.add(AttendancePolicyDay(
            policy_id=policy.id,
            weekday=weekday,
            is_working_day=is_working,
            start_time=workday_start if is_working else None,
            end_time=workday_end if is_working else None,
        ))
    db.commit()
    return policy


def _cleanup_holidays(db):
    """Delete Holiday rows created by tests."""
    try:
        db.rollback()
    except Exception:
        pass
    db.query(Holiday).delete()
    db.commit()


# ---------------------------------------------------------------------------
# Model / table
# ---------------------------------------------------------------------------
def test_model_registered_in_metadata():
    assert HourlyMission.__tablename__ == "hourly_missions"
    assert "hourly_missions" in Base.metadata.tables
    assert HourlyMissionPolicy.__tablename__ == "hourly_mission_policies"
    assert "hourly_mission_policies" in Base.metadata.tables
    from models import HourlyMission as Exported
    assert Exported is HourlyMission
    from models import HourlyMissionPolicy as Exported2
    assert Exported2 is HourlyMissionPolicy


def test_table_created_in_test_db():
    tables = inspect(test_engine).get_table_names()
    assert "hourly_missions" in tables
    assert "hourly_mission_policies" in tables
    cols = {c["name"] for c in inspect(test_engine).get_columns("hourly_missions")}
    assert {
        "user_id", "mission_date", "start_time", "end_time", "reason",
        "destination", "status", "approved_by", "approved_at",
        "rejection_reason", "created_at", "updated_at",
    }.issubset(cols)
    policy_cols = {c["name"] for c in inspect(test_engine).get_columns("hourly_mission_policies")}
    assert {
        "employment_type_code", "user_id", "effective_from_date", "effective_to_date",
        "is_active", "enabled", "working_hours_only", "allowed_on_holidays",
        "deduct_from_required_minutes", "created_at", "updated_at",
    }.issubset(policy_cols)


def test_create_and_read_mission(db, make_user):
    user = make_user(role="user", balance_al=None)
    try:
        mission = HourlyMission(
            user_id=user["user_id"],
            mission_date=date(2027, 3, 22),
            start_time=time(8, 0),
            end_time=time(10, 30),
            reason="بازدید از اداره",
            destination="اداره مرکزی",
        )
        db.add(mission)
        db.commit()
        db.expire_all()

        row = db.query(HourlyMission).filter(
            HourlyMission.user_id == user["user_id"]).first()
        assert row is not None
        assert row.mission_date == date(2027, 3, 22)
        assert row.start_time == time(8, 0)
        assert row.end_time == time(10, 30)
        assert row.status == "P"
        assert row.status_name == "⏳ در انتظار"
        assert row.duration_minutes == 150
        assert row.duration_display == "2:30"
        assert row.destination == "اداره مرکزی"
        assert row.created_at is not None
        assert row.updated_at is not None
        assert row.to_dict()["duration_minutes"] == 150
    finally:
        _cleanup_missions(db, user["user_id"])


def test_start_after_end_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    try:
        mission = HourlyMission(
            user_id=user["user_id"],
            mission_date=date(2027, 3, 22),
            start_time=time(10, 0),
            end_time=time(9, 0),
        )
        db.add(mission)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.user_id == user["user_id"]).count() == 0
    finally:
        db.rollback()
        _cleanup_missions(db, user["user_id"])


def test_invalid_status_rejected(db, make_user):
    user = make_user(role="user", balance_al=None)
    try:
        mission = HourlyMission(
            user_id=user["user_id"],
            mission_date=date(2027, 3, 22),
            start_time=time(8, 0),
            end_time=time(9, 0),
            status="X",
        )
        db.add(mission)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.rollback()
        _cleanup_missions(db, user["user_id"])


def test_status_cycle_codes():
    from models.hourly_mission import STATUS_CODES
    assert set(STATUS_CODES) == {"P", "A", "R", "D"}


# ---------------------------------------------------------------------------
# Policy Resolution (resolve → override → group → default)
# ---------------------------------------------------------------------------
def test_group_policy_resolves_for_employee_without_override(db, make_user):
    _cleanup_policies(db)
    try:
        creds = make_user(role="user", balance_al=None, department="4")
        emp = db.query(Employee).filter(
            Employee.user_id == creds["user_id"]).first()
        assert emp is not None

        # Group policy (employment_type_code=4, no user_id)
        _seed_policy(db, employment_type_code="4",
                     enabled=True, working_hours_only=False,
                     allowed_on_holidays=True, deduct_from_required_minutes=False)

        target = date(2027, 3, 22)
        resolved = resolve_hourly_mission_policy(db, emp, target)
        assert resolved is not None
        assert resolved.user_id is None
        assert resolved.employment_type_code == "4"
        assert resolved.enabled is True
        assert resolved.working_hours_only is False
        assert resolved.allowed_on_holidays is True
        assert resolved.deduct_from_required_minutes is False
    finally:
        _cleanup_policies(db)


def test_override_beats_group_policy(db, make_user):
    _cleanup_policies(db)
    try:
        creds = make_user(role="user", balance_al=None, department="4")
        emp = db.query(Employee).filter(
            Employee.user_id == creds["user_id"]).first()

        # Group policy: enabled=True
        _seed_policy(db, employment_type_code="4", enabled=True)
        # Override for this user: enabled=False
        _seed_policy(db, employment_type_code="4",
                     user_id=creds["user_id"], enabled=False)

        target = date(2027, 3, 22)
        resolved = resolve_hourly_mission_policy(db, emp, target)
        assert resolved is not None
        assert resolved.user_id == creds["user_id"]
        assert resolved.enabled is False
    finally:
        _cleanup_policies(db)


def test_no_override_uses_group_policy(db, make_user):
    _cleanup_policies(db)
    try:
        creds = make_user(role="user", balance_al=None, department="4")
        emp = db.query(Employee).filter(
            Employee.user_id == creds["user_id"]).first()

        # Override for a different (real) user
        other_creds = make_user(role="user", balance_al=None, department="4")
        _seed_policy(db, employment_type_code="4",
                     user_id=other_creds["user_id"], enabled=False)
        # Group policy for this employee
        _seed_policy(db, employment_type_code="4", enabled=True)

        target = date(2027, 3, 22)
        resolved = resolve_hourly_mission_policy(db, emp, target)
        assert resolved is not None
        assert resolved.user_id is None
        assert resolved.enabled is True
    finally:
        _cleanup_policies(db)


def test_no_group_falls_back_to_defaults(db, make_user):
    _cleanup_policies(db)
    try:
        creds = make_user(role="user", balance_al=None, department="4")
        emp = db.query(Employee).filter(
            Employee.user_id == creds["user_id"]).first()

        # No policies seeded
        target = date(2027, 3, 22)
        resolved = resolve_hourly_mission_policy(db, emp, target)
        assert resolved is None

        settings = get_effective_hourly_mission_settings(db, emp, target)
        assert settings == DEFAULT_HOURLY_MISSION_SETTINGS
        assert settings["enabled"] is True
        assert settings["working_hours_only"] is True
        assert settings["allowed_on_holidays"] is False
        assert settings["deduct_from_required_minutes"] is True
    finally:
        _cleanup_policies(db)


def test_four_options_independent_storage_and_retrieval(db, make_user):
    _cleanup_policies(db)
    try:
        # Group A (code=1): one combination
        _seed_policy(db, employment_type_code="1",
                     enabled=True, working_hours_only=False,
                     allowed_on_holidays=True, deduct_from_required_minutes=False)

        # Group B (code=2): different combination
        _seed_policy(db, employment_type_code="2",
                     enabled=False, working_hours_only=True,
                     allowed_on_holidays=False, deduct_from_required_minutes=True)

        # Read back
        p1 = db.query(HourlyMissionPolicy).filter(
            HourlyMissionPolicy.employment_type_code == "1",
            HourlyMissionPolicy.user_id.is_(None)).first()
        assert p1.enabled is True
        assert p1.working_hours_only is False
        assert p1.allowed_on_holidays is True
        assert p1.deduct_from_required_minutes is False

        p2 = db.query(HourlyMissionPolicy).filter(
            HourlyMissionPolicy.employment_type_code == "2",
            HourlyMissionPolicy.user_id.is_(None)).first()
        assert p2.enabled is False
        assert p2.working_hours_only is True
        assert p2.allowed_on_holidays is False
        assert p2.deduct_from_required_minutes is True

        # They are independent
        assert p1.enabled != p2.enabled
        assert p1.working_hours_only != p2.working_hours_only
        assert p1.allowed_on_holidays != p2.allowed_on_holidays
        assert p1.deduct_from_required_minutes != p2.deduct_from_required_minutes
    finally:
        _cleanup_policies(db)


# ---------------------------------------------------------------------------
# UI: policies page renders card, detail page shows scopes
# ---------------------------------------------------------------------------
def test_policies_page_renders_hourly_mission_card(client, make_user):
    _as_super(client, make_user)
    resp = client.get("/admin/policies")
    assert resp.status_code == 200
    # Card is present
    assert "مأموریت ساعتی" in resp.text
    assert "/admin/policies/hourly-mission" in resp.text
    assert "مدیریت سیاست" in resp.text
    # Old global form is gone
    assert "hourly_mission_enabled" not in resp.text
    assert "تنظیمات کلی" not in resp.text  # old section title removed


def test_detail_page_shows_scopes_and_new_button(client, db, make_user):
    _cleanup_policies(db)
    try:
        _as_super(client, make_user)
        # Seed one group policy so table headers render
        _seed_policy(db, employment_type_code="4",
                     enabled=True, working_hours_only=True,
                     allowed_on_holidays=False, deduct_from_required_minutes=True)

        resp = client.get("/admin/policies/hourly-mission")
        assert resp.status_code == 200
        assert "سیاست‌های مأموریت ساعتی" in resp.text
        assert "رسمی" in resp.text  # dept type names shown
        assert "افزودن سیاست" in resp.text
        # Four setting columns in table header (rendered when policies exist)
        assert "ساعات موظفی فقط" in resp.text
        assert "روز تعطیل" in resp.text
        assert "کسر از موظفی" in resp.text
        # Group card + override section
        assert "قراردادی" in resp.text  # code=4 dept name
        assert "Override" in resp.text
    finally:
        _cleanup_policies(db)


def test_form_page_renders_four_switches(client, make_user):
    _as_super(client, make_user)
    resp = client.get("/admin/policies/hourly-mission/new")
    assert resp.status_code == 200
    assert "مأموریت ساعتی فعال است" in resp.text
    assert "مأموریت ساعتی فقط در ساعات موظفی مجاز است" in resp.text
    assert "مأموریت ساعتی در روز تعطیل مجاز است" in resp.text
    assert "مدت مأموریت ساعتی از موظفی کسر می‌شود" in resp.text


# ---------------------------------------------------------------------------
# Save via HTTP form
# ---------------------------------------------------------------------------
def test_save_creates_independent_four_options(client, db, make_user):
    _cleanup_policies(db)
    _as_super(client, make_user)
    try:
        resp = client.post(
            "/admin/policies/hourly-mission/save",
            data={
                "employment_type_code": "4",
                "user_id_override": "",
                "effective_from_date_str": "1405/01/01",
                "effective_to_date_str": "",
                "enabled": "on",
                # working_hours_only omitted → off
                # allowed_on_holidays omitted → off
                # deduct_from_required_minutes omitted → off
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=saved" in resp.headers["location"]

        db.expire_all()
        row = db.query(HourlyMissionPolicy).filter(
            HourlyMissionPolicy.employment_type_code == "4",
            HourlyMissionPolicy.user_id.is_(None),
            HourlyMissionPolicy.is_active == True,
        ).first()
        assert row is not None
        assert row.enabled is True
        assert row.working_hours_only is False
        assert row.allowed_on_holidays is False
        assert row.deduct_from_required_minutes is False

        # Second save for different group with different values
        resp2 = client.post(
            "/admin/policies/hourly-mission/save",
            data={
                "employment_type_code": "1",
                "user_id_override": "",
                "effective_from_date_str": "1405/01/01",
                "effective_to_date_str": "",
                # enabled omitted → off
                "working_hours_only": "on",
                "allowed_on_holidays": "on",
                # deduct omitted → off
            },
            follow_redirects=False,
        )
        assert resp2.status_code == 302
        db.expire_all()
        row2 = db.query(HourlyMissionPolicy).filter(
            HourlyMissionPolicy.employment_type_code == "1",
            HourlyMissionPolicy.user_id.is_(None),
            HourlyMissionPolicy.is_active == True,
        ).first()
        assert row2 is not None
        assert row2.enabled is False
        assert row2.working_hours_only is True
        assert row2.allowed_on_holidays is True
        assert row2.deduct_from_required_minutes is False
    finally:
        _cleanup_policies(db)


def test_non_super_admin_cannot_save_hourly_mission_policy(client, make_user):
    creds = make_user(role="admin", balance_al=None)
    login_as(client, creds["national_code"])
    resp = client.post(
        "/admin/policies/hourly-mission/save",
        data={
            "employment_type_code": "4",
            "effective_from_date_str": "1405/01/01",
            "enabled": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Phase 2 — Validation service
# ---------------------------------------------------------------------------
# Fixed dates (same convention as hourly leave tests):
# 2027-03-22 Mon, 2027-03-26 Fri, 2027-03-27 Sat
MONDAY = date(2027, 3, 22)
FRIDAY = date(2027, 3, 26)
SATURDAY = date(2027, 3, 27)


def _employee(db, make_user, department="4"):
    creds = make_user(role="user", balance_al=None, department=department)
    emp = db.query(Employee).filter(
        Employee.user_id == creds["user_id"]).first()
    assert emp is not None
    return emp, creds


def _validate(db, emp, day, start, end, **kwargs):
    return validate_hourly_mission_request(db, emp, day, start, end, **kwargs)


# --- Policy: enabled / override / group ---
def test_validation_rejects_when_disabled(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=False,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is False
        assert err is not None
        assert "فعال" in err
    finally:
        _cleanup_policies(db)


def test_validation_continues_when_enabled(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True
        assert err is None
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_validation_uses_override_enabled(db, make_user):
    _cleanup_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_policy(db, employment_type_code="4",
                     user_id=creds["user_id"], enabled=False)
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is False
        assert err is not None
    finally:
        _cleanup_policies(db)


def test_validation_uses_group_policy_when_no_override(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        other, other_creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4",
                     user_id=other_creds["user_id"], enabled=False)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# --- Time order ---
def test_validation_rejects_start_ge_end(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(11, 0), time(9, 0))
        assert ok is False
        assert err is not None
        assert "شروع" in err
        # equal times
        ok2, err2 = _validate(db, emp, MONDAY, time(9, 0), time(9, 0))
        assert ok2 is False
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_validation_accepts_valid_range(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True
        assert err is None
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# --- Working hours ---
def test_working_hours_inside_accepted(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=True, allowed_on_holidays=True)
        # 07:00–15:00 workday
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True, err
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_working_hours_partial_outside_rejected(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=True, allowed_on_holidays=True)
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        # starts before shift
        ok, err = _validate(db, emp, MONDAY, time(6, 0), time(8, 0))
        assert ok is False
        assert err is not None
        assert "شروع" in err
        # ends after shift
        ok2, err2 = _validate(db, emp, MONDAY, time(14, 0), time(16, 0))
        assert ok2 is False
        assert err2 is not None
        assert "پایان" in err2
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_working_hours_off_setting_allows_outside(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        ok, err = _validate(db, emp, MONDAY, time(16, 0), time(18, 0))
        assert ok is True, err
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# --- Holiday ---
def test_holiday_friday_rejected_when_not_allowed(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=False)
        ok, err = _validate(db, emp, FRIDAY, time(9, 0), time(11, 0))
        assert ok is False
        assert err is not None
        assert "تعطیل" in err or "جمعه" in err
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_holiday_table_rejected_when_not_allowed(db, make_user):
    _cleanup_policies(db)
    _cleanup_holidays(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=False)
        # national holiday on Monday
        db.add(Holiday(holiday_date=MONDAY, title="تست", is_national=True,
                       group_id=None))
        db.commit()
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is False
        assert err is not None
    finally:
        _cleanup_policies(db)
        _cleanup_holidays(db)


def test_holiday_allowed_continues_other_checks(db, make_user):
    _cleanup_policies(db)
    _cleanup_holidays(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        db.add(Holiday(holiday_date=MONDAY, title="تست", is_national=True,
                       group_id=None))
        db.commit()
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True, err
        # but disabled still rejects
        ok2, err2 = _validate(db, emp, MONDAY, time(11, 0), time(9, 0))
        assert ok2 is False
    finally:
        _cleanup_policies(db)
        _cleanup_holidays(db)
        _cleanup_attendance_policies(db)


def test_is_holiday_helper_friday_and_table(db, make_user):
    _cleanup_holidays(db)
    try:
        emp, _ = _employee(db, make_user)
        assert is_holiday_for_employee(db, emp, FRIDAY) is True
        assert is_holiday_for_employee(db, emp, MONDAY) is False
        db.add(Holiday(holiday_date=MONDAY, title="تست", is_national=True,
                       group_id=None))
        db.commit()
        assert is_holiday_for_employee(db, emp, MONDAY) is True
    finally:
        _cleanup_holidays(db)


# --- Non-working day ---
def test_non_working_day_rejected_when_working_hours_only(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=True, allowed_on_holidays=True)
        # Saturday is working in helper; make Thursday (weekday=3) non-working
        # Actually use a custom schedule: only Mon-Thu working; Sat non-working
        _seed_attendance_policy(db, department="4",
                                working_weekdays=(0, 1, 2, 3),  # no Sat
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        # Saturday 2027-03-27 is not Friday/holiday but non-working in policy
        ok, err = _validate(db, emp, SATURDAY, time(9, 0), time(11, 0))
        assert ok is False
        assert err is not None
        assert "کاری" in err
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_non_working_day_allowed_when_working_hours_off(db, make_user):
    _cleanup_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_attendance_policy(db, department="4",
                                working_weekdays=(0, 1, 2, 3),
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        ok, err = _validate(db, emp, SATURDAY, time(9, 0), time(11, 0))
        assert ok is True, err
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# --- Duration ---
def test_duration_minutes_computed(db, make_user):
    assert compute_mission_minutes(time(9, 0), time(11, 30)) == 150
    assert compute_mission_minutes(time(9, 0), time(9, 0)) == 0
    assert compute_mission_minutes(None, time(9, 0)) == 0


def test_authorized_mission_minutes_respects_deduct_flag(db):
    settings_on = {"deduct_from_required_minutes": True}
    settings_off = {"deduct_from_required_minutes": False}
    assert get_authorized_mission_minutes(
        settings_on, time(9, 0), time(11, 0)) == 120
    assert get_authorized_mission_minutes(
        settings_off, time(9, 0), time(11, 0)) == 0


# --- Overlap ---
def _seed_mission(db, user_id, day, start, end, status="P"):
    m = HourlyMission(
        user_id=user_id,
        mission_date=day,
        start_time=start,
        end_time=end,
        status=status,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_overlap_with_pending_rejected(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_mission(db, creds["user_id"], MONDAY, time(9, 0), time(11, 0),
                      status="P")
        # fully inside
        ok, err = _validate(db, emp, MONDAY, time(9, 30), time(10, 30))
        assert ok is False
        assert err is not None
        assert "تداخل" in err
        # contains existing
        ok2, err2 = _validate(db, emp, MONDAY, time(8, 0), time(12, 0))
        assert ok2 is False
        # start inside existing
        ok3, err3 = _validate(db, emp, MONDAY, time(10, 0), time(12, 0))
        assert ok3 is False
        # end inside existing
        ok4, err4 = _validate(db, emp, MONDAY, time(8, 0), time(10, 0))
        assert ok4 is False
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)
        _cleanup_missions(db, creds["user_id"])


def test_overlap_with_approved_rejected(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_mission(db, creds["user_id"], MONDAY, time(9, 0), time(11, 0),
                      status="A")
        ok, err = _validate(db, emp, MONDAY, time(10, 0), time(12, 0))
        assert ok is False
        assert err is not None
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)
        _cleanup_missions(db, creds["user_id"])


def test_overlap_rejected_or_cancelled_does_not_block(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_mission(db, creds["user_id"], MONDAY, time(9, 0), time(11, 0),
                      status="R")
        _seed_mission(db, creds["user_id"], MONDAY, time(13, 0), time(15, 0),
                      status="D")
        ok, err = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is True, err
        ok2, err2 = _validate(db, emp, MONDAY, time(13, 0), time(15, 0))
        assert ok2 is True, err2
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)
        _cleanup_missions(db, creds["user_id"])


def test_adjacent_ranges_not_overlap(db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        _seed_mission(db, creds["user_id"], MONDAY, time(9, 0), time(10, 0),
                      status="P")
        # 10:00-11:00 is adjacent (touching) — not overlap
        ok, err = _validate(db, emp, MONDAY, time(10, 0), time(11, 0))
        assert ok is True, err
        # 08:00-09:00 adjacent on the left
        ok2, err2 = _validate(db, emp, MONDAY, time(8, 0), time(9, 0))
        assert ok2 is True, err2
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)
        _cleanup_missions(db, creds["user_id"])


def test_overlap_exclude_mission_id(db, make_user):
    """exclude_mission_id allows re-validation of an existing mission (edit)."""
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, creds = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        existing = _seed_mission(db, creds["user_id"], MONDAY,
                                 time(9, 0), time(11, 0), status="P")
        # without exclude → blocked
        ok, _ = _validate(db, emp, MONDAY, time(9, 0), time(11, 0))
        assert ok is False
        # with exclude → ok
        ok2, err2 = _validate(db, emp, MONDAY, time(9, 0), time(11, 0),
                              exclude_mission_id=existing.id)
        assert ok2 is True, err2
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)
        _cleanup_missions(db, creds["user_id"])


# --- Same-day / cross-midnight ---
def test_cross_midnight_rejected_by_time_order(db, make_user):
    """23:00→01:00: start >= end on same mission_date → rejected."""
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        emp, _ = _employee(db, make_user)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        ok, err = _validate(db, emp, MONDAY, time(23, 0), time(1, 0))
        assert ok is False
        assert err is not None
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# ---------------------------------------------------------------------------
# Phase 3 — daily-status form integration
# ---------------------------------------------------------------------------
from urllib.parse import unquote


def _post_hourly(client, user_id, from_date, start="09:00", end="11:00",
                 to_date=None, description=""):
    data = {
        "user_id": user_id,
        "from_date": from_date,
        "status_code": "hourly_mission",
        "description": description,
        "start_time": start,
        "end_time": end,
    }
    if to_date is not None:
        data["to_date"] = to_date
    return client.post("/admin/daily-status/add", data=data,
                       follow_redirects=False)


def _future_weekday(target_gwd: int, not_gwd: int | None = None):
    """
    Future Jalali date string whose Gregorian weekday == target_gwd
    (and != not_gwd if given). Uses Gregorian weekday because
    is_holiday_for_employee checks date.weekday()==4 on the Gregorian date.
    jdatetime.weekday() uses Saturday=0 (Friday=6), so never use it here.
    """
    d = jdatetime.date.today() + timedelta(days=7)
    while True:
        gwd = d.togregorian().weekday()
        if gwd == target_gwd and (not_gwd is None or gwd != not_gwd):
            return d.strftime("%Y/%m/%d")
        d += timedelta(days=1)


def _future_non_friday():
    """Future date that is not Gregorian Friday (weekday!=4)."""
    d = jdatetime.date.today() + timedelta(days=7)
    while d.togregorian().weekday() == 4:
        d += timedelta(days=1)
    return d.strftime("%Y/%m/%d")


def _future_friday():
    """Future date that is Gregorian Friday (weekday==4)."""
    return _future_weekday(4)


# --- UI ---
def test_daily_status_page_shows_hourly_mission_option(client, make_user):
    _as_super(client, make_user)
    resp = client.get("/admin/daily-status")
    assert resp.status_code == 200
    assert 'value="hourly_mission"' in resp.text
    assert "مأموریت ساعتی" in resp.text
    # conditional time fields present and hidden by default
    assert 'id="start_time"' in resp.text
    assert 'id="end_time"' in resp.text
    assert 'id="hm-start-wrap"' in resp.text
    assert "d-none" in resp.text
    # JS toggle present
    assert "toggleHourlyMissionFields" in resp.text
    assert "hourly_mission" in resp.text


def test_daily_status_filter_does_not_include_hourly_mission(client, make_user):
    """Filter dropdown must stay DailyStatus-only (no hourly_mission)."""
    _as_super(client, make_user)
    resp = client.get("/admin/daily-status")
    assert resp.status_code == 200
    # add-form select has hourly_mission; filter select must not.
    # Count occurrences of value="hourly_mission" — should be exactly 1 (add form).
    assert resp.text.count('value="hourly_mission"') == 1


# --- Submission ---
def test_submit_hourly_mission_valid_creates_pending(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        day = _future_non_friday()
        resp = _post_hourly(client, target["user_id"], day,
                            start="09:00", end="11:00",
                            description="بازدید سایت")
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        assert "موفقیت" in unquote(resp.headers["location"])

        db.expire_all()
        m = db.query(HourlyMission).filter(
            HourlyMission.user_id == target["user_id"]).all()
        assert len(m) == 1
        assert m[0].status == "P"
        assert m[0].start_time == time(9, 0)
        assert m[0].end_time == time(11, 0)
        assert m[0].reason == "بازدید سایت"
        # Jalali → Gregorian roundtrip
        expected_g = jdatetime.datetime.strptime(day, "%Y/%m/%d").date().togregorian()
        assert m[0].mission_date == expected_g
        # NO DailyStatus created for hourly mission
        assert db.query(DailyStatus).filter(
            DailyStatus.user_id == target["user_id"]).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_missing_start_rejected(client, db, make_user):
    _cleanup_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        day = _future_non_friday()
        resp = client.post("/admin/daily-status/add", data={
            "user_id": target["user_id"],
            "from_date": day,
            "status_code": "hourly_mission",
            "end_time": "11:00",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.user_id == target["user_id"]).count() == 0
    finally:
        _cleanup_policies(db)


def test_submit_hourly_mission_start_ge_end_rejected(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        day = _future_non_friday()
        resp = _post_hourly(client, target["user_id"], day,
                            start="11:00", end="09:00")
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.user_id == target["user_id"]).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_cross_midnight_rejected(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        day = _future_non_friday()
        resp = _post_hourly(client, target["user_id"], day,
                            start="23:00", end="01:00")
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_policy_disabled_rejected(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=False,
                     working_hours_only=False, allowed_on_holidays=True)
        day = _future_non_friday()
        resp = _post_hourly(client, target["user_id"], day)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert "فعال" in unquote(resp.headers["location"])
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_outside_working_hours_rejected(client, db, make_user):
    _cleanup_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        emp = db.query(Employee).filter(
            Employee.user_id == target["user_id"]).one()
        assert emp.department == "4"
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=True, allowed_on_holidays=True)
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        # pick a working day (Mon-Thu, Sat) by Gregorian weekday
        d = jdatetime.date.today() + timedelta(days=7)
        while d.togregorian().weekday() in (4,):  # skip Friday
            d += timedelta(days=1)
        day = d.strftime("%Y/%m/%d")
        # 16:00-18:00 is after shift end 15:00
        resp = _post_hourly(client, target["user_id"], day,
                            start="16:00", end="18:00")
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_holiday_rejected(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_holidays(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=False)
        day = _future_friday()
        resp = _post_hourly(client, target["user_id"], day)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert "تعطیل" in unquote(resp.headers["location"])
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)
        _cleanup_holidays(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_overlap_rejected(client, db, make_user):
    _cleanup_policies(db)
    _cleanup_attendance_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        _seed_policy(db, employment_type_code="4", enabled=True,
                     working_hours_only=False, allowed_on_holidays=True)
        day = _future_non_friday()
        # first OK
        r1 = _post_hourly(client, target["user_id"], day,
                          start="09:00", end="11:00")
        assert "success=" in r1.headers["location"]
        # overlapping second → reject
        r2 = _post_hourly(client, target["user_id"], day,
                          start="10:00", end="12:00")
        assert "error=" in r2.headers["location"]
        assert "تداخل" in unquote(r2.headers["location"])
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.user_id == target["user_id"]).count() == 1
    finally:
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_submit_hourly_mission_multi_day_rejected(client, db, make_user):
    _cleanup_policies(db)
    try:
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        from_str = _future_non_friday()
        # to_date different from from_date
        to_str = (jdatetime.datetime.strptime(from_str, "%Y/%m/%d").date()
                  + timedelta(days=2)).strftime("%Y/%m/%d")
        resp = _post_hourly(client, target["user_id"], from_str,
                            to_date=to_str)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        assert "یک روز" in unquote(resp.headers["location"])
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)


def test_submit_hourly_mission_unknown_employee_rejected(client, db, make_user):
    _cleanup_policies(db)
    try:
        _as_super(client, make_user)
        day = _future_non_friday()
        resp = _post_hourly(client, "NO-SUCH-USER", day)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).count() == 0
    finally:
        _cleanup_policies(db)


# --- Regression: M and R still work ---
def test_daily_mission_still_works(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    day = _future_non_friday()
    resp = client.post("/admin/daily-status/add", data={
        "user_id": target["user_id"],
        "from_date": day,
        "status_code": "M",
        "description": "مأموریت روزانه",
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    rows = db.query(DailyStatus).filter(
        DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1
    assert rows[0].status_code == "M"
    # no HourlyMission from M submission
    assert db.query(HourlyMission).filter(
        HourlyMission.user_id == target["user_id"]).count() == 0


def test_rest_still_works(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    day = _future_non_friday()
    resp = client.post("/admin/daily-status/add", data={
        "user_id": target["user_id"],
        "from_date": day,
        "status_code": "R",
        "description": "",
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    rows = db.query(DailyStatus).filter(
        DailyStatus.user_id == target["user_id"]).all()
    assert len(rows) == 1
    assert rows[0].status_code == "R"
    assert db.query(HourlyMission).filter(
        HourlyMission.user_id == target["user_id"]).count() == 0


def test_hourly_mission_ignores_extra_time_fields_for_m(client, db, make_user):
    """When status is M, start/end times must be ignored (no HourlyMission)."""
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    day = _future_non_friday()
    resp = client.post("/admin/daily-status/add", data={
        "user_id": target["user_id"],
        "from_date": day,
        "status_code": "M",
        "description": "",
        "start_time": "09:00",
        "end_time": "17:00",
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert "success=" in resp.headers["location"]
    db.expire_all()
    assert db.query(HourlyMission).count() == 0
    assert db.query(DailyStatus).filter(
        DailyStatus.user_id == target["user_id"],
        DailyStatus.status_code == "M",
    ).count() == 1


# ---------------------------------------------------------------------------
# Phase 4 — approve / reject by admin
# ---------------------------------------------------------------------------
def _seed_pending_mission(db, user_id, day=None, start=time(9, 0), end=time(11, 0),
                          status="P", reason="بازدید"):
    if day is None:
        day_j = jdatetime.date.today() + timedelta(days=7)
        while day_j.togregorian().weekday() == 4:
            day_j += timedelta(days=1)
        day = day_j.togregorian()
    m = HourlyMission(
        user_id=user_id,
        mission_date=day,
        start_time=start,
        end_time=end,
        status=status,
        reason=reason,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _approve(client, mission_id, referer="/admin/daily-status"):
    return client.post(
        f"/admin/daily-status/hourly-missions/{mission_id}/approve",
        headers={"referer": referer},
        follow_redirects=False,
    )


def _reject(client, mission_id, reason="", referer="/admin/daily-status"):
    return client.post(
        f"/admin/daily-status/hourly-missions/{mission_id}/reject",
        data={"rejection_reason": reason},
        headers={"referer": referer},
        follow_redirects=False,
    )


def test_page_shows_hourly_missions_section(client, db, make_user):
    admin = _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        resp = client.get("/admin/daily-status")
        assert resp.status_code == 200
        assert "درخواست‌های مأموریت ساعتی" in resp.text
        assert "در انتظار تأیید" in resp.text
        assert "ساعت شروع" in resp.text
        assert "ساعت پایان" in resp.text
        # approve + reject buttons for pending
        assert f"/admin/daily-status/hourly-missions/{m.id}/approve" in resp.text
        assert f"/admin/daily-status/hourly-missions/{m.id}/reject" in resp.text
        assert "hmRejectModal" in resp.text
    finally:
        _cleanup_missions(db, target["user_id"])


def test_final_statuses_show_no_actions(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m_a = _seed_pending_mission(db, target["user_id"], status="A")
    m_r = _seed_pending_mission(db, target["user_id"], status="R")
    m_d = _seed_pending_mission(db, target["user_id"], status="D")
    try:
        resp = client.get("/admin/daily-status")
        assert resp.status_code == 200
        for mid in (m_a.id, m_r.id, m_d.id):
            assert f"/admin/daily-status/hourly-missions/{mid}/approve" not in resp.text
            assert f"/admin/daily-status/hourly-missions/{mid}/reject" not in resp.text
        assert "تأیید شده" in resp.text
        assert "رد شده" in resp.text
        assert "لغو شده" in resp.text
    finally:
        _cleanup_missions(db, target["user_id"])


def test_approve_pending_sets_approved_with_metadata(client, db, make_user):
    admin = _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        resp = _approve(client, m.id)
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        assert "تأیید" in unquote(resp.headers["location"])

        db.expire_all()
        row = db.query(HourlyMission).filter(HourlyMission.id == m.id).first()
        assert row.status == "A"
        assert row.approved_by == admin["user_id"]
        assert row.approved_at is not None
        assert row.rejection_reason is None
    finally:
        _cleanup_missions(db, target["user_id"])


def test_reject_pending_sets_rejected_with_reason(client, db, make_user):
    admin = _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        resp = _reject(client, m.id, reason="خارج از ساعات کاری")
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]

        db.expire_all()
        row = db.query(HourlyMission).filter(HourlyMission.id == m.id).first()
        assert row.status == "R"
        assert row.approved_by == admin["user_id"]
        assert row.approved_at is not None
        assert row.rejection_reason == "خارج از ساعات کاری"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_reject_without_reason_succeeds(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        resp = _reject(client, m.id, reason="")
        assert resp.status_code == 302
        assert "success=" in resp.headers["location"]
        db.expire_all()
        row = db.query(HourlyMission).filter(HourlyMission.id == m.id).first()
        assert row.status == "R"
        assert row.rejection_reason is None
    finally:
        _cleanup_missions(db, target["user_id"])


def test_approve_twice_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        first = _approve(client, m.id)
        assert "success=" in first.headers["location"]
        second = _approve(client, m.id)
        assert "error=" in second.headers["location"]
        assert "قبلاً بررسی" in unquote(second.headers["location"])
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "A"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_reject_approved_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"], status="A")
    try:
        resp = _reject(client, m.id)
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "A"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_approve_rejected_request_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"], status="R")
    try:
        resp = _approve(client, m.id)
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "R"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_reject_rejected_request_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"], status="R")
    try:
        resp = _reject(client, m.id)
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "R"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_approve_cancelled_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"], status="D")
    try:
        resp = _approve(client, m.id)
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "D"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_reject_cancelled_rejected(client, db, make_user):
    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"], status="D")
    try:
        resp = _reject(client, m.id)
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "D"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_approve_not_found_error(client, make_user):
    _as_super(client, make_user)
    resp = _approve(client, 999999)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert "یافت نشد" in unquote(resp.headers["location"])


def test_plain_user_cannot_approve(client, db, make_user):
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    creds = make_user(role="user", balance_al=None)
    login_as(client, creds["national_code"])
    try:
        resp = _approve(client, m.id)
        assert resp.status_code == 403
        resp2 = _reject(client, m.id, reason="x")
        assert resp2.status_code == 403
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "P"
    finally:
        _cleanup_missions(db, target["user_id"])


def test_admin_without_permission_cannot_approve(client, db, make_user):
    """Admin role with view_all_attendance revoked → 403 (override layer)."""
    from models.user_permission import UserPermission

    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    admin = make_user(role="admin", balance_al=None)
    db.add(UserPermission(
        user_id=admin["user_id"],
        permission="view_all_attendance",
        granted=False,
    ))
    db.commit()
    login_as(client, admin["national_code"])
    try:
        resp = _approve(client, m.id)
        assert resp.status_code == 403
        db.expire_all()
        assert db.query(HourlyMission).filter(
            HourlyMission.id == m.id).first().status == "P"
    finally:
        db.query(UserPermission).filter(
            UserPermission.user_id == admin["user_id"]).delete()
        db.commit()
        _cleanup_missions(db, target["user_id"])


def test_approve_creates_no_daily_status_or_attendance_or_leave(client, db, make_user):
    """Approve must not touch DailyStatus / Attendance / LeaveRequest / LeaveBalance."""
    from models.attendance import Attendance
    from models.leave_balance import LeaveBalance
    from models.leave_request import LeaveRequest

    _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    m = _seed_pending_mission(db, target["user_id"])
    try:
        before_ds = db.query(DailyStatus).filter(
            DailyStatus.user_id == target["user_id"]).count()
        before_att = db.query(Attendance).filter(
            Attendance.user_id == target["user_id"]).count()
        before_lr = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == target["user_id"]).count()
        before_lb = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == target["user_id"]).count()

        resp = _approve(client, m.id)
        assert "success=" in resp.headers["location"]

        db.expire_all()
        assert db.query(DailyStatus).filter(
            DailyStatus.user_id == target["user_id"]).count() == before_ds
        assert db.query(Attendance).filter(
            Attendance.user_id == target["user_id"]).count() == before_att
        assert db.query(LeaveRequest).filter(
            LeaveRequest.user_id == target["user_id"]).count() == before_lr
        assert db.query(LeaveBalance).filter(
            LeaveBalance.user_id == target["user_id"]).count() == before_lb
        row = db.query(HourlyMission).filter(HourlyMission.id == m.id).first()
        assert row.status == "A"
    finally:
        _cleanup_missions(db, target["user_id"])
