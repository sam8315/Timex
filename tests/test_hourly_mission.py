"""
Phase 1+2+3+4+5+6A+6B tests — hourly mission data model, scoped policies, validation service, daily-status form, admin approve/reject, required-minutes integration, UI display, PDF/Excel/Raw exports.

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

Phase 5 (required minutes integration):
- approved HM deducts from compute_required_minutes_for_range when policy on
- policy off / non-approved status → no deduction
- clamp at 0; full-day M / leave / rest / holiday stay 0
- multiple same-day missions sum; exact boundary → 0
- no side effects on LeaveBalance / LeaveRequest / DailyStatus / HL

Phase 6A (display in existing reports/UI):
- format_hm_display exact strings (single + multiple ranges)
- get_approved_hourly_missions_for_display: only status=A; independent of deduct policy
- badge on /attendance, /admin/attendance, /admin/attendance/user, monthly reports
- pending not shown as approved time in attendance UI
- daily-status still shows all statuses (management view)
- rendering does not alter required minutes / side-effect rows

Phase 6B (PDF / Excel / Raw Report):
- approved only (P/R/D excluded) in raw dataset + exports
- format_hm_display / detail (start-end-minutes) in leave column
- no synthetic punches; person_status cascade unchanged (M stays M)
- multiple missions sorted by start_time; date-range filtered
- group report: no mix across employees; bulk query (no N+1)
- display independent of deduct policy; no required-minutes recompute

Phase 6C (monthly reports Effective Required audit):
- detailed/full generator uses the shared compute_effective_required_minutes_for_day
- approved HM (policy on) deducts from monthly Required; policy off → display only
- DailyStatus M / rest / all full-day leave types (incl. CW) → zero duty
- policy non-working days render as تعطیل (not غایب); summary mission_days
- summary totals, attendance-only morning/evening/night, weekly overtime boundary
- both routes show Required from the same generator; no (7:20) labels
- monthly-stats regression: no hourly mission text
- daily-status HM time fields use the HL time-input markup
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
    get_approved_hourly_mission_minutes,
    get_approved_hourly_missions_for_display,
    format_hm_display,
    is_holiday_for_employee,
)
from web.services.attendance_policy_service import (
    compute_required_minutes_for_range,
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


# ---------------------------------------------------------------------------
# Phase 5 — Approved hourly mission → compute_required_minutes_for_range
# ---------------------------------------------------------------------------
# Base attendance policy in these tests: Mon-Thu+Sat 07:00–15:00 → 480 min.
# MONDAY = 2027-03-22 (working day). HM 09:00–11:00 = 120 min.


def _seed_hm_and_base(db, make_user, **policy_kwargs):
    """Employee + attendance policy (480min) + optional HM policy.
    Returns (emp, creds). Always cleans HM/attendance policies first."""
    _cleanup_policies(db)
    _cleanup_attendance_policies(db, "4")
    emp, creds = _employee(db, make_user)
    _seed_attendance_policy(db, department="4",
                            workday_start=time(7, 0),
                            workday_end=time(15, 0))
    _seed_policy(db, employment_type_code="4", **policy_kwargs)
    return emp, creds


def _hm_required(db, emp, day=MONDAY, **kwargs):
    defaults = dict(
        rest_dates=set(), holiday_dates={}, leaves_by_date={},
        mission_dates=set(),
    )
    defaults.update(kwargs)
    return compute_required_minutes_for_range(
        db=db, employee=emp, start_date=day, end_date=day, **defaults
    )


def test_hm_approved_deducts_from_required(db, make_user):
    """Base 480 − approved HM 120 = 360."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        m = _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
        assert _hm_required(db, emp) == 360
        assert get_approved_hourly_mission_minutes(db, emp, MONDAY, MONDAY) == {
            MONDAY: 120
        }
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_policy_deduct_disabled_no_reduction(db, make_user):
    """deduct_from_required_minutes=False → full 480 despite approved HM."""
    emp, creds = _seed_hm_and_base(
        db, make_user, deduct_from_required_minutes=False
    )
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp) == 480
        assert get_approved_hourly_mission_minutes(db, emp, MONDAY, MONDAY) == {}
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


@pytest.mark.parametrize("status", ["P", "R", "D"])
def test_hm_non_approved_status_no_deduction(db, make_user, status):
    """Only status='A' reduces required minutes."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status=status)
        assert _hm_required(db, emp) == 480
        assert get_approved_hourly_mission_minutes(db, emp, MONDAY, MONDAY) == {}
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_deduct_clamped_at_zero(db, make_user):
    """HM longer than required → 0, never negative (600 − 480 → 0)."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(7, 0), end=time(17, 0),  # 600 min
                              status="A")
        assert _hm_required(db, emp) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_on_full_day_mission_stays_zero(db, make_user):
    """Full-day DailyStatus M → base 0; approved HM must not make it positive."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp, mission_dates={MONDAY}) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_on_leave_stays_zero(db, make_user):
    """Full-day leave → base 0; approved HM still 0 (never negative)."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp, leaves_by_date={MONDAY: "AL"}) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_on_rest_stays_zero(db, make_user):
    """Rest day → base 0; approved HM still 0."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp, rest_dates={MONDAY}) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_on_holiday_stays_zero(db, make_user):
    """Holiday → base 0; approved HM still 0."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp, holiday_dates={MONDAY: "تعطیل"}) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_multiple_same_day_summed(db, make_user):
    """Two approved missions same day: 60 + 90 = 150 → 480 − 150 = 330."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(8, 0), end=time(9, 0),
                              status="A")  # 60
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(10, 0), end=time(11, 30),
                              status="A")  # 90
        hm = get_approved_hourly_mission_minutes(db, emp, MONDAY, MONDAY)
        assert hm == {MONDAY: 150}
        assert _hm_required(db, emp) == 330
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_exact_boundary_zero(db, make_user):
    """HM duration == required (480) → 0 exactly."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(7, 0), end=time(15, 0),  # 480
                              status="A")
        assert _hm_required(db, emp) == 0
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_not_on_date_in_range_ignored(db, make_user):
    """Mission on Tuesday does not affect Monday required."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=date(2027, 3, 23),
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        assert _hm_required(db, emp) == 480
        assert get_approved_hourly_mission_minutes(db, emp, MONDAY, MONDAY) == {}
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_and_hl_both_deduct(db, make_user):
    """HL 60 + HM 60 → 480 − 120 = 360 (same clamp pipeline)."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(10, 0),
                              status="A")  # 60
        result = compute_required_minutes_for_range(
            db=db, employee=emp, start_date=MONDAY, end_date=MONDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            mission_dates=set(),
            hourly_leave_minutes_by_date={MONDAY: 60},
            hourly_mission_minutes_by_date={MONDAY: 60},
        )
        assert result == 360
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_auto_fetch_when_param_none(db, make_user):
    """Passing hourly_mission_minutes_by_date=None still deducts (single source)."""
    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        result = compute_required_minutes_for_range(
            db=db, employee=emp, start_date=MONDAY, end_date=MONDAY,
            rest_dates=set(), holiday_dates={}, leaves_by_date={},
            mission_dates=set(),
            # hourly_mission_minutes_by_date omitted → auto-fetch
        )
        assert result == 360
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


