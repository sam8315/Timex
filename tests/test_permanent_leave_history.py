"""تست تاریخچه مرخصی قرارداد رسمی: CHARGE/USE/CW و ویرایش."""
from datetime import timedelta

import jdatetime
import pytest

from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_transaction import LeaveTransaction
from models.leave_glossary import (
    LEAVE_TYPE_AL,
    LEAVE_TYPE_CW,
    MEMBERSHIP_PERMANENT,
    TX_CHARGE,
    TX_CF_OUT,
    TX_USE,
)
from models.policy import Policy, PolicyValue
from web.services.leave_entitlement_service import jalali_year_bounds_g
from web.services.leave_service import get_buyback_quota, get_stored_leave_balance
from web.services.permanent_leave_history_service import (
    HISTORY_PREFIX,
    apply_permanent_history,
    build_year_plan,
    get_used_by_year_from_contract,
)


def _seed_leave_policy(db, *, annual=30, cf_cap=9, buyback_cap=15, clear_periods=True):
    # بازه‌های dated اگر باشند بر legacy غالب‌اند؛ برای تست‌های cap ثابت پاک می‌کنیم
    if clear_periods:
        from models.leave_settlement_cap_period import LeaveSettlementCapPeriod
        db.query(LeaveSettlementCapPeriod).delete()
        db.flush()

    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(category='leave', name='test leave', is_active=True)
        db.add(policy)
        db.flush()

    def upsert(key, value, region_code=None):
        q = db.query(PolicyValue).filter(
            PolicyValue.policy_id == policy.id,
            PolicyValue.parameter_key == key,
        )
        if region_code is None:
            q = q.filter(PolicyValue.region_code.is_(None))
        else:
            q = q.filter(PolicyValue.region_code == region_code)
        existing = q.first()
        if existing:
            existing.parameter_value = str(value)
        else:
            db.add(PolicyValue(
                policy_id=policy.id,
                parameter_key=key,
                parameter_value=str(value),
                region_code=region_code,
            ))

    from models.membership_type_rule import MembershipTypeRule
    rule = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == '1')
        .order_by(MembershipTypeRule.effective_from.desc())
        .first()
    )
    if rule:
        rule.annual_leave_base = int(annual)
    upsert('region_applies_dept_1', 'false')
    upsert('carry_forward_dept_1', cf_cap if cf_cap is not None else '')
    upsert('buyback_dept_1', buyback_cap if buyback_cap is not None else '')
    db.commit()
    return policy


