"""دستور مالی استعلاجی نتیجه ذخیره‌شده را تا اعمال صریح عوض نمی‌کند."""
from decimal import Decimal

import jdatetime
import pytest

from models.leave_financial_order import LeaveFinancialOrder
from models.leave_request import LeaveRequest
from models.payroll import (
    PayrollComponent,
    PayrollPeriod,
    PayrollResult,
    PayrollResultItem,
    PayrollRun,
)
from tests.conftest import login_as
from web.services.payroll.run_service import PayrollRunError, iter_calculate, reopen_run
from web.services.payroll.seed import ensure_payroll_defaults
from web.services.sick_leave_finance import queue_financial_orders


def _closed_result(db, user_id, status, amount, year_j=1391, month_j=7):
    period = (
        db.query(PayrollPeriod)
        .filter(PayrollPeriod.year_j == year_j, PayrollPeriod.month_j == month_j)
        .first()
    )
    if period is None:
        period = PayrollPeriod(year_j=year_j, month_j=month_j, status="open")
        db.add(period)
        db.flush()
    run = PayrollRun(
        period_id=period.id,
        status=status,
        created_by=user_id,
    )
    db.add(run)
    db.flush()
    result = PayrollResult(
        run_id=run.id,
        user_id=user_id,
        employee_name="تست",
        membership_type_code="4",
        covered_days=30,
        month_days=30,
        gross_earnings=amount,
        net_pay=amount,
    )
    db.add(result)
    db.flush()
    item = PayrollResultItem(
        result_id=result.id,
        component_code="DAILY_WAGE",
        component_name="حقوق",
        kind="earning",
        amount=amount,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return run, item


def _approved_sick(db, user_id, pays=False, year_j=1391, month_j=7):
    day = jdatetime.date(year_j, month_j, 10).togregorian()
    leave = LeaveRequest(
        user_id=user_id,
        leave_type="SL",
        from_date=day,
        to_date=day,
        days_count=1,
        status="A",
        employer_pays_wages=pays,
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


def test_cancel_keeps_stored_payroll_and_leaves_order_pending(db, make_user):
    creds = make_user()
    amount = Decimal("5000")
    run, item = _closed_result(db, creds["user_id"], "approved", amount)
    leave = _approved_sick(db, creds["user_id"])
    orders = queue_financial_orders(db, leave, "cancel", creds["user_id"], "لغو")
    db.commit()
    db.refresh(item)
    assert item.amount == amount
    assert run.status == "approved"
    assert len(orders) == 1
    assert orders[0].status == "pending"
    assert orders[0].resolution == "unspecified"


def test_open_run_order_stays_pending_until_calculate(db, make_user):
    creds = make_user()
    amount = Decimal("5000")
    _run, item = _closed_result(db, creds["user_id"], "calculated", amount, year_j=1391, month_j=8)
    leave = _approved_sick(db, creds["user_id"], year_j=1391, month_j=8)
    orders = queue_financial_orders(db, leave, "change", creds["user_id"], "تغییر بازه")
    db.commit()
    db.refresh(item)
    assert item.amount == amount
    assert orders[0].status == "pending"
    assert orders[0].resolution == "recalc"


def test_approved_run_refuses_silent_recalculate(db, make_user):
    creds = make_user()
    amount = Decimal("5000")
    run, item = _closed_result(db, creds["user_id"], "published", amount, year_j=1391, month_j=9)
    events = list(iter_calculate(db, run.id, [creds["user_id"]]))
    assert any(event.get("error") for event in events)
    db.refresh(item)
    assert item.amount == amount
    db.refresh(run)
    assert run.status == "published"


def test_reopen_requires_reason_and_idle_lock(db, make_user):
    creds = make_user()
    amount = Decimal("4200")
    run, item = _closed_result(db, creds["user_id"], "approved", amount, year_j=1391, month_j=10)
    with pytest.raises(PayrollRunError):
        reopen_run(db, run.id, creds["user_id"], "   ")
    run.calculating_by = creds["user_id"]
    db.commit()
    with pytest.raises(PayrollRunError):
        reopen_run(db, run.id, creds["user_id"], "بازگشایی آزمایشی")
    db.refresh(run)
    assert run.status == "approved"
    run.calculating_by = None
    db.commit()
    reopened = reopen_run(db, run.id, creds["user_id"], "بازگشایی آزمایشی")
    assert reopened.status == "calculated"
    db.refresh(item)
    assert item.amount == amount


def test_published_reopen_returns_to_calculated(db, make_user):
    creds = make_user()
    run, item = _closed_result(db, creds["user_id"], "published", Decimal("1000"), year_j=1391, month_j=11)
    reopened = reopen_run(db, run.id, creds["user_id"], "انتشار تا محاسبه مجدد پنهان می‌شود")
    assert reopened.status == "calculated"
    assert "reopen by" in (reopened.notes or "")
    db.refresh(item)
    assert item.amount == Decimal("1000")


def test_next_period_command_does_not_change_closed_result(client, db, make_user):
    admin = make_user(role="super_admin")
    target = make_user()
    amount = Decimal("3000")
    _run, item = _closed_result(db, target["user_id"], "approved", amount, year_j=1403, month_j=6)
    leave = _approved_sick(db, target["user_id"], pays=False, year_j=1403, month_j=6)
    ensure_payroll_defaults(db)
    component = db.query(PayrollComponent).filter(PayrollComponent.code == "DAILY_WAGE").one()
    previous = (component.sick_mode, component.absence_mode, component.day_basis)
    component.sick_mode = "exclude"
    component.absence_mode = "keep"
    component.day_basis = "fixed_30"
    db.commit()
    try:
        orders = queue_financial_orders(db, leave, "change", admin["user_id"], "تغییر پرداخت")
        db.commit()
        login_as(client, admin["national_code"])
        resp = client.post(
            f"/admin/leave-financial-orders/{orders[0].id}/apply",
            data={"resolution": "next_period", "reason": "تعدیل دوره بعد"},
        )
        assert resp.status_code == 302, resp.headers.get("location")
        location = resp.headers["location"]
        assert "success=" in location, location
        db.expire_all()
        db.refresh(item)
        assert item.amount == amount
        fresh = db.query(LeaveFinancialOrder).filter(LeaveFinancialOrder.id == orders[0].id).one()
        assert fresh.status == "pending"
        assert fresh.resolution == "next_period", location
        assert fresh.year_j == 1403
        assert fresh.month_j == 7
        assert fresh.run_id is None
        assert "DAILY_WAGE" in (fresh.after_amounts_json or "")
    finally:
        db.expire_all()
        component = db.query(PayrollComponent).filter(PayrollComponent.code == "DAILY_WAGE").one()
        component.sick_mode, component.absence_mode, component.day_basis = previous
        db.commit()