def test_hm_compute_creates_no_side_effect_rows(db, make_user):
    """compute_required_minutes_for_range with approved HM must not write
    DailyStatus / Attendance / LeaveRequest / LeaveBalance / HL rows."""
    from models.attendance import Attendance
    from models.leave_balance import LeaveBalance
    from models.leave_request import LeaveRequest

    emp, creds = _seed_hm_and_base(db, make_user)
    try:
        _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                              start=time(9, 0), end=time(11, 0),
                              status="A")
        before_ds = db.query(DailyStatus).filter(
            DailyStatus.user_id == creds["user_id"]).count()
        before_att = db.query(Attendance).filter(
            Attendance.user_id == creds["user_id"]).count()
        before_lr = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == creds["user_id"]).count()
        before_lb = db.query(LeaveBalance).filter(
            LeaveBalance.user_id == creds["user_id"]).count()
        before_hl = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == creds["user_id"],
            LeaveRequest.leave_type == "HL",
        ).count()

        assert _hm_required(db, emp) == 360

        db.expire_all()
        assert db.query(DailyStatus).filter(
            DailyStatus.user_id == creds["user_id"]).count() == before_ds
        assert db.query(Attendance).filter(
            Attendance.user_id == creds["user_id"]).count() == before_att
        assert db.query(LeaveRequest).filter(
            LeaveRequest.user_id == creds["user_id"]).count() == before_lr
        assert db.query(LeaveBalance).filter(
            LeaveBalance.user_id == creds["user_id"]).count() == before_lb
        assert db.query(LeaveRequest).filter(
            LeaveRequest.user_id == creds["user_id"],
            LeaveRequest.leave_type == "HL",
        ).count() == before_hl
        # HM row itself unchanged (still A)
        row = db.query(HourlyMission).filter(
            HourlyMission.user_id == creds["user_id"]).first()
        assert row.status == "A"
    finally:
        _cleanup_missions(db, creds["user_id"])
        _cleanup_policies(db)
        _cleanup_attendance_policies(db)


# ---------------------------------------------------------------------------
# Phase 6A — display hourly missions in existing reports/UI
# ---------------------------------------------------------------------------
def _workday_in_current_month():
    """Non-Friday day in current Jalali month (for UI pages that filter by month)."""
    today_j = jdatetime.date.today()
    jy, jm = today_j.year, today_j.month
    if jm == 12:
        j_end = jdatetime.date(jy, 12, 29)
    else:
        j_end = jdatetime.date(jy, jm + 1, 1) - timedelta(days=1)
    j_start = jdatetime.date(jy, jm, 1)
    days_in_month = (j_end - j_start).days + 1
    candidate = jdatetime.date(jy, jm, min(10, days_in_month))
    while candidate.togregorian().weekday() == 4:
        candidate += timedelta(days=1)
        if candidate > j_end:
            candidate = jdatetime.date(jy, jm, 1)
            while candidate.togregorian().weekday() == 4:
                candidate += timedelta(days=1)
            break
    return candidate


def _html_row_containing(html, needle):
    for chunk in html.split("<tr"):
        if needle in chunk:
            return chunk
    return ""


class TestFormatHmDisplay:
    @pytest.mark.parametrize("starts_ends, expected", [
        ([(time(9, 0), time(11, 0))], "مأموریت ساعتی 09:00 تا 11:00"),
        ([(time(9, 0), time(11, 0)), (time(13, 0), time(14, 0))],
         "مأموریت ساعتی 09:00 تا 11:00، 13:00 تا 14:00"),
        ([(time(7, 30), time(8, 0))], "مأموریت ساعتی 07:30 تا 08:00"),
    ])
    def test_format_ranges(self, starts_ends, expected):
        class FakeM:
            def __init__(self, s, e):
                self.start_time = s
                self.end_time = e
        missions = [FakeM(s, e) for s, e in starts_ends]
        assert format_hm_display(missions) == expected

    def test_format_empty(self):
        assert format_hm_display(None) == ""
        assert format_hm_display([]) == ""


class TestDisplayHelper:
    def test_only_approved_returned(self, db, make_user):
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0), status="A")
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(13, 0), end=time(14, 0), status="P")
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(15, 0), end=time(16, 0), status="R")
            result = get_approved_hourly_missions_for_display(
                db, emp, MONDAY, MONDAY)
            assert MONDAY in result
            assert len(result[MONDAY]) == 1
            assert result[MONDAY][0].status == "A"
            assert format_hm_display(result[MONDAY]) == \
                "مأموریت ساعتی 09:00 تا 11:00"
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_display_independent_of_deduct_policy(self, db, make_user):
        """policy deduct off → still displays (Required stays original)."""
        _cleanup_policies(db)
        try:
            emp, creds = _employee(db, make_user)
            _seed_policy(db, employment_type_code="4",
                         deduct_from_required_minutes=False)
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0), status="A")
            display = get_approved_hourly_missions_for_display(
                db, emp, MONDAY, MONDAY)
            assert format_hm_display(display.get(MONDAY)) == \
                "مأموریت ساعتی 09:00 تا 11:00"
            assert get_approved_hourly_mission_minutes(
                db, emp, MONDAY, MONDAY) == {}
        finally:
            _cleanup_missions(db, creds["user_id"])
            _cleanup_policies(db)

    def test_out_of_range_excluded(self, db, make_user):
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=date(2027, 3, 23),
                                  start=time(9, 0), end=time(11, 0), status="A")
            result = get_approved_hourly_missions_for_display(
                db, emp, MONDAY, MONDAY)
            assert result == {}
        finally:
            _cleanup_missions(db, creds["user_id"])


