"""
Phase 1 tests — hourly mission data model and scoped policies.

Covers:
- model import / registration in Base.metadata
- table creation in the test database
- base DB constraints (start < end, valid status)
- four hourly-mission policy settings (save + read, independent)
- policy resolution (override → group → default)
- policies page renders the new card
- detail page shows scopes
- previous related behaviour stays intact
"""
from datetime import date, time

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models import Base, HourlyMission, HourlyMissionPolicy
from models.employee import Employee
from tests.conftest import test_engine
from .conftest import login_as

from web.services.hourly_mission_service import (
    resolve_hourly_mission_policy,
    get_effective_hourly_mission_settings,
    DEFAULT_HOURLY_MISSION_SETTINGS,
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
