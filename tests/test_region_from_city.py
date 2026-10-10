"""Region service grade is derived from the effective service-location city."""
from datetime import date, timedelta

import jdatetime
import pytest

from models.city import City
from models.employee import Employee
from models.employee_region import EmployeeRegion
from models.employee_service_location import EmployeeServiceLocation
from web.services.leave_entitlement_service import (
    sync_employee_region_from_service_location,
    sync_employees_for_city,
)
from .conftest import login_as


def _today_j() -> str:
    return jdatetime.date.today().strftime("%Y/%m/%d")


def _make_city(db, *, name, region_code="NORMAL", lat=35.0, lon=51.0):
    city = City(
        name=name,
        province="TestProv",
        latitude=lat,
        longitude=lon,
        region_code=region_code,
        is_active=True,
    )
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


def test_service_location_sets_employee_region(db, make_user):
    user = make_user(role="user", region_code="NORMAL")
    city = _make_city(db, name=f"RegionCityA{user['user_id']}", region_code="GRADE_2")

    db.add(EmployeeServiceLocation(
        user_id=user["user_id"],
        city_id=city.id,
        effective_from=date.today() - timedelta(days=1),
        effective_to=None,
        created_by="test",
    ))
    db.flush()
    code = sync_employee_region_from_service_location(
        db, user["user_id"], commit=True, approved_by="test",
    )
    assert code == "GRADE_2"

    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.region_code == "GRADE_2"
    hist = (
        db.query(EmployeeRegion)
        .filter(
            EmployeeRegion.user_id == user["user_id"],
            EmployeeRegion.region_code == "GRADE_2",
            EmployeeRegion.effective_to.is_(None),
        )
        .first()
    )
    assert hist is not None