class TestAttendanceUserHmBadge:
    def test_user_attendance_shows_approved_hm(self, db, client, make_user):
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.get(
                f"/admin/attendance/user/{user['user_id']}"
                f"?year={workday.year}&month={workday.month}")
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])

    def test_pending_hm_not_shown_as_approved(self, db, client, make_user):
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="P")
            login_as(client, admin["national_code"])
            resp = client.get(
                f"/admin/attendance/user/{user['user_id']}"
                f"?year={workday.year}&month={workday.month}")
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" not in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])


class TestAdminDailyAttendanceHmBadge:
    def test_admin_attendance_shows_hm(self, db, client, make_user):
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.get(
                f"/admin/attendance?date_str={workday.strftime('%Y/%m/%d')}")
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])


class TestSelfAttendanceHmBadge:
    def test_attendance_page_shows_hm(self, db, client, make_user):
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, user["national_code"])
            resp = client.get(
                f"/attendance?year={workday.year}&month={workday.month}")
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])


class TestReportHmBadge:
    def test_detailed_report_shows_hm(self, db, client, make_user, monkeypatch):
        from tests.conftest import TestingSessionLocal
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.post("/reports/monthly-detailed", data={
                "target_user_id": user["user_id"],
                "year": workday.year,
                "month": workday.month,
            })
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
            # person_status must not be converted to full-day mission
            row = _html_row_containing(
                resp.text, workday.strftime("%Y/%m/%d"))
            assert "مأموریت ساعتی" in row
            assert "status-badge\">مرخصی" not in row
        finally:
            _cleanup_missions(db, user["user_id"])

    def test_full_report_shows_hm(self, db, client, make_user, monkeypatch):
        from tests.conftest import TestingSessionLocal
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _workday_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.post("/reports/monthly-full", data={
                "target_user_id": user["user_id"],
                "year": workday.year,
                "month": workday.month,
            })
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])


class TestDailyStatusStillShowsAllStatuses:
    def test_pending_still_visible_on_daily_status(self, db, client, make_user):
        """Daily-status page continues to show P/A/R/D (management view)."""
        _as_super(client, make_user)
        target = make_user(role="user", balance_al=None)
        try:
            _seed_pending_mission(db, target["user_id"], status="P")
            _seed_pending_mission(db, target["user_id"],
                                  start=time(13, 0), end=time(14, 0),
                                  status="A")
            resp = client.get("/admin/daily-status")
            assert resp.status_code == 200
            assert "در انتظار تأیید" in resp.text
            assert "تأیید شده" in resp.text
            assert "درخواست‌های مأموریت ساعتی" in resp.text
        finally:
            _cleanup_missions(db, target["user_id"])


