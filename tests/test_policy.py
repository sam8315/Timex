"""Tests for the global policy & region management (super-admin panel)."""
import itertools
import time

import pytest

from models.employee import Employee
from models.employee_region import EmployeeRegion
from models.policy import Policy, PolicyAuditLog, PolicyValue
from models.region import Region
from .conftest import login_as

_code_seq = itertools.count(int(time.time()) % 100000)


def _unique_code(prefix="TST"):
    return f"{prefix}{next(_code_seq) % 100000:05d}"


def _as_super(client, make_user):
    creds = make_user(role="super_admin", balance_al=None)
    resp = login_as(client, creds["national_code"])
    assert resp.status_code == 302
    return creds


def _leave_policy_id(db):
    return db.query(Policy).filter(Policy.category == "leave").first().id


def _param(db, key, region_code=None):
    q = db.query(PolicyValue).filter(
        PolicyValue.parameter_key == key)
    if region_code is None:
        q = q.filter(PolicyValue.region_code.is_(None))
    else:
        q = q.filter(PolicyValue.region_code == region_code)
    return q.first()


def test_policy_pages_load(client, make_user):
    _as_super(client, make_user)
    for path in ("/admin/policies", "/admin/policies/leave",
                 "/admin/policies/regions"):
        resp = client.get(path)
        assert resp.status_code == 200, path


