"""استقلال نوع عضویت از دپارتمان سازمانی."""
from datetime import date, timedelta

from scripts.split_membership_department import apply_plan, build_plan, propose_membership, validate

from models.contract import Contract
from models.department import Department
from models.employee import Employee
from web.services.membership_resolve import (
    resolve_employee_membership,
    sync_employee_base_membership_from_active_contract,
)
from web.services.travel_leave_service import resolve_membership_code, resolve_policy


def test_contract_on_date_beats_base_membership(db, make_user):
    user = make_user(department="4", contract_type_code="4", balance_al=None)
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.membership_type_code = "1"
    db.query(Contract).filter_by(user_id=user["user_id"]).update(
        {Contract.contract_type_code: "4"}
    )
    db.commit()

    resolved = resolve_employee_membership(db, user["user_id"], date(2024, 6, 1))
    assert resolved.source == "contract"
    assert resolved.code == "4"
    assert emp.department_id is None


def test_base_membership_when_no_covering_contract(db, make_user):
    user = make_user(department="4", balance_al=None)
    db.query(Contract).filter_by(user_id=user["user_id"]).delete()
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.membership_type_code = "1"
    db.commit()

    resolved = resolve_employee_membership(db, user["user_id"], date.today())
    assert resolved.source == "base"
    assert resolved.code == "1"


def test_unresolved_does_not_guess_contractual(db, make_user):
    user = make_user(department="9", balance_al=None, create_employee=True)
    db.query(Contract).filter_by(user_id=user["user_id"]).delete()
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.membership_type_code = None
    db.commit()

    resolved = resolve_employee_membership(db, user["user_id"], date.today())
    assert resolved.source == "unresolved"
    assert resolved.code is None


def test_ambiguous_same_start_is_unresolved(db, make_user):
    user = make_user(balance_al=None)
    db.query(Contract).filter_by(user_id=user["user_id"]).delete()
    start = date(2024, 1, 1)
    db.add(Contract(
        user_id=user["user_id"], contract_type_code="1",
        start_date=start, end_date=None, annual_leave_days=0,
        sick_leave_days=0, service_deduction_days=0,
    ))
    db.add(Contract(
        user_id=user["user_id"], contract_type_code="4",
        start_date=start, end_date=None, annual_leave_days=0,
        sick_leave_days=0, service_deduction_days=0,
    ))
    db.commit()
    resolved = resolve_employee_membership(db, user["user_id"], date(2024, 6, 1))
    assert resolved.ambiguous is True
    assert resolved.code is None


def test_sync_updates_membership_not_department(db, make_user):
    user = make_user(department="3", balance_al=None)
    pharmacy = Department(name=f"داروخانه-{user['user_id']}", is_active=True, sort_order=1)
    db.add(pharmacy)
    db.flush()
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.department_id = pharmacy.id
    db.query(Contract).filter_by(user_id=user["user_id"]).delete()
    db.add(Contract(
        user_id=user["user_id"], contract_type_code="1",
        start_date=date.today() - timedelta(days=10), end_date=None,
        annual_leave_days=30, sick_leave_days=0, service_deduction_days=0,
    ))
    db.commit()

    code = sync_employee_base_membership_from_active_contract(db, user["user_id"], commit=True)
    db.refresh(emp)
    assert code == "1"
    assert emp.membership_type_code == "1"
    assert emp.department_id == pharmacy.id


def test_permanent_travel_uses_base_membership_not_department(db, make_user):
    user = make_user(department="4", contract_type_code="4", balance_al=None)
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.membership_type_code = "1"
    db.commit()

    assert resolve_membership_code(emp, None, db) == "1"
    policy, contract, _employee = resolve_policy(db, user["user_id"], date.today())
    assert contract is None
    if policy is not None:
        assert policy.contract_type_code == "1"


def test_changing_department_does_not_change_membership(db, make_user):
    user = make_user(department="1", contract_type_code="1", balance_al=None)
    finance = Department(name=f"مالی-{user['user_id']}", is_active=True, sort_order=2)
    pharmacy = Department(name=f"دارو-{user['user_id']}", is_active=True, sort_order=3)
    db.add_all([finance, pharmacy])
    db.flush()
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.department_id = finance.id
    db.commit()
    before = resolve_employee_membership(db, user["user_id"], date.today()).code
    emp.department_id = pharmacy.id
    db.commit()
    after = resolve_employee_membership(db, user["user_id"], date.today()).code
    assert before == after == "1"


def test_profile_get_does_not_rewrite_membership_or_department(client, db, make_user):
    from tests.conftest import login_as

    admin = make_user(role="admin")
    user = make_user(department="3", contract_type_code="1", balance_al=None)
    pharmacy = Department(name=f"دارو-پروفایل-{user['user_id']}", is_active=True, sort_order=1)
    db.add(pharmacy)
    db.flush()
    emp = db.query(Employee).filter_by(user_id=user["user_id"]).one()
    emp.department_id = pharmacy.id
    emp.membership_type_code = "3"
    db.commit()

    login_as(client, admin["national_code"])
    resp = client.get(f"/admin/profile/{user['user_id']}")
    assert resp.status_code == 200
    db.refresh(emp)
    assert emp.membership_type_code == "3"
    assert emp.department_id == pharmacy.id