class TestDisplayDoesNotChangeRequired:
    def test_rendering_does_not_alter_required_minutes(self, db, client, make_user):
        """UI display path must not change compute_required_minutes_for_range."""
        emp, creds = _seed_hm_and_base(db, make_user)
        admin = _as_super(client, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            assert _hm_required(db, emp) == 360

            # Hit UI page (display path) then re-check required
            login_as(client, admin["national_code"])
            workday = _workday_in_current_month()
            client.get(
                f"/admin/attendance/user/{creds['user_id']}"
                f"?year={workday.year}&month={workday.month}")

            db.expire_all()
            assert _hm_required(db, emp) == 360
            row = db.query(HourlyMission).filter(
                HourlyMission.user_id == creds["user_id"]).first()
            assert row.status == "A"
            assert db.query(DailyStatus).filter(
                DailyStatus.user_id == creds["user_id"]).count() == 0
        finally:
            _cleanup_missions(db, creds["user_id"])
            _cleanup_policies(db)
            _cleanup_attendance_policies(db)


# ---------------------------------------------------------------------------
# Phase 6B — hourly mission in PDF / Excel / Raw Report
# ---------------------------------------------------------------------------
# MONDAY = 2027-03-22 = 1406/01/02 (Farvardin). Raw report month: 1406/01.
RAW_YEAR, RAW_MONTH = 1406, 1


def _cleanup_daily_statuses(db, user_id):
    db.query(DailyStatus).filter(
        DailyStatus.user_id == user_id).delete()
    db.commit()


def _build_raw(db, user_id, year=RAW_YEAR, month=RAW_MONTH):
    from core.raw_report import build_raw_report
    return build_raw_report(db, year, month, employee_user_id=user_id)


def _raw_day(report, user_id, g_date):
    for emp in report["employees"]:
        if emp["user_id"] == user_id:
            for day in emp["days"]:
                if day["date"] == g_date:
                    return day
    return None


class TestRawReportHourlyMission:
    def test_approved_shown_in_raw_day(self, db, make_user):
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day is not None
            assert day["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00"
            assert day["hourly_mission_minutes"] == 120
            assert day["hourly_missions"] == [
                {"start": "09:00", "end": "11:00", "minutes": 120}
            ]
        finally:
            _cleanup_missions(db, creds["user_id"])

    @pytest.mark.parametrize("status", ["P", "R", "D"])
    def test_non_approved_not_shown(self, db, make_user, status):
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status=status)
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day["hourly_mission_display"] == ""
            assert day["hourly_missions"] == []
            assert day["hourly_mission_minutes"] == 0
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_daily_status_m_not_confused_with_hourly_mission(self, db, make_user):
        """DailyStatus M → person_status M; HM is separate display field."""
        emp, creds = _employee(db, make_user)
        try:
            db.add(DailyStatus(user_id=creds["user_id"],
                               status_date=MONDAY, status_code="M"))
            db.commit()
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(13, 0), end=time(15, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day["person_status"] == "M"
            assert day["person_status_name"] == "مأموریت"
            # HM stays separate — not merged into person_status
            assert day["hourly_mission_display"] == \
                "مأموریت ساعتی 13:00 تا 15:00"
        finally:
            _cleanup_missions(db, creds["user_id"])
            _cleanup_daily_statuses(db, creds["user_id"])

    def test_hourly_mission_does_not_change_person_status(self, db, make_user):
        """HM alone must not become person_status M/leave — cascade unchanged."""
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            # No DailyStatus, no punches → not M; HM is only a display field
            assert day["person_status"] != "M"
            assert day["hourly_mission_display"]
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_multiple_missions_sorted_by_start_time(self, db, make_user):
        emp, creds = _employee(db, make_user)
        try:
            # Insert out of order — query orders by start_time
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(13, 0), end=time(14, 0),
                                  status="A")
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00، 13:00 تا 14:00"
            assert len(day["hourly_missions"]) == 2
            assert day["hourly_missions"][0]["start"] == "09:00"
            assert day["hourly_missions"][1]["start"] == "13:00"
            assert day["hourly_mission_minutes"] == 120 + 60
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_mission_outside_date_range_excluded(self, db, make_user):
        emp, creds = _employee(db, make_user)
        outside = date(2026, 6, 15)  # not in 1406/01
        try:
            _seed_pending_mission(db, creds["user_id"], day=outside,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], outside)
            assert day is None  # outside month days
            # Also no HM leaked into any in-range day
            for d in report["employees"][0]["days"]:
                assert d["hourly_mission_display"] == ""
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_no_synthetic_punches_from_mission(self, db, make_user):
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day["punches"] == []
            assert day["attendance_segments"] == []
            assert day["attendance_str"] == "—"
            assert day["has_attendance"] is False
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_group_report_no_employee_mix(self, db, make_user):
        emp_a, creds_a = _employee(db, make_user)
        emp_b, creds_b = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds_a["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            _seed_pending_mission(db, creds_b["user_id"], day=MONDAY,
                                  start=time(14, 0), end=time(16, 0),
                                  status="A")
            from core.raw_report import build_raw_report
            report = build_raw_report(db, RAW_YEAR, RAW_MONTH)
            day_a = _raw_day(report, creds_a["user_id"], MONDAY)
            day_b = _raw_day(report, creds_b["user_id"], MONDAY)
            assert day_a["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00"
            assert day_b["hourly_mission_display"] == \
                "مأموریت ساعتی 14:00 تا 16:00"
            # No cross-contamination
            assert "14:00" not in day_a["hourly_mission_display"]
            assert "09:00" not in day_b["hourly_mission_display"]
        finally:
            _cleanup_missions(db, creds_a["user_id"])
            _cleanup_missions(db, creds_b["user_id"])

    def test_display_independent_of_deduct_policy(self, db, make_user):
        """deduct=false → still displayed; required minutes helper stays empty."""
        _cleanup_policies(db)
        emp, creds = _employee(db, make_user)
        try:
            _seed_policy(db, employment_type_code="4",
                         deduct_from_required_minutes=False)
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            assert day["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00"
            # Deduction layer unchanged (display ≠ deduction)
            assert get_approved_hourly_mission_minutes(
                db, emp, MONDAY, MONDAY) == {}
        finally:
            _cleanup_missions(db, creds["user_id"])
            _cleanup_policies(db)


class TestExcelHourlyMission:
    def test_excel_shows_mission_with_minutes(self, db, make_user):
        from io import BytesIO
        from openpyxl import load_workbook
        from core.excel_raw_report import export_individual as excel_export_individual

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            output = BytesIO()
            excel_export_individual(report, output)
            output.seek(0)
            wb = load_workbook(output)
            ws = wb.active
            found = False
            for row in ws.iter_rows(min_row=7, values_only=True):
                if row and row[0] and "1406/01/02" in str(row[0]):
                    leave_cell = str(row[4] or "")
                    assert "مأموریت ساعتی 09:00-11:00 (120 دقیقه)" in leave_cell
                    # employee header present
                    found = True
            assert found, "Row for 1406/01/02 not found in Excel"
            # Employee identity in header
            header_text = str(ws.cell(row=4, column=1).value or "")
            assert creds["user_id"] in header_text
            # Format: 6 columns still
            headers = [cell.value for cell in ws[6]]
            assert len(headers) == 6
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_excel_pending_not_shown(self, db, make_user):
        from io import BytesIO
        from openpyxl import load_workbook
        from core.excel_raw_report import export_individual as excel_export_individual

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="P")
            report = _build_raw(db, creds["user_id"])
            output = BytesIO()
            excel_export_individual(report, output)
            output.seek(0)
            wb = load_workbook(output)
            ws = wb.active
            for row in ws.iter_rows(min_row=7, values_only=True):
                if row and row[0] and "1406/01/02" in str(row[0]):
                    assert "مأموریت ساعتی" not in str(row[4] or "")
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_excel_multiple_missions(self, db, make_user):
        from io import BytesIO
        from openpyxl import load_workbook
        from core.excel_raw_report import export_individual as excel_export_individual

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(13, 0), end=time(14, 0),
                                  status="A")
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            output = BytesIO()
            excel_export_individual(report, output)
            output.seek(0)
            wb = load_workbook(output)
            ws = wb.active
            for row in ws.iter_rows(min_row=7, values_only=True):
                if row and row[0] and "1406/01/02" in str(row[0]):
                    cell = str(row[4] or "")
                    assert "مأموریت ساعتی 09:00-11:00 (120 دقیقه)" in cell
                    assert "مأموریت ساعتی 13:00-14:00 (60 دقیقه)" in cell
                    # 09:00 before 13:00
                    assert cell.index("09:00") < cell.index("13:00")
        finally:
            _cleanup_missions(db, creds["user_id"])


