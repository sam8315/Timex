"""Tests for admin leave-balances overview (year vs conscript period)."""
from datetime import date

import jdatetime
import pytest

from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_glossary import TX_CHARGE, TX_DEDUCT, TX_REVERSE, TX_USE
from models.leave_transaction import LeaveTransaction
from web.services.leave_balance_overview_service import (
    build_leave_balance_list_rows,
    get_user_al_period_snapshot,
    resolve_user_al_availability,
)
from web.services.leave_service import get_user_al_year_snapshot


def _add_tx(db, user_id, year, leave_type, amount, tx_type, ref=None):
    db.add(
        LeaveTransaction(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            amount=amount,
            transaction_type=tx_type,
            description="test",
            reference_id=ref,
        )
    )


def _add_bal(db, user_id, year, leave_type, balance):
    db.add(
        LeaveBalance(
            user_id=user_id,
            year=year,
            leave_type=leave_type,
            balance=balance,
        )
    )


class TestYearSnapshotRows:
    def test_non_conscript_year_row_matches_snapshot(self, db, make_user):
        user = make_user(role="user", balance_al=None, contract_type_code="4")
        uid = user["user_id"]
        year = jdatetime.date.today().year

        c = (
            db.query(Contract)
            .filter(Contract.user_id == uid)
            .order_by(Contract.id.desc())
            .first()
        )
        c.annual_leave_days = 26
        db.flush()
        _add_tx(db, uid, year, "AL", 26, TX_CHARGE)
        _add_tx(db, uid, year, "AL", 5, TX_USE)
        _add_bal(db, uid, year, "AL", 21)
        db.commit()

        snap = get_user_al_year_snapshot(db, uid, year)
        assert snap["entitlement"] == 26
        assert snap["used"] == 5

        grouped = {
            (uid, year): {
                "user_id": uid,
                "year": year,
                "AL": 21,
                "SL": None,
                "RL": None,
                "CW": None,
            }
        }
        rows = build_leave_balance_list_rows(
            db,
            grouped,
            {uid: {"code": "4", "name": "قراردادی"}},
            name_resolver=lambda u: "Test",
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["scope"] == "year"
        assert row["year"] == year
        assert row["al_entitlement"] == 26
        assert row["al_used"] == 5
        assert row["al_remaining"] == 26 - 5
        assert row["is_conscript"] is False


class TestEntitlementIgnoresReversedCharge:
    def test_reverse_subtracts_from_entitlement(self, db, make_user):
        user = make_user(role="user", balance_al=None, contract_type_code="4")
        uid = user["user_id"]
        year = jdatetime.date.today().year

        _add_tx(db, uid, year, "AL", 35, TX_CHARGE, ref=78)
        _add_tx(db, uid, year, "AL", 35, TX_REVERSE, ref=78)
        _add_tx(db, uid, year, "AL", 26, TX_CHARGE, ref=81)
        _add_tx(db, uid, year, "AL", 7, TX_DEDUCT, ref=81)
        _add_bal(db, uid, year, "AL", 19)
        db.commit()

        snap = get_user_al_year_snapshot(db, uid, year)
        # 35 - 35 + 26 - 7 = 19
        assert snap["entitlement"] == 19


class TestConscriptPeriodRows:
    def test_conscript_aggregates_all_years(self, db, make_user):
        user = make_user(
            role="user",
            balance_al=None,
            department="2",
            contract_type_code="2",
        )
        uid = user["user_id"]
        y1, y2 = 1403, 1404

        c = (
            db.query(Contract)
            .filter(Contract.user_id == uid)
            .order_by(Contract.id.desc())
            .first()
        )
        assert c is not None
        c.start_date = date(2024, 9, 22)
        c.end_date = date(2026, 10, 6)
        c.dispatch_date = date(2024, 9, 22)
        c.unit_entry_date = date(2024, 11, 21)
        c.annual_leave_days = 35
        db.flush()
        _add_tx(db, uid, y1, "AL", 17, TX_CHARGE)
        _add_tx(db, uid, y1, "AL", 4, TX_USE)
        _add_tx(db, uid, y1, "AL", 6, TX_DEDUCT)
        _add_bal(db, uid, y1, "AL", 7)

        _add_tx(db, uid, y2, "AL", 35, TX_CHARGE)
        _add_tx(db, uid, y2, "AL", 38, TX_USE)
        _add_bal(db, uid, y2, "AL", -3)
        db.commit()

        annual_before = c.annual_leave_days

        # Seed only one year in grouped (as year filter would); period still expands.
        grouped = {
            (uid, y2): {
                "user_id": uid,
                "year": y2,
                "AL": -3,
                "SL": None,
                "RL": None,
                "CW": None,
            }
        }
        rows = build_leave_balance_list_rows(
            db,
            grouped,
            {uid: {"code": "2", "name": "وظیفه"}},
            name_resolver=lambda u: "Conscript",
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["scope"] == "period"
        assert row["is_conscript"] is True
        assert y1 in row["years"] and y2 in row["years"]
        assert "دوره خدمت" in (row["period_label"] or "")

        period = get_user_al_period_snapshot(db, uid, [y1, y2])
        # entitlement: (17-6) + 35 = 46
        assert period["entitlement"] == 46
        assert period["used"] == 4 + 38
        assert row["al_entitlement"] == period["entitlement"]
        assert row["al_used"] == period["used"]
        # Remaining overview = entitlement - used (may diverge from LeaveBalance)
        assert row["al_remaining"] == period["entitlement"] - period["used"]
        assert row["al_remaining"] == 46 - 42
        assert period["remaining"] == row["al_remaining"]

        db.refresh(c)
        assert c.annual_leave_days == annual_before

        # داشبورد و صفحه مرخصی باید یک عدد ببینند (مانده دوره)
        avail = resolve_user_al_availability(db, uid, year_j=y2)
        assert avail["is_conscript"] is True
        assert avail["scope"] == "period"
        assert avail["total"] == period["remaining"]
        assert avail["total"] == row["al_remaining"]
