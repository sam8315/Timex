"""
Phase 1 tests — hourly mission data model and global policies.

Covers:
- model import / registration in Base.metadata
- table creation in the test database
- base DB constraints (start < end, valid status)
- four hourly-mission policy keys (save + read)
- policies page renders the new settings section
- previous related behaviour stays intact
"""
from datetime import date, time

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from models import Base, HourlyMission
from models.policy import Policy, PolicyValue
from tests.conftest import test_engine
from .conftest import login_as


POLICY_KEYS = (
    "hourly_mission_enabled",
    "hourly_mission_working_hours_only",
    "hourly_mission_allowed_on_holidays",
    "hourly_mission_deduct_from_required_minutes",
)


def _as_super(client, make_user):
    creds = make_user(role="super_admin", balance_al=None)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def _policy_values(db):
    policy = db.query(Policy).filter(
        Policy.category == "hourly_mission").first()
    assert policy is not None, "hourly_mission policy container missing"
    return {
        pv.parameter_key: pv.parameter_value
        for pv in db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.region_code.is_(None),
        )
    }


def _cleanup_missions(db, user_id):
    db.query(HourlyMission).filter(
        HourlyMission.user_id == user_id).delete()
    db.commit()


# ---------------------------------------------------------------------------
# Model / table
# ---------------------------------------------------------------------------
def test_model_registered_in_metadata():
    assert HourlyMission.__tablename__ == "hourly_missions"
    assert "hourly_missions" in Base.metadata.tables
    # exported from the models package
    from models import HourlyMission as Exported
    assert Exported is HourlyMission


def test_table_created_in_test_db():
    tables = inspect(test_engine).get_table_names()
    assert "hourly_missions" in tables
    cols = {c["name"] for c in inspect(test_engine).get_columns("hourly_missions")}
    assert {
        "user_id", "mission_date", "start_time", "end_time", "reason",
        "destination", "status", "approved_by", "approved_at",
        "rejection_reason", "created_at", "updated_at",
    }.issubset(cols)


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
# Global policies (four keys)
# ---------------------------------------------------------------------------
def test_policies_page_renders_hourly_mission_section(client, make_user):
    _as_super(client, make_user)
    resp = client.get("/admin/policies")
    assert resp.status_code == 200
    assert "مأموریت ساعتی فعال است" in resp.text
    assert "مأموریت ساعتی فقط در ساعات موظفی مجاز است" in resp.text
    assert "مأموریت ساعتی در روز تعطیل مجاز است" in resp.text
    assert "مدت مأموریت ساعتی از موظفی کسر می‌شود" in resp.text


def test_save_creates_four_policy_keys(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/hourly-mission/save",
        data={
            "hourly_mission_enabled": "on",
            "hourly_mission_working_hours_only": "on",
            # allowed_on_holidays omitted → unchecked → false
            "hourly_mission_deduct_from_required_minutes": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "success=saved" in resp.headers["location"]
    db.expire_all()

    values = _policy_values(db)
    assert set(POLICY_KEYS).issubset(values.keys())
    assert values["hourly_mission_enabled"] == "true"
    assert values["hourly_mission_working_hours_only"] == "true"
    assert values["hourly_mission_allowed_on_holidays"] == "false"
    assert values["hourly_mission_deduct_from_required_minutes"] == "true"

    # audit log recorded
    from models.policy import PolicyAuditLog
    policy = db.query(Policy).filter(
        Policy.category == "hourly_mission").first()
    audit_count = db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "policy_value",
        PolicyAuditLog.entity_id.in_(list(POLICY_KEYS)),
        PolicyAuditLog.action == "CREATE",
    ).count()
    assert audit_count >= 4

    # restore defaults so later runs/tests see expected state
    client.post(
        "/admin/policies/hourly-mission/save",
        data={
            "hourly_mission_enabled": "on",
            "hourly_mission_working_hours_only": "on",
            "hourly_mission_allowed_on_holidays": "off",
            "hourly_mission_deduct_from_required_minutes": "on",
        },
        follow_redirects=False,
    )


def test_save_is_idempotent_no_duplicates(client, db, make_user):
    _as_super(client, make_user)
    payload = {key: "on" for key in POLICY_KEYS}
    try:
        for _ in range(2):
            resp = client.post(
                "/admin/policies/hourly-mission/save",
                data=payload,
                follow_redirects=False,
            )
            assert resp.status_code == 302

        db.expire_all()
        policy = db.query(Policy).filter(
            Policy.category == "hourly_mission").first()
        rows = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.region_code.is_(None),
            PolicyValue.parameter_key.in_(list(POLICY_KEYS)),
        ).all()
        assert len(rows) == 4
        assert all(r.parameter_value == "true" for r in rows)
    finally:
        # restore defaults
        client.post(
            "/admin/policies/hourly-mission/save",
            data={
                "hourly_mission_enabled": "on",
                "hourly_mission_working_hours_only": "on",
                "hourly_mission_allowed_on_holidays": "off",
                "hourly_mission_deduct_from_required_minutes": "on",
            },
            follow_redirects=False,
        )


def test_non_super_admin_cannot_save_hourly_mission_policy(client, make_user):
    creds = make_user(role="admin", balance_al=None)
    login_as(client, creds["national_code"])
    resp = client.post(
        "/admin/policies/hourly-mission/save",
        data={"hourly_mission_enabled": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