class TestPdfHourlyMission:
    def test_pdf_export_includes_mission_text(self, db, make_user):
        from io import BytesIO
        from core.pdf_raw_report import export_individual as pdf_export_individual
        from core.pdf_raw_report import RawPDF

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            # leave cell text used by PDF includes HM
            text = RawPDF._leave_and_mission_text(day)
            assert "مأموریت ساعتی 09:00 تا 11:00" in text
            output = BytesIO()
            pdf_export_individual(report, output)
            assert output.tell() > 0 or len(output.getvalue()) > 0
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_pdf_mission_not_converted_to_punch(self, db, make_user):
        from core.pdf_raw_report import RawPDF

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            # Attendance cell stays empty — mission is not a punch pair
            att_text = RawPDF._attendance_text_for_pdf(day)
            assert att_text in ("—", "")
            assert "09:00 → 11:00" not in att_text
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_pdf_pending_not_in_leave_text(self, db, make_user):
        from core.pdf_raw_report import RawPDF

        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="P")
            report = _build_raw(db, creds["user_id"])
            day = _raw_day(report, creds["user_id"], MONDAY)
            text = RawPDF._leave_and_mission_text(day)
            assert "مأموریت ساعتی" not in text
        finally:
            _cleanup_missions(db, creds["user_id"])


class TestRawReportHtmlHourlyMission:
    def test_raw_html_shows_mission(self, db, client, make_user):
        _as_super(client, make_user)
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            resp = client.post("/reports/raw", data={
                "target_user_id": creds["user_id"],
                "year": str(RAW_YEAR),
                "month": str(RAW_MONTH),
                "employment_type": "all",
                "status_filter": "all",
            })
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" in resp.text
        finally:
            _cleanup_missions(db, creds["user_id"])

    def test_raw_html_pending_not_shown(self, db, client, make_user):
        _as_super(client, make_user)
        emp, creds = _employee(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="P")
            resp = client.post("/reports/raw", data={
                "target_user_id": creds["user_id"],
                "year": str(RAW_YEAR),
                "month": str(RAW_MONTH),
                "employment_type": "all",
                "status_filter": "all",
            })
            assert resp.status_code == 200
            assert "مأموریت ساعتی 09:00 تا 11:00" not in resp.text
        finally:
            _cleanup_missions(db, creds["user_id"])


# ---------------------------------------------------------------------------
# Phase 6C — monthly reports (گزارش تفصیلی / کامل): Effective Required audit
# ---------------------------------------------------------------------------
# ماه گزارش: 1406/01 = 2027-03-21 .. 2027-04-20 (31 روز — فروردین 31 روزه).
# سیاست پایهٔ این تست‌ها: Mon-Thu+Sat 07:00–15:00 = 480 دقیقه → 22 روز کاری
# (22 کاری + 4 جمعه + 5 یکشنبه = 31).
P6C_SUNDAY = date(2027, 3, 21)      # 1406/01/01 — یکشنبه (غیرکاری در Policy)
P6C_TUESDAY = date(2027, 3, 23)
P6C_WEDNESDAY = date(2027, 3, 24)
P6C_THURSDAY = date(2027, 3, 25)
# MONDAY = 2027-03-22 و FRIDAY = 2027-03-26 — در بالای فایل تعریف شده‌اند
P6C_WORKDAYS = 22
P6C_DUTY_HOURS = 176.0
P6C_WORK_WEEKDAYS = (0, 1, 2, 3, 5)


def _p6c_base(db, make_user):
    """Employee دپارتمان 4 + سیاست حضور 480 دقیقه‌ای + پاک‌سازی policy قبلی."""
    _cleanup_policies(db)
    _cleanup_attendance_policies(db, "4")
    _cleanup_holidays(db)
    emp, creds = _employee(db, make_user)
    _seed_attendance_policy(db, department="4",
                            workday_start=time(7, 0),
                            workday_end=time(15, 0))
    return emp, creds


def _p6c_teardown(db, user_id):
    _cleanup_missions(db, user_id)
    _cleanup_policies(db)
    _cleanup_attendance_policies(db, "4")
    _cleanup_holidays(db)
    _cleanup_daily_statuses(db, user_id)


def _p6c_report(monkeypatch, user_id, year=RAW_YEAR, month=RAW_MONTH):
    """گزارش ماهانه از generator واقعی — روی DB تست (همان مسیر هر دو route)."""
    from tests.conftest import TestingSessionLocal
    from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
    monkeypatch.setattr(
        "core.detailed_monthly_report_v2.SessionLocal", TestingSessionLocal)
    gen = DetailedMonthlyReportGeneratorV2()
    try:
        report = gen.generate_detailed_report(user_id, year, month)
    finally:
        gen.close()
    assert report.get("success"), report.get("message")
    return report


def _p6c_day(report, g_date):
    for d in report["days"]:
        if d["date"] == g_date:
            return d
    raise AssertionError(f"day {g_date} not found in report")


def _p6c_seed_leave(db, user_id, day, leave_type="AL", status="A",
                    start=None, end=None):
    from models.leave_request import LeaveRequest
    req = LeaveRequest(
        user_id=user_id, leave_type=leave_type,
        from_date=day, to_date=day,
        days_count=0 if start else 1,
        status=status, start_time=start, end_time=end,
    )
    db.add(req)
    db.commit()
    return req


def _p6c_seed_status(db, user_id, day, code):
    db.add(DailyStatus(user_id=user_id, status_date=day, status_code=code))
    db.commit()


def _p6c_seed_punches(db, user_id, day, start_t, end_t):
    from datetime import datetime
    from models.attendance import Attendance
    for punch, t in ((0, start_t), (1, end_t)):
        db.add(Attendance(
            user_id=user_id,
            timestamp=datetime(day.year, day.month, day.day,
                               t.hour, t.minute),
            punch=punch, source="M",
        ))
    db.commit()


def _p6c_count_working_days(jy, jm):
    """تعداد روزهای کاری Policy (Mon-Thu+Sat) در یک ماه جلالی (بدون Holiday)."""
    count = 0
    for day_no in range(1, 32):
        try:
            g = jdatetime.date(jy, jm, day_no).togregorian()
        except ValueError:
            break
        if g.weekday() in P6C_WORK_WEEKDAYS:
            count += 1
    return count


