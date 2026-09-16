"""
Phase 6: Tests for Attendance Policy CRUD

Covers:
- CRUD (create, edit, soft-delete)
- Validation (invalid type, no working days, bad times, bad dates, bad override)
- Overlap rejection
- Effective-date ordering (to <= from)
- Atomic save (rollback on error)
- Authorization (non-super-admin rejected)
- Historical delete protection (correction #5)
"""
import pytest
from datetime import date, time

import jdatetime

from models.attendance import AttendancePolicy, AttendancePolicyDay
from models.employee import Employee
from models.user import User
from .conftest import login_as


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FUTURE_START = "1408/01/01"
_FUTURE_END = "1408/06/30"
_FUTURE_START_B = "1408/07/01"
_FUTURE_END_B = "1408/12/29"
_PAST_START = "1400/01/01"      # ~2021-03-21 — well in the past
_PAST_END = "1400/06/30"


def _as_super(client, make_user):
    creds = make_user(role="super_admin", balance_al=None)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def _base_data(**overrides):
    """Minimal valid POST data for creating an attendance policy."""
    data = {
        "employment_type_code": "1",
        "user_id_override": "",
        "effective_from_date_str": _FUTURE_START,
        "effective_to_date_str": _FUTURE_END,
        "late_enabled": "on",
        "late_allowed_minutes": "5",
        "late_reference_mode": "FIXED_TIME",
        "early_leave_enabled": "on",
        "early_leave_allowed_minutes": "5",
        "early_reference_mode": "FIXED_TIME",
        # Mon–Fri working 07:00–14:20, Sat/Sun off
        "wd0_working": "on", "wd0_start": "07:00", "wd0_end": "14:20",
        "wd1_working": "on", "wd1_start": "07:00", "wd1_end": "14:20",
        "wd2_working": "on", "wd2_start": "07:00", "wd2_end": "14:20",
        "wd3_working": "on", "wd3_start": "07:00", "wd3_end": "14:20",
        "wd4_working": "on", "wd4_start": "07:00", "wd4_end": "14:20",
        # wd5, wd6 absent → non-working
    }
    data.update(overrides)
    return data


def _cleanup(db, emp_user_id=None):
    """Delete attendance policy rows created during the test."""
    try:
        db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id.in_(
                db.query(AttendancePolicy.id).filter(
                    AttendancePolicy.employment_type_code.in_(["1", "2", "3", "4", "5"])
                )
            )
        ).delete(synchronize_session=False)
        db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code.in_(["1", "2", "3", "4", "5"])
        ).delete()
        if emp_user_id:
            db.query(Employee).filter(Employee.user_id == emp_user_id).delete()
        db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class TestCreatePolicy:
    def test_create_success(self, client, db, make_user):
        _as_super(client, make_user)
        resp = client.post("/admin/policies/attendance/save",
                           data=_base_data(), follow_redirects=False)
        assert resp.status_code == 302
        assert "success=saved" in resp.headers["location"]
        # Verify DB
        p = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1",
            AttendancePolicy.is_active == True
        ).order_by(AttendancePolicy.id.desc()).first()
        assert p is not None
        assert p.effective_from_date == jdatetime.datetime.strptime(
            _FUTURE_START, "%Y/%m/%d").date().togregorian()
        assert p.late_allowed_minutes == 5
        assert p.late_enabled is True
        days = db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id == p.id
        ).all()
        assert len(days) == 7
        assert sum(1 for d in days if d.is_working_day) == 5
        _cleanup(db)

    def test_create_with_late_disabled(self, client, db, make_user):
        """late_enabled checkbox unchecked → policy should have late_enabled=False."""
        _as_super(client, make_user)
        data = _base_data()
        # Remove all working-day entries to create only Mon
        for wd in range(1, 7):
            data.pop(f"wd{wd}_working", None)
            data.pop(f"wd{wd}_start", None)
            data.pop(f"wd{wd}_end", None)
        data["effective_to_date_str"] = ""  # open-ended
        # Simulate unchecked toggles: pop late_enabled and early_leave_enabled
        # so their Form("") defaults kick in → False
        data.pop("late_enabled", None)
        data.pop("early_leave_enabled", None)
        data.pop("late_allowed_minutes", None)  # default 0
        resp = client.post("/admin/policies/attendance/save",
                           data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "success=saved" in resp.headers["location"]
        p = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1",
            AttendancePolicy.is_active == True
        ).order_by(AttendancePolicy.id.desc()).first()
        assert p is not None
        assert p.late_enabled is False
        assert p.late_allowed_minutes == 0
        _cleanup(db)