def _make_permanent(db, user_id, start_g, annual=30):
    end_g = start_g + timedelta(days=365 * 30)
    c = Contract(
        user_id=user_id,
        contract_type_code=MEMBERSHIP_PERMANENT,
        start_date=start_g,
        end_date=end_g,
        annual_leave_days=annual,
        sick_leave_days=0,
        service_deduction_days=0,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


class TestBuildYearPlan:
    def test_years_from_hire_to_current_minus_one(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_leave_policy(db, annual=30, cf_cap=9)
        current = jdatetime.date.today().year
        start_j = jdatetime.date(current - 3, 1, 1)
        plan = build_year_plan(
            db, user_id=user["user_id"], start_date=start_j.togregorian()
        )
        years = [r['year'] for r in plan]
        assert years == list(range(current - 3, current))
        assert all(r['entitlement'] == 30 for r in plan)

    def test_start_current_year_empty_plan(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        _seed_leave_policy(db)
        current = jdatetime.date.today().year
        start_g, _ = jalali_year_bounds_g(current)
        plan = build_year_plan(db, user_id=user["user_id"], start_date=start_g)
        assert plan == []


class TestApplyPermanentHistory:
    def test_charge_use_and_cw_from_1380_style(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        current = jdatetime.date.today().year
        # سه سال گذشته کامل
        start_j = jdatetime.date(current - 3, 1, 1)
        contract = _make_permanent(db, user["user_id"], start_j.togregorian())

        used = {
            current - 3: 25,  # unused 5 → carry 5
            current - 2: 20,  # unused 10 → carry 9 (cap)
            current - 1: 30,  # unused 0
        }
        result = apply_permanent_history(db, contract, used, commit=True)

        assert result['stored_cw'] == 5 + 9 + 0
        # سقف بازخرید هر سال (legacy=۱۵): min(5,15)+min(9,15)+0
        assert result['buyback'] == 5 + 9

        txs = db.query(LeaveTransaction).filter(
            LeaveTransaction.reference_id == contract.id,
            LeaveTransaction.description.like(f"{HISTORY_PREFIX}%"),
        ).all()
        charge_years = {
            t.year for t in txs
            if t.transaction_type == TX_CHARGE and t.leave_type == LEAVE_TYPE_AL
        }
        use_years = {
            t.year for t in txs
            if t.transaction_type == TX_USE and t.leave_type == LEAVE_TYPE_AL
        }
        cf_out = [
            t for t in txs
            if t.transaction_type == TX_CF_OUT and t.leave_type == LEAVE_TYPE_AL
        ]
        assert charge_years == {current - 3, current - 2, current - 1}
        assert use_years == {current - 3, current - 2, current - 1}
        assert sum(t.amount for t in cf_out) == 14

        assert get_stored_leave_balance(db, user["user_id"], current) == 14
        assert get_buyback_quota(db, user["user_id"], current) == 14
        assert get_used_by_year_from_contract(db, contract.id) == used

    def test_edit_used_replaces_history_and_cw(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        current = jdatetime.date.today().year
        start_j = jdatetime.date(current - 2, 1, 1)
        contract = _make_permanent(db, user["user_id"], start_j.togregorian())

        apply_permanent_history(
            db, contract, {current - 2: 0, current - 1: 0}, commit=True
        )
        assert get_stored_leave_balance(db, user["user_id"], current) == 9 + 9

        apply_permanent_history(
            db, contract, {current - 2: 30, current - 1: 21}, commit=True
        )
        # year-2: unused 0; year-1: unused 9 → CW 9
        assert get_stored_leave_balance(db, user["user_id"], current) == 9
        assert get_used_by_year_from_contract(db, contract.id)[current - 1] == 21

        # فقط یک CHARGE/USE به ازای هر سال تاریخچه
        al_charge = db.query(LeaveTransaction).filter(
            LeaveTransaction.reference_id == contract.id,
            LeaveTransaction.transaction_type == TX_CHARGE,
            LeaveTransaction.leave_type == LEAVE_TYPE_AL,
            LeaveTransaction.description.like(f"{HISTORY_PREFIX}%"),
        ).count()
        assert al_charge == 2

    def test_used_over_entitlement_raises(self, db, make_user):
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30)
        current = jdatetime.date.today().year
        start_j = jdatetime.date(current - 1, 1, 1)
        contract = _make_permanent(db, user["user_id"], start_j.togregorian())
        with pytest.raises(ValueError, match="بیشتر از استحقاق"):
            apply_permanent_history(db, contract, {current - 1: 99}, commit=True)

    def test_unlimited_storage_period_carries_all_unused(self, db, make_user):
        """مثل ۱۳۸۰: سقف ذخیره نامحدود → کل استحقاق استفاده‌نشده به CW."""
        from web.services.leave_settlement.caps import create_period

        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=35, cf_cap=9, buyback_cap=None)

        current = jdatetime.date.today().year
        y = current - 1
        start_j = jdatetime.date(y, 1, 1)
        y_start, y_end = jalali_year_bounds_g(y)
        create_period(
            db,
            membership_code="1",
            region_code=None,
            effective_from=y_start,
            effective_to=y_end,
            storage_cap=None,
            buyback_cap=None,
            created_by="test",
            commit=True,
        )

        contract = _make_permanent(db, user["user_id"], start_j.togregorian(), annual=35)
        result = apply_permanent_history(db, contract, {y: 0}, commit=True)
        assert result['stored_cw'] == 35
        assert get_stored_leave_balance(db, user["user_id"], current) == 35
        assert result['buyback'] == 35
        year_row = next(r for r in result['years'] if r['year'] == y)
        assert year_row['storage_cap'] is None
        assert year_row['carried'] == 35

    def test_buyback_accumulates_per_year_caps(self, db, make_user):
        """بازخرید = جمع min(انتقال، سقف بازخرید همان سال)، نه فقط سقف سال جاری."""
        from web.services.leave_settlement.caps import create_period

        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        current = jdatetime.date.today().year
        y1, y2 = current - 2, current - 1
        s1, e1 = jalali_year_bounds_g(y1)
        s2, e2 = jalali_year_bounds_g(y2)
        create_period(
            db, membership_code="1", region_code=None,
            effective_from=s1, effective_to=e1,
            storage_cap=None, buyback_cap=None, created_by="test", commit=False,
        )
        create_period(
            db, membership_code="1", region_code=None,
            effective_from=s2, effective_to=e2,
            storage_cap=None, buyback_cap=10, created_by="test", commit=True,
        )
        start_j = jdatetime.date(y1, 1, 1)
        contract = _make_permanent(db, user["user_id"], start_j.togregorian())
        result = apply_permanent_history(
            db, contract, {y1: 0, y2: 0}, commit=True
        )
        # y1: carry 30, bb unlimited → 30; y2: carry 30, bb 10 → 10
        assert result['stored_cw'] == 60
        assert result['buyback'] == 40
        assert get_buyback_quota(db, user["user_id"], current) == 40

    def test_http_add_forces_permanent_end_date(self, client, db, make_user):
        from .conftest import login_as
        from web.routes.admin_contracts import add_years

        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        login_as(client, admin["national_code"])
        current = jdatetime.date.today().year
        start_j = jdatetime.date(current - 1, 1, 1)
        r = client.post(
            "/admin/contracts/add",
            data={
                "user_id": user["user_id"],
                "contract_type_code": "1",
                "start_date_str": start_j.strftime("%Y/%m/%d"),
                "end_date_str": f"{current + 1}/01/01",  # باید نادیده گرفته شود
                "annual_leave_days": "0",
                "sick_leave_days": "0",
                "service_deduction_days": "0",
                "stored_leave_days": "0",
                "buyback_leave_days": "0",
                f"used_{current - 1}": "0",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "error" not in (r.headers.get("location") or "")
        contract = (
            db.query(Contract)
            .filter(Contract.user_id == user["user_id"], Contract.contract_type_code == "1")
            .order_by(Contract.id.desc())
            .first()
        )
        assert contract is not None
        assert contract.end_date == add_years(start_j.togregorian(), 30)

    def test_http_add_permanent_with_used_fields(self, client, db, make_user):
        from .conftest import login_as

        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        login_as(client, admin["national_code"])
        current = jdatetime.date.today().year
        start_str = f"{current - 2}/01/01"
        data = {
            "user_id": user["user_id"],
            "contract_type_code": "1",
            "start_date_str": start_str,
            "end_date_str": "",
            "annual_leave_days": "0",
            "sick_leave_days": "0",
            "service_deduction_days": "0",
            "stored_leave_days": "0",
            "buyback_leave_days": "0",
            f"used_{current - 2}": "10",
            f"used_{current - 1}": "15",
        }
        r = client.post("/admin/contracts/add", data=data, follow_redirects=False)
        assert r.status_code == 302
        assert "error" not in (r.headers.get("location") or "")

        contract = (
            db.query(Contract)
            .filter(
                Contract.user_id == user["user_id"],
                Contract.contract_type_code == MEMBERSHIP_PERMANENT,
            )
            .order_by(Contract.id.desc())
            .first()
        )
        assert contract is not None
        used = get_used_by_year_from_contract(db, contract.id)
        assert used.get(current - 2) == 10
        assert used.get(current - 1) == 15
        # unused: 20 + 15 with cap 9 → 9+9
        db.expire_all()
        assert get_stored_leave_balance(db, user["user_id"], current) == 18

    def test_http_edit_permanent_history_updates_used_and_cw(self, client, db, make_user):
        from .conftest import login_as

        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.query(LeaveBalance).filter(LeaveBalance.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)

        login_as(client, admin["national_code"])
        current = jdatetime.date.today().year
        start_str = f"{current - 2}/01/01"
        add = client.post(
            "/admin/contracts/add",
            data={
                "user_id": user["user_id"],
                "contract_type_code": "1",
                "start_date_str": start_str,
                "end_date_str": "",
                "annual_leave_days": "0",
                "sick_leave_days": "0",
                "service_deduction_days": "0",
                "stored_leave_days": "0",
                "buyback_leave_days": "0",
                f"used_{current - 2}": "0",
                f"used_{current - 1}": "0",
            },
            follow_redirects=False,
        )
        assert add.status_code == 302
        assert "error" not in (add.headers.get("location") or "")
        contract = (
            db.query(Contract)
            .filter(Contract.user_id == user["user_id"], Contract.contract_type_code == "1")
            .order_by(Contract.id.desc())
            .first()
        )
        assert contract is not None
        db.expire_all()
        assert get_stored_leave_balance(db, user["user_id"], current) == 18

        edit = client.post(
            f"/admin/contracts/{contract.id}/edit",
            data={
                "contract_type_code": "1",
                "start_date_str": start_str,
                "end_date_str": "",
                "annual_leave_days": "0",
                "sick_leave_days": "0",
                "service_deduction_days": "0",
                "stored_leave_days": "0",
                "buyback_leave_days": "0",
                f"used_{current - 2}": "30",
                f"used_{current - 1}": "21",
            },
            follow_redirects=False,
        )
        assert edit.status_code == 302
        assert "error" not in (edit.headers.get("location") or "")
        db.expire_all()
        used = get_used_by_year_from_contract(db, contract.id)
        assert used.get(current - 2) == 30
        assert used.get(current - 1) == 21
        # year-2 unused 0; year-1 unused 9 → CW 9
        assert get_stored_leave_balance(db, user["user_id"], current) == 9
        assert get_buyback_quota(db, user["user_id"], current) == 9

    def test_http_delete_permanent_contract(self, client, db, make_user):
        from .conftest import login_as

        admin = make_user(role="super_admin", balance_al=None)
        user = make_user(department="1", balance_al=None, contract_type_code="1")
        db.query(Contract).filter(Contract.user_id == user["user_id"]).delete()
        db.commit()
        _seed_leave_policy(db, annual=30, cf_cap=9, buyback_cap=15)
        login_as(client, admin["national_code"])
        current = jdatetime.date.today().year
        r = client.post(
            "/admin/contracts/add",
            data={
                "user_id": user["user_id"],
                "contract_type_code": "1",
                "start_date_str": f"{current - 1}/01/01",
                "end_date_str": "",
                "annual_leave_days": "0",
                "sick_leave_days": "0",
                "service_deduction_days": "0",
                "stored_leave_days": "0",
                "buyback_leave_days": "0",
                f"used_{current - 1}": "5",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        contract = (
            db.query(Contract)
            .filter(Contract.user_id == user["user_id"], Contract.contract_type_code == "1")
            .order_by(Contract.id.desc())
            .first()
        )
        assert contract is not None
        cid = contract.id
        d = client.post(
            f"/admin/contracts/{cid}/delete",
            follow_redirects=False,
        )
        assert d.status_code == 302
        loc = d.headers.get("location") or ""
        assert "error" not in loc
        db.expire_all()
        assert db.query(Contract).filter(Contract.id == cid).first() is None
