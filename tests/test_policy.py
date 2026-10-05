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
        "/admin/policies/regions/GRADE_2/update",
        data={"annual_leave_days": "36"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    region = db.query(Region).filter(Region.code == "GRADE_2").first()
    assert int(region.default_annual_leave_days) == 36
    assert _param(db, "annual_leave_days", "GRADE_2").parameter_value == "36"
    # restore seed value
    client.post("/admin/policies/regions/GRADE_2/update",
                data={"annual_leave_days": "40"},
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
        data={"region_applies_1": "on", "region_applies_3": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    # annual_leave_dept دیگر از این فرم نوشته نمی‌شود؛ فقط region_applies
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


def test_carry_forward_save_empty_means_unlimited(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/carry-forward/save",
        data={"cf_1": "", "cf_2": "0", "cf_3": "", "cf_4": "9",
              "cf_5": "", "pro_rata_method": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "carry_forward_dept_1").parameter_value == "none"
    assert _param(db, "carry_forward_dept_2").parameter_value == "0"
    assert _param(db, "carry_forward_dept_3").parameter_value == "none"
    from web.services.leave_entitlement_service import resolve_max_carry_forward
    assert resolve_max_carry_forward(db, "1") is None
    assert resolve_max_carry_forward(db, "2") == 0


def test_buyback_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/buyback/save",
        data={
            "bb_2": "0",
            "bb_3": "",
            "bb_4": "",
            "bb_5": "5",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "buyback_dept_2").parameter_value == "0"
    assert _param(db, "buyback_dept_4").parameter_value == "none"
    assert _param(db, "buyback_dept_5").parameter_value == "5"


def test_buyback_save_empty_clears_cap(client, db, make_user):
    """فیلد خالی باید به none ذخیره شود (بدون سقف)."""
    _as_super(client, make_user)
    client.post(
        "/admin/policies/buyback/save",
        data={"bb_2": "3", "bb_3": "4", "bb_4": "9", "bb_5": "5"},
        follow_redirects=False,
    )
    resp = client.post(
        "/admin/policies/buyback/save",
        data={"bb_2": "", "bb_3": "", "bb_4": "", "bb_5": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "buyback_dept_2").parameter_value == "none"
    assert _param(db, "buyback_dept_4").parameter_value == "none"
    assert _param(db, "buyback_dept_5").parameter_value == "none"


def test_buyback_permanent_save_merges_rules(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/buyback-permanent/save",
        data={
            "bb_region_NORMAL": "15",
            "bb_region_GRADE_2": "18",
            "bb_region_GRADE_3": "20",
            "bb_region_GRADE_4": "22",
            "bb_1": "12",
            "pre_1390_cap": "",
            "era_1390_1398_cap": "15",
            "grade4_from": "1391/07/15",
            "grade4_cap": "25",
            "modern_from_year": "1399",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "buyback_cap", region_code="NORMAL").parameter_value == "15"
    assert _param(db, "buyback_cap", region_code="GRADE_2").parameter_value == "18"
    assert _param(db, "buyback_dept_1").parameter_value == "12"
    assert _param(db, "max_buyback").parameter_value == "12"
    assert _param(db, "buyback_era_pre_1390_cap").parameter_value == "none"
    assert _param(db, "buyback_era_modern_from_year").parameter_value == "1399"


def test_buyback_regions_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/buyback-regions/save",
        data={
            "bb_region_NORMAL": "15",
            "bb_region_GRADE_2": "18",
            "bb_region_GRADE_3": "20",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "buyback_cap", region_code="NORMAL").parameter_value == "15"
    assert _param(db, "buyback_cap", region_code="GRADE_2").parameter_value == "18"
    assert _param(db, "buyback_cap", region_code="GRADE_3").parameter_value == "20"


def test_buyback_eras_save_persists(client, db, make_user):
    _as_super(client, make_user)
    resp = client.post(
        "/admin/policies/buyback-eras/save",
        data={
            "pre_1390_cap": "",
            "era_1390_1398_cap": "15",
            "grade4_from": "1391/07/15",
            "grade4_cap": "25",
            "modern_from_year": "1399",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    assert _param(db, "buyback_era_pre_1390_cap").parameter_value == "none"
    assert _param(db, "buyback_era_1390_1398_cap").parameter_value == "15"
    assert _param(db, "buyback_era_grade4_from").parameter_value == "1391/07/15"
    assert _param(db, "buyback_era_grade4_cap").parameter_value == "25"
    assert _param(db, "buyback_era_modern_from_year").parameter_value == "1399"


def test_leave_policy_page_shows_article11_sections(client, db, make_user):
    _as_super(client, make_user)
    resp = client.get("/admin/policies/leave")
    assert resp.status_code == 200
    body = resp.text
    assert "buyback-permanent/save" in body
    assert "بازخرید رسمی" in body
    assert "bb_region_NORMAL" in body
    assert "عادی" in body
    assert "درجه دو" in body
    assert "bb_region_GRADE_1" not in body
    assert "ماده ۱۱" in body
    assert "name=\"bb_1\"" in body


def test_profile_edit_manual_region_code_is_ignored(client, db, make_user):
    """Region is derived from service-location city; form field must not stick."""
    _as_super(client, make_user)
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
    assert emp.region_code == "NORMAL"
    hist = db.query(EmployeeRegion).filter(
        EmployeeRegion.user_id == target["user_id"],
        EmployeeRegion.region_code == "GRADE_2").first()
    assert hist is None