def _p6c_working_day_in_current_month():
    """روز کاری Policy در ماه جلالی جاری (برای تست‌های route)."""
    today_j = jdatetime.date.today()
    for day_no in range(1, 32):
        try:
            d = jdatetime.date(today_j.year, today_j.month, day_no)
        except ValueError:
            break
        if d.togregorian().weekday() in P6C_WORK_WEEKDAYS:
            return d
    raise AssertionError("no policy-working day in current Jalali month")


class TestMonthlyReportEffectiveRequired:
    """Effective Required در گزارش ماهانه — واحد با compute_required_minutes_for_range."""

    def test_base_required_and_day_status(self, db, make_user, monkeypatch):
        """روز عادی 480؛ جمعه/یکشنبهٔ Policy غیرکاری = تعطیل (نه غایب)."""
        emp, creds = _p6c_base(db, make_user)
        try:
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["daily_duty"] == 8.0
            assert monday["has_duty"] is True
            assert monday["person_status"] == "A"   # بدون تردد → غایب
            # تک‌منبع: همان عدد از compute_required_minutes_for_range
            assert _hm_required(db, emp) == 480

            friday = _p6c_day(report, FRIDAY)
            assert friday["is_friday"] is True
            assert friday["is_day_off"] is True
            assert friday["person_status"] == "H"
            assert friday["daily_duty"] == 0.0

            # روز غیرکاری Policy (یکشنبه) هم «تعطیل» است — نه «غایب»
            sunday = _p6c_day(report, P6C_SUNDAY)
            assert sunday["is_day_off"] is True
            assert sunday["day_status"] == "تعطیل"
            assert sunday["person_status"] == "H"
            assert sunday["daily_duty"] == 0.0

            assert report["summary"]["duty_days"] == P6C_WORKDAYS
            assert report["summary"]["duty_hours"] == P6C_DUTY_HOURS
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_approved_hm_deducts_from_required(self, db, make_user, monkeypatch):
        """فقط status='A': 480 − 120 = 360 دقیقه (6.00 ساعت) در هر دو مسیر."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["hourly_mission_minutes"] == 120
            assert monday["daily_duty"] == 6.0
            assert monday["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00"
            # وضعیت فرد دست نمی‌خورد (بدون تردد → A، نه مأموریت کامل)
            assert monday["person_status"] == "A"
            # خلاصه: 176 − 2 = 174 ساعت
            assert report["summary"]["duty_hours"] == 174.0
            assert report["summary"]["duty_days"] == P6C_WORKDAYS
            # تک‌منبع: همان عدد از compute_required_minutes_for_range
            assert _hm_required(db, emp) == 360
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_hm_policy_off_shows_display_but_no_deduction(
            self, db, make_user, monkeypatch):
        """deduct policy خاموش → نمایش هست، Required دست نمی‌خورد."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _seed_policy(db, employment_type_code="4",
                         deduct_from_required_minutes=False)
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["daily_duty"] == 8.0
            assert monday["hourly_mission_minutes"] == 0
            assert monday["hourly_mission_display"] == \
                "مأموریت ساعتی 09:00 تا 11:00"
            assert report["summary"]["duty_hours"] == P6C_DUTY_HOURS
            assert _hm_required(db, emp) == 480
        finally:
            _p6c_teardown(db, creds["user_id"])

    @pytest.mark.parametrize("status", ["P", "R", "D"])
    def test_hm_not_approved_no_deduction(self, db, make_user, monkeypatch,
                                          status):
        """P/R/D نه کسر می‌شوند و نه نمایش داده می‌شوند."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status=status)
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["daily_duty"] == 8.0
            assert monday["hourly_mission_minutes"] == 0
            assert monday["hourly_mission_display"] == ""
            assert _hm_required(db, emp) == 480
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_hm_longer_than_required_clamped_at_zero(
            self, db, make_user, monkeypatch):
        """HM 600 دقیقه > موظفی 480 → 0 (clamp)، روز از duty_days خارج."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(7, 0), end=time(17, 0),
                                  status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["daily_duty"] == 0.0
            assert monday["has_duty"] is False
            assert monday["deficit"] == 0.0
            assert report["summary"]["duty_days"] == P6C_WORKDAYS - 1
            assert report["summary"]["duty_hours"] == P6C_DUTY_HOURS - 8
            assert _hm_required(db, emp) == 0
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_hl_and_hm_both_deduct_in_report(self, db, make_user, monkeypatch):
        """HL 60 + HM 120 → 480 − 180 = 300 دقیقه (5.00 ساعت) — یک pipeline."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_leave(db, creds["user_id"], MONDAY, leave_type="HL",
                            status="A", start=time(9, 0), end=time(10, 0))
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["hourly_leave_minutes"] == 60
            assert monday["hourly_mission_minutes"] == 120
            assert monday["daily_duty"] == 5.0
            # HL روز را مرخصی کامل نمی‌کند
            assert monday["person_status"] == "A"
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_daily_mission_status_zero_duty(self, db, make_user, monkeypatch):
        """DailyStatus 'M' → person_status=مأموریت، موظفی 0، نه غایب."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_status(db, creds["user_id"], MONDAY, "M")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["person_status"] == "M"
            assert monday["person_status_name"] == "مأموریت"
            assert monday["daily_duty"] == 0.0
            assert monday["deficit"] == 0.0

            s = report["summary"]
            assert s["mission_days"] == 1
            assert s["absent_days"] == P6C_WORKDAYS - 1
            assert s["duty_days"] == P6C_WORKDAYS - 1
            assert s["duty_hours"] == P6C_DUTY_HOURS - 8
            assert _hm_required(db, emp, mission_dates={MONDAY}) == 0
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_rest_status_zero_duty(self, db, make_user, monkeypatch):
        """DailyStatus 'R' → استراحت، موظفی 0."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_status(db, creds["user_id"], MONDAY, "R")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["person_status"] == "R"
            assert monday["person_status_name"] == "استراحت"
            assert monday["daily_duty"] == 0.0
            assert report["summary"]["rest_days"] == 1
            assert report["summary"]["absent_days"] == P6C_WORKDAYS - 1
            assert _hm_required(db, emp, rest_dates={MONDAY}) == 0
        finally:
            _p6c_teardown(db, creds["user_id"])

    @pytest.mark.parametrize("leave_type", ["AL", "SL", "RL", "CW", "UL"])
    def test_full_day_leave_types_zero_duty(self, db, make_user, monkeypatch,
                                            leave_type):
        """همهٔ مرخصی‌های روزانه (شامل CW — اصلاح فاز 6C) → L و موظفی 0."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_leave(db, creds["user_id"], MONDAY,
                            leave_type=leave_type, status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["person_status"] == "L"
            assert monday["person_status_name"] == "مرخصی"
            assert monday["daily_duty"] == 0.0

            s = report["summary"]
            assert s["leave_days"] == 1
            assert s["absent_days"] == P6C_WORKDAYS - 1
            assert s["duty_days"] == P6C_WORKDAYS - 1
            assert s["duty_hours"] == P6C_DUTY_HOURS - 8
            assert _hm_required(
                db, emp, leaves_by_date={MONDAY: leave_type}) == 0
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_holiday_row_zero_duty(self, db, make_user, monkeypatch):
        """Holiday ثبت‌شده → تعطیل، موظفی 0، شمارش holiday_days."""
        emp, creds = _p6c_base(db, make_user)
        try:
            db.add(Holiday(holiday_date=MONDAY, title="تست فاز 6C",
                           is_national=True, group_id=None))
            db.commit()
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["is_holiday"] is True
            assert monday["is_day_off"] is True
            assert monday["person_status"] == "H"
            assert monday["daily_duty"] == 0.0

            s = report["summary"]
            # 4 جمعه + 5 یکشنبه + MONDAY
            assert s["holiday_days"] == 10
            assert s["duty_days"] == P6C_WORKDAYS - 1
            assert s["duty_hours"] == P6C_DUTY_HOURS - 8
            assert s["absent_days"] == P6C_WORKDAYS - 1
            assert _hm_required(db, emp, holiday_dates={MONDAY: None}) == 0
        finally:
            _p6c_teardown(db, creds["user_id"])