class TestEditPolicy:
    def test_edit_policy(self, client, db, make_user):
        _as_super(client, make_user)
        # Create
        client.post("/admin/policies/attendance/save",
                    data=_base_data(), follow_redirects=False)
        p = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1",
            AttendancePolicy.is_active == True
        ).order_by(AttendancePolicy.id.desc()).first()
        assert p is not None
        policy_id = p.id
        # Edit
        data = _base_data(
            effective_from_date_str="1408/02/01",
            late_allowed_minutes="15",
        )
        resp = client.post(f"/admin/policies/attendance/{policy_id}/update",
                           data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "success=updated" in resp.headers["location"]
        db.expire_all()
        p2 = db.query(AttendancePolicy).filter(AttendancePolicy.id == policy_id).first()
        assert p2.late_allowed_minutes == 15
        assert p2.effective_from_date == jdatetime.datetime.strptime(
            "1408/02/01", "%Y/%m/%d").date().togregorian()
        _cleanup(db)


class TestSoftDelete:
    def test_delete_future_policy_allowed(self, client, db, make_user):
        _as_super(client, make_user)
        client.post("/admin/policies/attendance/save",
                    data=_base_data(), follow_redirects=False)
        p = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1",
            AttendancePolicy.is_active == True
        ).order_by(AttendancePolicy.id.desc()).first()
        resp = client.post(f"/admin/policies/attendance/{p.id}/delete",
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "success=deleted" in resp.headers["location"]
        db.expire_all()
        p2 = db.query(AttendancePolicy).filter(AttendancePolicy.id == p.id).first()
        assert p2.is_active is False
        _cleanup(db)

    def test_delete_historical_policy_rejected(self, client, db, make_user):
        """Correction #5: policy with effective_from <= today must not be soft-deletable."""
        _as_super(client, make_user)
        policy = AttendancePolicy(
            employment_type_code="1",
            user_id=None,
            effective_from_date=jdatetime.datetime.strptime(
                _PAST_START, "%Y/%m/%d").date().togregorian(),
            late_enabled=True,
            late_allowed_minutes=5,
            late_reference_mode="FIXED_TIME",
            early_leave_enabled=True,
            early_leave_allowed_minutes=5,
            early_leave_reference_mode="FIXED_TIME",
            is_active=True,
        )
        db.add(policy)
        db.flush()
        db.add(AttendancePolicyDay(
            policy_id=policy.id, weekday=0, is_working_day=True,
            start_time=time(7, 0), end_time=time(14, 0),
        ))
        db.commit()
        resp = client.post(f"/admin/policies/attendance/{policy.id}/delete",
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        db.expire_all()
        assert db.query(AttendancePolicy).filter(
            AttendancePolicy.id == policy.id,
            AttendancePolicy.is_active == True
        ).first() is not None
        _cleanup(db)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_invalid_employment_type(self, client, db, make_user):
        _as_super(client, make_user)
        resp = client.post("/admin/policies/attendance/save",
                           data=_base_data(employment_type_code="99"),
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)

    def test_no_working_days(self, client, db, make_user):
        _as_super(client, make_user)
        data = _base_data()
        # Remove all working-day flags
        for wd in range(7):
            data.pop(f"wd{wd}_working", None)
            data.pop(f"wd{wd}_start", None)
            data.pop(f"wd{wd}_end", None)
        resp = client.post("/admin/policies/attendance/save",
                           data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)

    def test_start_after_end_time(self, client, db, make_user):
        """Working day with start >= end must be rejected."""
        _as_super(client, make_user)
        data = _base_data(wd0_start="16:00", wd0_end="08:00")
        resp = client.post("/admin/policies/attendance/save",
                           data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)

    def test_invalid_date_format(self, client, db, make_user):
        _as_super(client, make_user)
        resp = client.post("/admin/policies/attendance/save",
                           data=_base_data(effective_from_date_str="bad-date"),
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)

    def test_to_before_from_date(self, client, db, make_user):
        _as_super(client, make_user)
        resp = client.post("/admin/policies/attendance/save",
                           data=_base_data(
                               effective_from_date_str=_FUTURE_END,
                               effective_to_date_str=_FUTURE_START,
                           ), follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)

    def test_override_employee_not_found(self, client, db, make_user):
        _as_super(client, make_user)
        resp = client.post("/admin/policies/attendance/save",
                           data=_base_data(user_id_override="NONEXISTENT_USER"),
                           follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        _cleanup(db)


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------
class TestOverlap:
    def test_overlap_rejection(self, client, db, make_user):
        _as_super(client, make_user)
        # First policy
        r1 = client.post("/admin/policies/attendance/save",
                         data=_base_data(), follow_redirects=False)
        assert r1.status_code == 302
        assert "success=saved" in r1.headers["location"]
        # Second overlapping policy (same type, overlapping dates)
        r2 = client.post("/admin/policies/attendance/save",
                         data=_base_data(
                             effective_from_date_str="1408/03/01",
                             effective_to_date_str="1408/09/30",
                         ), follow_redirects=False)
        assert r2.status_code == 302
        assert "error=" in r2.headers["location"]
        _cleanup(db)

    def test_non_overlapping_allowed(self, client, db, make_user):
        """Two non-overlapping policies for the same type should both be allowed."""
        _as_super(client, make_user)
        r1 = client.post("/admin/policies/attendance/save",
                         data=_base_data(
                             effective_from_date_str=_FUTURE_START,
                             effective_to_date_str=_FUTURE_END,
                         ), follow_redirects=False)
        assert r1.status_code == 302
        assert "success=saved" in r1.headers["location"]
        r2 = client.post("/admin/policies/attendance/save",
                         data=_base_data(
                             effective_from_date_str=_FUTURE_START_B,
                             effective_to_date_str=_FUTURE_END_B,
                         ), follow_redirects=False)
        assert r2.status_code == 302
        assert "success=saved" in r2.headers["location"]
        _cleanup(db)


# ---------------------------------------------------------------------------
# Atomic Save
# ---------------------------------------------------------------------------
class TestAtomicSave:
    def test_rollback_on_schedule_error(self, client, db, make_user):
        """If schedule parsing fails, the entire policy + days must NOT be persisted."""
        _as_super(client, make_user)
        before = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1"
        ).count()
        # Submit a policy where Mon has start >= end (invalid)
        data = _base_data(wd0_start="16:00", wd0_end="08:00")
        resp = client.post("/admin/policies/attendance/save",
                           data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "error=" in resp.headers["location"]
        after = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == "1"
        ).count()
        assert after == before, "No new policy should be created on error"
        _cleanup(db)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
class TestAuthorization:
    def test_non_super_admin_gets_403(self, client, make_user):
        """require_super_admin blocks non-super roles."""
        creds = make_user(role="admin", balance_al=None)
        login_as(client, creds["national_code"])
        for method, path in [
            ("get", "/admin/policies/attendance"),
            ("get", "/admin/policies/attendance/add"),
        ]:
            resp = getattr(client, method)(path, follow_redirects=False)
            assert resp.status_code == 403, f"{method.upper()} {path} should be 403"
