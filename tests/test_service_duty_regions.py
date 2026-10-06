"""تست پالیسی منطقه خدمت وظیفه + پایان محاسبه‌ای + شارژ کل دوره."""
from datetime import date, timedelta
from uuid import uuid4

import jdatetime
import pytest

from models.contract import Contract
from models.service_adjustment import ServiceAdjustment
from models.service_duty_region import ServiceDutyRegion
from web.services.leave_service import (
    calculate_prorated_leave_by_year,
    charge_leave_for_new_contract,
)
from web.services.service_adjustment_service import create_adjustment
from web.services.service_duty_region_service import (
    ServiceDutyRegionError,
    create_duty_region,
    delete_duty_region,
    resolve_service_duration_months,
    seed_default_duty_regions,
    update_duty_region,
)
from web.services.service_end_date_engine import (
    add_jalali_months,
    apply_end_date_to_contract,
    compute_legal_end_date,
)


@pytest.fixture
def duty_region(db):
    seed_default_duty_regions(db)
    db.commit()
    row = db.query(ServiceDutyRegion).filter_by(code="NORMAL_DUTY").first()
    assert row is not None
    return row


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8].upper()}"


class TestDutyRegionCrud:
    def test_create_and_resolve_native_affects(self, db):
        code = _uniq("TEST_OP")
        create_duty_region(
            db,
            name="تست عملیاتی",
            code=code,
            native_affects=True,
            duration_months_native=15,
            duration_months_non_native=14,
        )
        db.commit()
        assert resolve_service_duration_months(db, code, False) == 14
        assert resolve_service_duration_months(db, code, True) == 15

    def test_create_without_native(self, db):
        code = _uniq("TEST_AMR")
        create_duty_region(
            db,
            name="امریه تست",
            code=code,
            native_affects=False,
            duration_months=24,
        )
        db.commit()
        assert resolve_service_duration_months(db, code, None) == 24

    def test_delete_blocked_when_in_use(self, db, make_user, duty_region):
        user = make_user(role="user")
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=date(2025, 3, 21),
            end_date=date(2026, 9, 21),
            annual_leave_days=30,
            service_duty_region_code=duty_region.code,
            dispatch_date=date(2025, 3, 21),
            is_native=False,
        )
        db.add(c)
        db.commit()
        with pytest.raises(ServiceDutyRegionError):
            delete_duty_region(db, duty_region.code)

    def test_update_name_and_months(self, db, duty_region):
        update_duty_region(
            db,
            duty_region.code,
            name="مناطق عادی ویرایش‌شده",
            native_affects=True,
            duration_months_native=22,
            duration_months_non_native=19,
            sort_order=duty_region.sort_order,
            is_active=True,
        )
        db.commit()
        assert resolve_service_duration_months(db, duty_region.code, True) == 22


class TestEndDateEngine:
    def test_legal_end_from_dispatch(self, db):
        code = _uniq("END_CALC")
        create_duty_region(
            db,
            name="منطقه پایان‌تست",
            code=code,
            native_affects=True,
            duration_months_native=21,
            duration_months_non_native=18,
        )
        db.commit()
        dispatch_j = jdatetime.date(1404, 1, 1)
        dispatch = dispatch_j.togregorian()
        end = compute_legal_end_date(
            db,
            dispatch_date=dispatch,
            region_code=code,
            is_native=False,
        )
        expected = add_jalali_months(dispatch, 18) - timedelta(days=1)
        assert end == expected

    def test_adjustment_shortens_end(self, db, make_user):
        code = _uniq("ADJ_CALC")
        create_duty_region(
            db,
            name="منطقه تعدیل‌تست",
            code=code,
            native_affects=False,
            duration_months=18,
        )
        db.commit()
        user = make_user(role="user")
        dispatch = jdatetime.date(1404, 1, 1).togregorian()
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=dispatch,
            dispatch_date=dispatch,
            service_duty_region_code=code,
            is_native=False,
            annual_leave_days=30,
        )
        db.add(c)
        db.flush()
        apply_end_date_to_contract(db, c)
        legal_end = c.end_date
        db.commit()

        create_adjustment(
            db,
            employee_id=user["user_id"],
            adjustment_type="service_deduction",
            effective_date=dispatch,
            months=1,
            contract_id=c.id,
            created_by="test",
        )
        db.commit()
        db.refresh(c)
        assert c.end_date < legal_end