class TestMonthlyReportSummaryAndShifts:
    """خلاصهٔ ماهانه، تفکیک شیفت (فقط attendance) و اضافه‌کار هفتگی."""

    def test_summary_scenario(self, db, make_user, monkeypatch):
        """حضور کامل / اضافی / کسری / مرخصی — جمع‌های خلاصه و تراز."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_punches(db, creds["user_id"], MONDAY,
                              time(7, 0), time(15, 0))       # 8h → تعادل
            _p6c_seed_punches(db, creds["user_id"], P6C_TUESDAY,
                              time(7, 0), time(17, 0))       # 10h → +2
            _p6c_seed_punches(db, creds["user_id"], P6C_WEDNESDAY,
                              time(7, 0), time(13, 0))       # 6h → −2
            _p6c_seed_leave(db, creds["user_id"], P6C_THURSDAY,
                            leave_type="AL", status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            assert _p6c_day(report, MONDAY)["surplus"] == 0.0
            assert _p6c_day(report, MONDAY)["deficit"] == 0.0
            assert _p6c_day(report, P6C_TUESDAY)["surplus"] == 2.0
            assert _p6c_day(report, P6C_WEDNESDAY)["deficit"] == 2.0
            assert _p6c_day(report, P6C_THURSDAY)["person_status"] == "L"
            assert _p6c_day(report, P6C_THURSDAY)["daily_duty"] == 0.0

            s = report["summary"]
            assert s["duty_days"] == P6C_WORKDAYS - 1
            assert s["duty_hours"] == P6C_DUTY_HOURS - 8
            assert s["present_days"] == 3
            assert s["leave_days"] == 1
            # 21 روز کاری − ۳ حضور − ۱ مرخصی
            assert s["absent_days"] == P6C_WORKDAYS - 4
            assert s["rest_days"] == 0
            assert s["mission_days"] == 0
            # 4 جمعه + 5 یکشنبه (بدون Holiday)
            assert s["holiday_days"] == 9
            assert s["total_surplus"] == 2.0
            # کسری: 17 روز بدون تردد (17×8) + کسری چهارشنبه (2)
            assert s["total_deficit"] == (P6C_WORKDAYS - 4) * 8 + 2.0
            assert s["net_balance"] == 2.0 - s["total_deficit"]
            assert s["overall_status"] == "کسری"
            # تفکیک شیفت فقط از attendance: 7+7+6 صبح، 1+3+0 عصر
            assert s["total_morning"] == 20.0
            assert s["total_evening"] == 4.0
            assert s["total_night"] == 0.0
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_shift_split_from_attendance_only(self, db, make_user, monkeypatch):
        """صبح/عصر/شب از جفت ورود/خروج — HM به آن اضافه نمی‌شود."""
        emp, creds = _p6c_base(db, make_user)
        try:
            _p6c_seed_punches(db, creds["user_id"], MONDAY,
                              time(7, 0), time(15, 0))
            _seed_pending_mission(db, creds["user_id"], day=MONDAY,
                                  start=time(12, 0), end=time(14, 0),
                                  status="A")
            report = _p6c_report(monkeypatch, creds["user_id"])

            monday = _p6c_day(report, MONDAY)
            assert monday["work_hours"] == 8.0
            assert monday["morning_hours"] == 7.0   # 07–14 (bucket 6–14)
            assert monday["evening_hours"] == 1.0    # 14–15 (bucket 14–22)
            assert monday["night_hours"] == 0.0
            # HM باز هم از موظفی کم می‌شود: 480 − 120 = 360
            assert monday["daily_duty"] == 6.0
        finally:
            _p6c_teardown(db, creds["user_id"])

    def test_weekly_overtime_current_behavior(self, db, make_user, monkeypatch):
        """اضافه‌کار هفتگی: هفته از شنبه؛ فقط روزهای همین ماه شمرده می‌شوند."""
        emp, creds = _p6c_base(db, make_user)
        try:
            # پانچِ خارج از ماه (شنبه 2027-03-20 — همان هفته) نباید لحاظ شود
            _p6c_seed_punches(db, creds["user_id"], date(2027, 3, 20),
                              time(7, 0), time(19, 0))
            _p6c_seed_punches(db, creds["user_id"], MONDAY,
                              time(7, 0), time(16, 0))       # 9h
            _p6c_seed_punches(db, creds["user_id"], P6C_TUESDAY,
                              time(7, 0), time(15, 0))       # 8h
            _p6c_seed_punches(db, creds["user_id"], P6C_WEDNESDAY,
                              time(7, 0), time(15, 0))       # 8h
            _p6c_seed_punches(db, creds["user_id"], P6C_THURSDAY,
                              time(7, 0), time(15, 0))       # 8h
            report = _p6c_report(monkeypatch, creds["user_id"])

            # هفتهٔ شنبه 2027-03-20 (ماه قبل) تا جمعه 2027-03-26:
            # کارکرد درون‌ماه 33h در برابر موظفی درون‌ماه 32h → 1h اضافه‌کار
            assert report["summary"]["weekly_overtime"] == 1.0
            assert report["summary"]["total_work_hours"] == 33.0
        finally:
            _p6c_teardown(db, creds["user_id"])


class TestMonthlyReportRoutes:
    """دو route گزارش + monthly-stats (بدون HM) + UI فرم HM."""

    def test_detailed_route_shows_required_after_hm(
            self, db, client, make_user, monkeypatch):
        from tests.conftest import TestingSessionLocal
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal",
            TestingSessionLocal)
        _cleanup_policies(db)
        _cleanup_attendance_policies(db, "4")
        _cleanup_holidays(db)
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        workday = _p6c_working_day_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.post("/reports/monthly-detailed", data={
                "target_user_id": user["user_id"],
                "year": workday.year,      # Jalali
                "month": workday.month,
            })
            assert resp.status_code == 200
            row = _html_row_containing(resp.text,
                                       workday.strftime("%Y/%m/%d"))
            assert row != "", "ردیف روز در گزارش تفصیلی یافت نشد"
            # موظفی = 480 − 120 = 360 دقیقه → 6.00 ساعت (ستون موظفی)
            assert 'hour-value">6.00</span>' in row
            assert "مأموریت ساعتی 09:00 تا 11:00" in row
            # وضعیت فرد نباید به مرخصی/مأموریت کامل تبدیل شود
            assert 'status-badge">مرخصی' not in row
            assert 'status-badge">مأموریت</span>' not in row
        finally:
            _cleanup_missions(db, user["user_id"])
            _cleanup_attendance_policies(db, "4")
            _cleanup_policies(db)

    def test_full_route_shows_required_and_no_720_labels(
            self, db, client, make_user, monkeypatch):
        from tests.conftest import TestingSessionLocal
        from web.routes.reports import format_hhmm
        monkeypatch.setattr(
            "core.detailed_monthly_report_v2.SessionLocal",
            TestingSessionLocal)
        _cleanup_policies(db)
        _cleanup_attendance_policies(db, "4")
        _cleanup_holidays(db)
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        _seed_attendance_policy(db, department="4",
                                workday_start=time(7, 0),
                                workday_end=time(15, 0))
        workday = _p6c_working_day_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.post("/reports/monthly-full", data={
                "target_user_id": user["user_id"],
                "year": workday.year,      # Jalali
                "month": workday.month,
            })
            assert resp.status_code == 200
            html = resp.text

            # موظفی خلاصه مستقیماً از همان generator:
            # (تعداد روزهای کاری × 8) − 2 ساعت کسر HM
            duty_days = _p6c_count_working_days(workday.year, workday.month)
            expected = (f"{duty_days} روز / "
                        f"{format_hhmm(duty_days * 8 - 2)} ساعت")
            assert expected in html
            assert "مأموریت ساعتی 09:00 تا 11:00" in html
            # برچسب‌های hard-coded حذف شده‌اند
            assert "اضافی (7:20)" not in html
            assert "کسری (7:20)" not in html
        finally:
            _cleanup_missions(db, user["user_id"])
            _cleanup_attendance_policies(db, "4")
            _cleanup_policies(db)

    def test_monthly_stats_has_no_hourly_mission(self, db, client, make_user):
        """گزارش آمار ماهیانه عمداً مأموریت ساعتی را نمایش نمی‌دهد."""
        _cleanup_policies(db)
        admin = _as_super(client, make_user)
        user = make_user(role="user", balance_al=None, department="4")
        workday = _p6c_working_day_in_current_month()
        try:
            _seed_pending_mission(db, user["user_id"],
                                  day=workday.togregorian(),
                                  start=time(9, 0), end=time(11, 0),
                                  status="A")
            login_as(client, admin["national_code"])
            resp = client.post("/reports/monthly-stats", data={
                "year": str(workday.year),
                "month": str(workday.month),
                "department": "all",
            })
            assert resp.status_code == 200
            assert "مأموریت ساعتی" not in resp.text
        finally:
            _cleanup_missions(db, user["user_id"])
            _cleanup_policies(db)

    def test_daily_status_hm_time_fields_match_hl_markup(
            self, client, make_user):
        """فیلدهای ساعت HM: همان markup الگوی HL (text + picker مشترک)."""
        _as_super(client, make_user)
        resp = client.get("/admin/daily-status")
        assert resp.status_code == 200
        html = resp.text

        assert 'id="start_time"' in html
        assert 'id="end_time"' in html
        assert 'id="hm-start-wrap"' in html
        # time-picker سراسری HL (leave_time.js) روی فیلدهای HM هم فعال است
        assert "leave_time.js" in html

        start_wrap = html.split('id="hm-start-wrap"', 1)[1][:500]
        end_wrap = html.split('id="hm-end-wrap"', 1)[1][:500]
        for wrap in (start_wrap, end_wrap):
            assert 'type="text"' in wrap
            assert 'type="time"' not in wrap
            assert 'pattern="([01][0-9]|2[0-3]):([0-5][0-9])"' in wrap
            assert 'inputmode="numeric"' in wrap
            assert 'maxlength="5"' in wrap
            assert 'dir="ltr"' in wrap
            assert 'autocomplete="off"' in wrap
            assert 'data-time-input="true"' in wrap

