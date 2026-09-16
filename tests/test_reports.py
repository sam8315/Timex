"""Tests for monthly-stats intro (معرفی) / settlement (تسویه) logic."""
from datetime import date, timedelta
from types import SimpleNamespace

import jdatetime

from models.contract import Contract
from models.employee import Employee
from web.routes.reports import get_day_code, resolve_intro_settle_dates
from .conftest import login_as


def _bounds(year, month):
    start_j = jdatetime.date(year, month, 1)
    if month == 12:
        end_j = jdatetime.date(year, 12, 29)
    else:
        end_j = jdatetime.date(year, month + 1, 1) - timedelta(days=1)
    return start_j.togregorian(), end_j.togregorian()


def _contract(start, end):
    return SimpleNamespace(start_date=start, end_date=end)


def test_no_contract_falls_back_to_hire_and_termination():
    ms, me = _bounds(1405, 5)
    hire = ms + timedelta(days=2)
    term = ms + timedelta(days=5)
    assert resolve_intro_settle_dates([], hire, term, ms, me) == (hire, term)


def test_no_contract_no_dates_returns_nones():
    ms, me = _bounds(1405, 5)
    assert resolve_intro_settle_dates([], None, None, ms, me) == (None, None)


def test_contract_start_in_month_is_intro():
    ms, me = _bounds(1405, 5)
    start = ms + timedelta(days=1)
    intro, settle = resolve_intro_settle_dates(
        [_contract(start, None)], date(1400, 1, 1), None, ms, me)
    assert intro == start
    assert settle is None


def test_spanning_contract_has_no_markers():
    ms, me = _bounds(1405, 5)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=40), me + timedelta(days=40))],
        ms - timedelta(days=100), None, ms, me)
    assert (intro, settle) == (None, None)


def test_contract_end_in_month_is_settle():
    ms, me = _bounds(1405, 5)
    end = ms + timedelta(days=4)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=40), end)], None, None, ms, me)
    assert settle == end


def test_back_to_back_contract_suppresses_settle():
    ms, me = _bounds(1405, 5)
    end = ms + timedelta(days=4)
    contracts = [_contract(ms - timedelta(days=40), end),
                 _contract(end + timedelta(days=1), None)]
    intro, settle = resolve_intro_settle_dates(
        contracts, None, None, ms, me)
    assert settle is None


def test_out_of_month_contract_dates_ignored():
    ms, me = _bounds(1405, 5)
    intro, settle = resolve_intro_settle_dates(
        [_contract(ms - timedelta(days=60), ms - timedelta(days=1))],
        None, None, ms, me)
    assert (intro, settle) == (None, None)


def test_day_code_intro_beats_settle_and_holiday():
    day = date(2026, 9, 3)
    assert get_day_code(day, {}, {}, set(), False, True,
                        hire_date=day, contract_end_date=day) == 'معرفی'
    assert get_day_code(day, {}, {}, set(), False, False,
                        hire_date=None,
                        contract_end_date=day) == 'تسویه'
    assert get_day_code(day, {}, {}, set(), False, True,
                        hire_date=None,
                        contract_end_date=None) == ''


def _set_employment(db, user_id, hire, term):
    db.query(Employee).filter(Employee.user_id == user_id).update(
        {"hire_date": hire, "termination_date": term})
    db.commit()


def test_monthly_stats_fallback_without_contract(client, db, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=None)
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    _set_employment(db, user["user_id"], ms + timedelta(days=2),
                    ms + timedelta(days=5))

    login_as(client, admin["national_code"])
    resp = client.post(
        "/reports/monthly-stats",
        data={"year": str(today_j.year), "month": str(today_j.month),
              "department": "all"},
    )
    assert resp.status_code == 200
    assert "معرفی" in resp.text
    assert "تسویه" in resp.text


def test_monthly_stats_contract_markers(client, db, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    user = make_user(role="user", balance_al=None)
    today_j = jdatetime.date.today()
    ms, me = _bounds(today_j.year, today_j.month)
    _set_employment(db, user["user_id"], ms - timedelta(days=100), None)
    db.add(Contract(
        user_id=user["user_id"], contract_type_code="4",
        start_date=ms + timedelta(days=1), end_date=ms + timedelta(days=4),
        annual_leave_days=30, sick_leave_days=0, service_deduction_days=0,
    ))
    db.commit()

    login_as(client, admin["national_code"])
    resp = client.post(
        "/reports/monthly-stats",
        data={"year": str(today_j.year), "month": str(today_j.month),
              "department": "all"},
    )
    assert resp.status_code == 200
    assert "معرفی" in resp.text
    assert "تسویه" in resp.text


def test_monthly_stats_excel_exports(client, make_user):
    admin = make_user(role="super_admin", balance_al=None)
    today_j = jdatetime.date.today()
    login_as(client, admin["national_code"])
    resp = client.get(
        "/reports/monthly-stats/excel",
        params={"year": today_j.year, "month": today_j.month,
                "department": "all"},
    )
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