def test_propose_membership_does_not_invent_department():
    known = {"1", "2", "4"}
    assert propose_membership(known, "1", "active_contract", "داروخانه") == ("1", "active_contract")
    assert propose_membership(known, None, None, "رسمی") == ("1", "legacy_membership_code")
    assert propose_membership(known, None, None, "واحد نامشخص") == (None, "unmapped_legacy_value")
    assert propose_membership(known, None, None, "") == (None, "empty_without_contract")
    assert propose_membership(known, "9", "latest_contract", "1")[0] is None


def test_backfill_fills_membership_and_leaves_department_empty(db, make_user):
    proven = make_user(department="1", contract_type_code="1", balance_al=None)
    ambiguous = make_user(department="4", balance_al=None, create_employee=True)
    db.query(Contract).filter_by(user_id=ambiguous["user_id"]).delete()
    emp_unknown = db.query(Employee).filter_by(user_id=ambiguous["user_id"]).one()
    emp_unknown.membership_type_code = None
    emp_proven = db.query(Employee).filter_by(user_id=proven["user_id"]).one()
    emp_proven.membership_type_code = None
    db.commit()

    before = db.query(Department).count()
    plan = build_plan(db)
    by_user = {row["user_id"]: row for row in plan["rows"]}
    assert by_user[proven["user_id"]]["proposed"] == "1"
    assert by_user[proven["user_id"]]["will_write"] is True
    assert by_user[ambiguous["user_id"]]["proposed"] is None
    assert by_user[ambiguous["user_id"]]["will_write"] is False

    written = apply_plan(db, plan)
    assert written >= 1
    db.refresh(emp_proven)
    db.refresh(emp_unknown)
    assert emp_proven.membership_type_code == "1"
    assert emp_proven.department_id is None
    assert emp_unknown.membership_type_code is None
    assert emp_unknown.department_id is None
    assert db.query(Department).count() == before
    assert validate(db, plan) == []

    again = build_plan(db)
    assert apply_plan(db, again) == 0


def test_backfill_reads_legacy_membership_without_contract(db, make_user):
    from sqlalchemy import text

    coded = make_user(balance_al=None)
    labeled = make_user(balance_al=None)
    unknown = make_user(balance_al=None)
    user_ids = [coded["user_id"], labeled["user_id"], unknown["user_id"]]
    db.query(Contract).filter(Contract.user_id.in_(user_ids)).delete(synchronize_session=False)
    db.query(Employee).filter(Employee.user_id.in_(user_ids)).update(
        {Employee.membership_type_code: None}, synchronize_session=False
    )
    db.commit()
    db.execute(text("ALTER TABLE employee ADD COLUMN IF NOT EXISTS department VARCHAR(100)"))
    db.execute(text("UPDATE employee SET department = :value WHERE user_id = :user_id"), [
        {"user_id": coded["user_id"], "value": "2"},
        {"user_id": labeled["user_id"], "value": "رسمی"},
        {"user_id": unknown["user_id"], "value": "واحد نامشخص"},
    ])
    db.commit()

    before = db.query(Department).count()
    try:
        plan = build_plan(db)
        rows = {row["user_id"]: row for row in plan["rows"]}
        assert rows[coded["user_id"]]["proposed"] == "2"
        assert rows[coded["user_id"]]["reason"] == "legacy_membership_code"
        assert rows[labeled["user_id"]]["proposed"] == "1"
        assert rows[labeled["user_id"]]["reason"] == "legacy_membership_code"
        assert rows[unknown["user_id"]]["proposed"] is None
        assert rows[unknown["user_id"]]["reason"] == "unmapped_legacy_value"

        apply_plan(db, plan)
        refreshed = {
            emp.user_id: emp
            for emp in db.query(Employee).filter(Employee.user_id.in_(user_ids)).all()
        }
        assert refreshed[coded["user_id"]].membership_type_code == "2"
        assert refreshed[labeled["user_id"]].membership_type_code == "1"
        assert refreshed[unknown["user_id"]].membership_type_code is None
        assert refreshed[coded["user_id"]].department_id is None
        assert db.query(Department).count() == before
        legacy = {
            user_id: db.execute(
                text("SELECT department FROM employee WHERE user_id = :user_id"),
                {"user_id": user_id},
            ).scalar()
            for user_id in user_ids
        }
        assert legacy[coded["user_id"]] == "2"
        assert legacy[labeled["user_id"]] == "رسمی"
        assert legacy[unknown["user_id"]] == "واحد نامشخص"
    finally:
        db.execute(text("ALTER TABLE employee DROP COLUMN IF EXISTS department"))
        db.commit()


def test_startup_drops_legacy_department_after_split():
    import inspect
    import database.init_db as init_db

    source = inspect.getsource(init_db.create_tables)
    split = inspect.getsource(init_db.migrate_department_membership_split)
    assert "migrate_drop_employee_department()" in source
    assert "ADD COLUMN department VARCHAR" not in split