class TestConscriptFullPeriodCharge:
    def test_charge_spans_multiple_years(self, db, make_user):
        code = _uniq("CHARGE_CALC")
        create_duty_region(
            db,
            name="منطقه شارژ‌تست",
            code=code,
            native_affects=False,
            duration_months=18,
        )
        db.commit()
        user = make_user(role="user")
        # دوره ۱۸ ماهه که از مرز سال شمسی عبور کند
        dispatch = jdatetime.date(1403, 10, 1).togregorian()
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=dispatch,
            dispatch_date=dispatch,
            service_duty_region_code=code,
            is_native=False,
            annual_leave_days=30,
        )
        db.add(c)
        db.flush()
        apply_end_date_to_contract(db, c)
        db.commit()

        by_year = calculate_prorated_leave_by_year(c, db=db)
        assert len(by_year) >= 2
        charged = charge_leave_for_new_contract(db, c)
        assert len(charged) >= 2


class TestLeaveStartDateBasis:
    @pytest.fixture(autouse=True)
    def _reset_basis(self, db):
        yield
        self._set_basis(db, "dispatch")

    def _set_basis(self, db, basis: str):
        from models.membership_type_rule import MembershipTypeRule
        from web.services.membership_service import get_effective_rule

        rule = get_effective_rule(db, "2")
        assert rule is not None
        db.query(MembershipTypeRule).filter(
            MembershipTypeRule.membership_type_code == "2",
            MembershipTypeRule.status == "active",
        ).update({"leave_start_date_basis": basis})
        db.commit()

    def test_dispatch_basis_matches_start(self, db, make_user, duty_region):
        from web.services.leave_entitlement_service import split_contract_coverage_by_year
        from web.services import membership_semantics as msem

        self._set_basis(db, "dispatch")
        user = make_user(role="user")
        dispatch = jdatetime.date(1404, 1, 1).togregorian()
        unit = jdatetime.date(1404, 2, 1).togregorian()
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=dispatch,
            dispatch_date=dispatch,
            unit_entry_date=unit,
            service_duty_region_code=duty_region.code,
            is_native=False,
            annual_leave_days=30,
        )
        db.add(c)
        db.flush()
        apply_end_date_to_contract(db, c)
        db.commit()

        assert msem.resolve_conscript_leave_start(db, c) == dispatch
        segs = split_contract_coverage_by_year(c, db=db)
        assert segs
        assert segs[0][1] == dispatch

    def test_unit_entry_basis_shifts_coverage_start(self, db, make_user, duty_region):
        from web.services.leave_entitlement_service import split_contract_coverage_by_year
        from web.services import membership_semantics as msem

        self._set_basis(db, "unit_entry")
        user = make_user(role="user")
        dispatch = jdatetime.date(1404, 1, 1).togregorian()
        unit = jdatetime.date(1404, 2, 15).togregorian()
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=dispatch,
            dispatch_date=dispatch,
            unit_entry_date=unit,
            service_duty_region_code=duty_region.code,
            is_native=False,
            annual_leave_days=30,
        )
        db.add(c)
        db.flush()
        apply_end_date_to_contract(db, c)
        end_before = c.end_date
        db.commit()

        assert msem.resolve_conscript_leave_start(db, c) == unit
        segs = split_contract_coverage_by_year(c, db=db)
        assert segs
        assert segs[0][1] == unit
        # پایان خدمت همچنان از اعزام
        assert c.end_date == end_before
        assert c.end_date == compute_legal_end_date(
            db,
            dispatch_date=dispatch,
            region_code=duty_region.code,
            is_native=False,
        )

    def test_missing_unit_entry_validation(self, db, make_user, duty_region):
        from web.routes.admin_contracts import _apply_conscript_fields

        self._set_basis(db, "unit_entry")
        user = make_user(role="user")
        dispatch = jdatetime.date(1404, 1, 1).togregorian()
        c = Contract(
            user_id=user["user_id"],
            contract_type_code="2",
            start_date=dispatch,
            annual_leave_days=30,
        )
        db.add(c)
        db.flush()

        class _Form(dict):
            def get(self, k, default=None):
                return super().get(k, default)

        form = _Form(
            {
                "dispatch_date_str": "1404/01/01",
                "unit_entry_date_str": "",
                "clinic_entry_date_str": "",
                "service_duty_region_code": duty_region.code,
                "is_native": "0",
            }
        )
        with pytest.raises(ValueError, match="ورود به یگان"):
            _apply_conscript_fields(
                db,
                c,
                contract_type_code="2",
                form=form,
                start_date=dispatch,
            )