def test_non_super_admin_cannot_post_policy(client, make_user):
    creds = make_user(role="admin", balance_al=None)
    login_as(client, creds["national_code"])
    resp = client.post(
        "/admin/policies/regions/add",
        data={"code": "XXX", "name": "X"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_add_region_success(client, db, make_user):
    _as_super(client, make_user)
    code = _unique_code()
    try:
        resp = client.post(
            "/admin/policies/regions/add",
            data={"code": code, "name": "تست", "description": "d",
                  "annual_leave_days": "37", "sort_order": "9"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "success=added" in resp.headers["location"]
        db.expire_all()
        region = db.query(Region).filter(Region.code == code).first()
        assert region is not None
        assert region.name == "تست"
        assert int(region.default_annual_leave_days) == 37
        pv = _param(db, "annual_leave_days", code)
        assert pv is not None and pv.parameter_value == "37"
        audit = db.query(PolicyAuditLog).filter(
            PolicyAuditLog.entity_type == "region",
            PolicyAuditLog.entity_id == code,
            PolicyAuditLog.action == "CREATE",
        ).first()
        assert audit is not None
    finally:
        db.query(PolicyValue).filter(
            PolicyValue.parameter_key == "annual_leave_days",
            PolicyValue.region_code == code).delete()
        db.query(Region).filter(Region.code == code).delete()
        db.commit()


def test_add_region_duplicate_code_rejected(client, db, make_user):
    _as_super(client, make_user)
    code = _unique_code("DUP")
    try:
        data = {"code": code, "name": "تست", "annual_leave_days": "30",
                "sort_order": "0"}
        assert client.post("/admin/policies/regions/add", data=data,
                           follow_redirects=False).status_code == 302
        dup = client.post("/admin/policies/regions/add", data=data,
                          follow_redirects=False)
        assert dup.status_code == 302
        assert "error=duplicate-code" in dup.headers["location"]
    finally:
        db.query(PolicyValue).filter(
            PolicyValue.parameter_key == "annual_leave_days",
            PolicyValue.region_code == code).delete()
        db.query(Region).filter(Region.code == code).delete()
        db.commit()


def test_add_region_invalid_code_rejected(client, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/regions/add",
        data={"code": "bad code!", "name": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=invalid-code" in resp.headers["location"]


def test_update_region_days(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/regions/GRADE_1/update",
        data={"annual_leave_days": "36"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    region = db.query(Region).filter(Region.code == "GRADE_1").first()
    assert int(region.default_annual_leave_days) == 36
    assert _param(db, "annual_leave_days", "GRADE_1").parameter_value == "36"
    # restore seed value
    client.post("/admin/policies/regions/GRADE_1/update",
                data={"annual_leave_days": "35"},
                follow_redirects=False)


def test_toggle_region_active(client, db, make_user):
    _as_super(client, make_user)
    before = db.query(Region).filter(
        Region.code == "GRADE_2").first().is_active
    resp = client.post("/admin/policies/regions/GRADE_2/toggle",
                       follow_redirects=False)
    assert resp.status_code == 302
    db.expire_all()
    after = db.query(Region).filter(
        Region.code == "GRADE_2").first().is_active
    assert after == (not before)
    # toggle back
    client.post("/admin/policies/regions/GRADE_2/toggle",
                follow_redirects=False)


def test_edit_region_full(client, db, make_user):
    _as_super(client, make_user)
    code = _unique_code("EDT")
    try:
        client.post(
            "/admin/policies/regions/add",
            data={"code": code, "name": "قبل", "description": "",
                  "annual_leave_days": "30", "sort_order": "1"},
            follow_redirects=False,
        )
        resp = client.post(
            f"/admin/policies/regions/{code}/edit",
            data={"name": "بعد", "description": "توضیح",
                  "sort_order": "5", "annual_leave_days": "41"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        db.expire_all()
        region = db.query(Region).filter(Region.code == code).first()
        assert region.name == "بعد"
        assert region.description == "توضیح"
        assert region.sort_order == 5
        assert int(region.default_annual_leave_days) == 41
    finally:
        db.query(PolicyValue).filter(
            PolicyValue.parameter_key == "annual_leave_days",
            PolicyValue.region_code == code).delete()
        db.query(PolicyAuditLog).filter(
            PolicyAuditLog.entity_type == "region",
            PolicyAuditLog.entity_id == code).delete()
        db.query(Region).filter(Region.code == code).delete()
        db.commit()


def test_delete_protected_region_rejected(client, make_user):
    _as_super(client, make_user)
    resp = client.post("/admin/policies/regions/NORMAL/delete",
                       follow_redirects=False)
    assert resp.status_code == 302
    assert "error=protected" in resp.headers["location"]


def test_delete_region_with_employees_rejected_then_allowed(
        client, db, make_user):
    _as_super(client, make_user)
    code = _unique_code("DEL")
    target = make_user(role="user", balance_al=None)
    try:
        client.post(
            "/admin/policies/regions/add",
            data={"code": code, "name": "حذف", "annual_leave_days": "30",
                  "sort_order": "0"},
            follow_redirects=False,
        )
        db.query(Employee).filter(
            Employee.user_id == target["user_id"]).update(
                {"region_code": code})
        db.commit()

        blocked = client.post(f"/admin/policies/regions/{code}/delete",
                              follow_redirects=False)
        assert blocked.status_code == 302
        assert "error=has-employees" in blocked.headers["location"]

        db.query(Employee).filter(
            Employee.user_id == target["user_id"]).update(
                {"region_code": "NORMAL"})
        db.commit()
        ok = client.post(f"/admin/policies/regions/{code}/delete",
                         follow_redirects=False)
        assert ok.status_code == 302
        assert "success=deleted" in ok.headers["location"]
        db.expire_all()
        assert db.query(Region).filter(Region.code == code).first() is None
    finally:
        db.query(PolicyValue).filter(
            PolicyValue.parameter_key == "annual_leave_days",
            PolicyValue.region_code == code).delete()
        db.query(PolicyAuditLog).filter(
            PolicyAuditLog.entity_type == "region",
            PolicyAuditLog.entity_id == code).delete()
        db.query(Region).filter(Region.code == code).delete()
        db.commit()


def test_employment_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/employment/save",
        data={"annual_1": "33", "annual_2": "34", "annual_3": "30",
              "annual_4": "30", "annual_5": "30",
              "region_applies_1": "on", "region_applies_3": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "annual_leave_dept_1").parameter_value == "33"
    assert _param(db, "annual_leave_dept_2").parameter_value == "34"
    assert _param(db, "region_applies_dept_1").parameter_value == "true"
    # unchecked boxes are stored as false
    assert _param(db, "region_applies_dept_2").parameter_value == "false"


def test_carry_forward_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/carry-forward/save",
        data={"cf_1": "5", "cf_2": "7", "cf_3": "9", "cf_4": "9",
              "cf_5": "9", "pro_rata_method": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "carry_forward_dept_1").parameter_value == "5"
    assert _param(db, "carry_forward_dept_2").parameter_value == "7"
    assert _param(db, "region_change_method").parameter_value == "pro_rata"


def test_buyback_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/buyback/save",
        data={"buyback_limit": "12"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "max_buyback").parameter_value == "12"


def test_profile_edit_region_change_is_audited(client, db, make_user):
    boss = _as_super(client, make_user)
    target = make_user(role="user", balance_al=None)
    resp = client.post(
        f"/admin/profile/{target['user_id']}/edit",
        data={"first_name": "تست", "last_name": target["user_id"],
              "is_active": "on", "region_code": "GRADE_2"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    emp = db.query(Employee).filter(
        Employee.user_id == target["user_id"]).first()
    assert emp.region_code == "GRADE_2"
    hist = db.query(EmployeeRegion).filter(
        EmployeeRegion.user_id == target["user_id"],
        EmployeeRegion.region_code == "GRADE_2").first()
    assert hist is not None
    assert hist.approved_by == boss["user_id"]
    audit = db.query(PolicyAuditLog).filter(
        PolicyAuditLog.entity_type == "employee_region",
        PolicyAuditLog.entity_id == target["user_id"]).first()
    assert audit is not None