def test_end_service_location_resets_to_normal(client, db, make_user):
    admin = make_user(role="super_admin")
    user = make_user(role="user", region_code="NORMAL")
    city = _make_city(db, name=f"RegionCityB{user['user_id']}", region_code="GRADE_2")

    login_as(client, admin["national_code"])
    resp = client.post(
        "/admin/service-locations/add",
        data={
            "user_id": user["user_id"],
            "city_id": str(city.id),
            "address_text": "",
            "effective_from_str": _today_j(),
            "effective_to_str": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.region_code == "GRADE_2"

    loc = (
        db.query(EmployeeServiceLocation)
        .filter(EmployeeServiceLocation.user_id == user["user_id"])
        .first()
    )
    assert loc is not None
    resp = client.post(
        f"/admin/service-locations/{loc.id}/end",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.region_code == "NORMAL"


def test_city_region_change_syncs_employees(db, make_user):
    user = make_user(role="user", region_code="NORMAL")
    city = _make_city(db, name=f"RegionCityC{user['user_id']}", region_code="NORMAL")
    db.add(EmployeeServiceLocation(
        user_id=user["user_id"],
        city_id=city.id,
        effective_from=date.today() - timedelta(days=5),
        effective_to=None,
        created_by="test",
    ))
    db.commit()

    city.region_code = "GRADE_3"
    db.flush()
    n = sync_employees_for_city(db, city.id, commit=True, approved_by="test")
    assert n == 1

    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.region_code == "GRADE_3"


def test_profile_edit_ignores_manual_region_code(client, db, make_user):
    boss = make_user(role="super_admin")
    target = make_user(role="user", region_code="NORMAL", balance_al=None)
    login_as(client, boss["national_code"])

    resp = client.post(
        f"/admin/profile/{target['user_id']}/edit",
        data={
            "first_name": "تست",
            "last_name": target["user_id"],
            "is_active": "on",
            "region_code": "GRADE_2",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    emp = db.query(Employee).filter(Employee.user_id == target["user_id"]).first()
    # No service location → stays NORMAL; form field is ignored
    assert emp.region_code == "NORMAL"
    hist = db.query(EmployeeRegion).filter(
        EmployeeRegion.user_id == target["user_id"],
        EmployeeRegion.region_code == "GRADE_2",
    ).first()
    assert hist is None


def test_create_user_always_normal_region(client, db, make_user):
    from web.session import make_csrf_token

    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    token = make_csrf_token(super_u["user_id"])
    uid = f"RC{int(date.today().strftime('%Y%m%d'))}{super_u['user_id'][-4:]}"
    nc = "9012345678"
    # ensure unique national code
    while db.query(Employee).filter(Employee.national_code == nc).first():
        nc = str(int(nc) + 1)

    resp = client.post(
        "/admin/users/create",
        data={
            "user_id": uid,
            "name": "Region Create",
            "first_name": "علی",
            "last_name": "تستی",
            "national_code": nc,
            "membership_type_code": "4",
            "department_id": "",
            "region_code": "GRADE_3",
            "is_active": "on",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    emp = db.query(Employee).filter(Employee.user_id == uid).first()
    assert emp is not None
    assert emp.region_code == "NORMAL"


def test_create_form_has_no_region_select(client, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    resp = client.get("/admin/users/create")
    assert resp.status_code == 200
    assert 'name="region_code"' not in resp.text
    assert "منطقه خدمتی" in resp.text


def test_contract_charge_uses_city_region(client, db, make_user):
    """ثبت عضویت وظیفه با محل خدمت GRADE_2 باید استحقاق منطقه‌ای شارژ کند."""
    from models.policy import Policy, PolicyValue
    from models.region import Region
    from models.leave_balance import LeaveBalance
    from models.leave_glossary import LEAVE_TYPE_AL
    from models.contract import Contract
    from web.services.leave_entitlement_service import jalali_year_bounds_g

    admin = make_user(role="super_admin")
    user = make_user(role="user", department="2", region_code="NORMAL",
                     contract_type_code="2", balance_al=None)
    db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
    db.commit()

    city = _make_city(db, name=f"ChargeCity{user['user_id']}", region_code="GRADE_2")
    db.query(Region).filter(Region.code == "GRADE_2").update(
        {"default_annual_leave_days": 40}
    )
    policy = db.query(Policy).filter(Policy.category == "leave").first()
    if not policy:
        policy = Policy(category="leave", name="leave", is_active=True)
        db.add(policy)
        db.flush()
    from models.membership_type_rule import MembershipTypeRule
    rule = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == "2")
        .order_by(MembershipTypeRule.effective_from.desc())
        .first()
    )
    if rule:
        rule.annual_leave_base = 30
    for key, val in (("region_applies_dept_2", "true"),):
        pv = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == key,
            PolicyValue.region_code.is_(None),
        ).first()
        if pv:
            pv.parameter_value = val
        else:
            db.add(PolicyValue(policy_id=policy.id, parameter_key=key, parameter_value=val))
    scoped = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy.id,
        PolicyValue.parameter_key == "annual_leave_days",
        PolicyValue.region_code == "GRADE_2",
    ).first()
    if scoped:
        scoped.parameter_value = "40"
    else:
        db.add(PolicyValue(
            policy_id=policy.id, parameter_key="annual_leave_days",
            parameter_value="40", region_code="GRADE_2",
        ))
    year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(year)
    db.add(EmployeeServiceLocation(
        user_id=user["user_id"],
        city_id=city.id,
        effective_from=y_start,
        effective_to=None,
        created_by="test",
    ))
    db.commit()

    login_as(client, admin["national_code"])
    start_str = jdatetime.date.fromgregorian(date=y_start).strftime("%Y/%m/%d")
    end_str = jdatetime.date.fromgregorian(date=y_end).strftime("%Y/%m/%d")

    resp = client.post(
        "/admin/contracts/add",
        data={
            "user_id": user["user_id"],
            "contract_type_code": "2",
            "start_date_str": start_str,
            "end_date_str": end_str,
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.expire_all()
    emp = db.query(Employee).filter(Employee.user_id == user["user_id"]).first()
    assert emp.region_code == "GRADE_2"
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.id.desc())
        .first()
    )
    assert contract.annual_leave_days == 40
    bal = db.query(LeaveBalance).filter(
        LeaveBalance.user_id == user["user_id"],
        LeaveBalance.leave_type == LEAVE_TYPE_AL,
        LeaveBalance.year == year,
    ).first()
    assert bal is not None
    assert bal.balance == 40
