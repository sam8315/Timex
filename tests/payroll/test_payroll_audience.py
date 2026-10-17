"""ملاک انتخاب افراد در محاسبه حقوق."""

from core.payroll.calendar_utils import jalali_month_bounds
from models.contract import Contract
from models.employee import Employee
from web.services.payroll.run_service import _eligible_employees

YEAR_J, MONTH_J = 1403, 1
MEMBERSHIP = "4"


def _month_bounds():
    return jalali_month_bounds(YEAR_J, MONTH_J)


def _user_ids(rows):
    return {row[0].user_id for row in rows}


def _eligible(db, mode: str, membership: str = MEMBERSHIP):
    month_start, month_end = _month_bounds()
    return _eligible_employees(
        db,
        month_start,
        month_end,
        membership,
        allowed_membership_codes={membership},
        audience_mode=mode,
    )


def test_contract_includes_inactive_with_valid_contract(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    emp = db.query(Employee).filter(Employee.user_id == creds["user_id"]).first()
    emp.is_active = False
    db.commit()

    assert creds["user_id"] in _user_ids(_eligible(db, "contract"))


def test_contract_excludes_without_contract(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    db.query(Contract).filter(Contract.user_id == creds["user_id"]).delete()
    db.commit()

    assert creds["user_id"] not in _user_ids(_eligible(db, "contract"))


def test_active_includes_active_without_contract(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    db.query(Contract).filter(Contract.user_id == creds["user_id"]).delete()
    db.commit()

    rows = _eligible(db, "active")
    assert creds["user_id"] in _user_ids(rows)
    row = next(r for r in rows if r[0].user_id == creds["user_id"])
    assert row[1] is None
    assert row[2] > 0


def test_active_excludes_inactive(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    emp = db.query(Employee).filter(Employee.user_id == creds["user_id"]).first()
    emp.is_active = False
    db.commit()

    assert creds["user_id"] not in _user_ids(_eligible(db, "active"))


def test_all_includes_inactive_without_contract(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    db.query(Contract).filter(Contract.user_id == creds["user_id"]).delete()
    emp = db.query(Employee).filter(Employee.user_id == creds["user_id"]).first()
    emp.is_active = False
    db.commit()

    assert creds["user_id"] in _user_ids(_eligible(db, "all"))


def test_all_three_modes_include_active_with_contract(db, make_user):
    creds = make_user(contract_type_code=MEMBERSHIP)
    for mode in ("contract", "active", "all"):
        rows = _eligible(db, mode)
        assert creds["user_id"] in _user_ids(rows)
        row = next(r for r in rows if r[0].user_id == creds["user_id"])
        assert row[1] is not None
        assert row[2] > 0
