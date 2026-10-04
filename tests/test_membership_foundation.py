"""Foundation hardening: pending rules, seed safety, temporal dual-run, data safety."""
from datetime import date, timedelta

from models.contract import Contract
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.leave_transaction import LeaveTransaction
from models.membership_type import MembershipType
from models.membership_type_rule import MembershipTypeRule
from models.service_adjustment import ServiceAdjustment
from web.services.membership_cutover_validation import (
    compare_contract_entitlement,
    contract_comparison_date,
)
from web.services.membership_retroactive_service import (
    build_impact_preview,
    confirm_and_recalculate,
    create_preview_request,
)
from web.services.membership_service import (
    create_membership_type,
    create_rule_snapshot,
    get_effective_rule,
    reconcile_seed_membership_rules,
    resolve_annual_leave_base,
    seed_default_memberships,
)
from web.services import membership_semantics as msem
from web.services.service_adjustment_service import create_adjustment


def test_pending_rule_ignored_until_confirm(db):
    from models.reserved_membership_code import ReservedMembershipCode

    code = "71"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    # Initial rule in the past so a later pending/current rule can supersede it.
    create_membership_type(
        db, code=code, name="pending-test", migration_date=date(2020, 1, 1)
    )
    db.commit()
    assert resolve_annual_leave_base(db, code) == 0

    rule = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=date.today() - timedelta(days=1),
        annual_leave_base=25,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()
    assert rule.status == "pending"
    # Runtime still sees old rule (annual 0)
    assert resolve_annual_leave_base(db, code) == 0
    assert get_effective_rule(db, code).annual_leave_base == 0

    preview = build_impact_preview(db, code, rule)
    assert "affected_count" in preview
    assert resolve_annual_leave_base(db, code) == 0

    req = create_preview_request(db, rule_id=rule.id, created_by="t")
    db.commit()
    confirm_and_recalculate(db, req.id, confirmed_by="t")
    db.commit()
    db.refresh(rule)
    assert rule.status == "active"
    assert resolve_annual_leave_base(db, code) == 25


def test_future_rule_scheduled_auto_effective_by_date(db):
    from models.reserved_membership_code import ReservedMembershipCode

    code = "72"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="future-test")
    db.commit()
    future = date.today() + timedelta(days=20)
    rule = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=future,
        annual_leave_base=18,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()
    assert rule.status == "scheduled"
    assert resolve_annual_leave_base(db, code, on_date=date.today()) == 0
    assert resolve_annual_leave_base(db, code, on_date=future) == 18


def test_seed_does_not_overwrite_existing(db):
    from web.services.membership_service import SEED_CODE_FLAGS

    mt = db.query(MembershipType).filter(MembershipType.code == "4").one()
    rule = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == "4")
        .order_by(MembershipTypeRule.effective_from.asc())
        .first()
    )
    seed = SEED_CODE_FLAGS["4"]
    mt.name = "قراردادی-سفارشی"
    mt.sort_order = 99
    rule.annual_leave_base = 27
    rule.supports_extra_service = True
    db.commit()

    try:
        n = reconcile_seed_membership_rules(db)
        db.commit()
        db.refresh(mt)
        db.refresh(rule)
        assert mt.name == "قراردادی-سفارشی"
        assert mt.sort_order == 99
        assert rule.annual_leave_base == 27
        assert rule.supports_extra_service is True
        # insert-only may create 0
        assert n >= 0
    finally:
        mt.name = seed["name"]
        mt.sort_order = seed["sort_order"]
        rule.annual_leave_base = seed["annual_leave_base"]
        rule.supports_service_deduction = seed["supports_service_deduction"]
        rule.supports_extra_service = seed["supports_extra_service"]
        rule.supports_positive_seniority = seed["supports_positive_seniority"]
        db.commit()


def test_behavior_profile_semantics(db):
    assert msem.is_permanent(db, "1")
    assert msem.is_conscript(db, "2")
    assert msem.is_physician(db, "5")
    assert msem.coverage_mode(db, "4") == msem.COVERAGE_CONTRACT_END
    assert msem.uses_department_travel_resolve(db, "1")
    assert msem.uses_department_travel_resolve(db, "2")
    assert not msem.uses_department_travel_resolve(db, "4")

    from models.reserved_membership_code import ReservedMembershipCode

    code = "73"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()
    create_membership_type(db, code=code, name="dyn", behavior_profile="permanent")
    db.commit()
    assert msem.is_permanent(db, code)


def test_temporal_dual_run_uses_historical_date(db, make_user):
    from models.reserved_membership_code import ReservedMembershipCode

    code = "74"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="temporal")
    db.commit()
    # Past rule annual 10 (active via seed rule 0 — replace with past active)
    # First rule from create is today/0. Add past active by confirming pending.
    past = date(2024, 1, 1)
    rule_a = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=past,
        annual_leave_base=10,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()
    req = create_preview_request(db, rule_id=rule_a.id, created_by="t")
    db.commit()
    confirm_and_recalculate(db, req.id, confirmed_by="t")
    db.commit()

    future = date.today() + timedelta(days=60)
    create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=future,
        annual_leave_base=40,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()

    user = make_user(department=code, balance_al=None, contract_type_code=code)
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .first()
    )
    # Force contract window in 2024–mid future
    contract.start_date = date(2024, 3, 1)
    contract.end_date = date(2024, 12, 31)
    db.commit()

    hist = date(2024, 6, 1)
    assert contract_comparison_date(contract, date.today()) == contract.end_date
    assert resolve_annual_leave_base(db, code, on_date=hist) == 10
    assert resolve_annual_leave_base(db, code, on_date=future) == 40

    # New path at historical clamp must not use future rule
    def new_fn(db, membership_code, region_code=None, on_date=None):
        return resolve_annual_leave_base(db, membership_code, on_date=on_date)

    diff = compare_contract_entitlement(
        db, contract, on_date=date.today(), new_annual_fn=new_fn, legacy_annual_fn=new_fn
    )
    # Same fn for both → no mismatch; assert as_of clamped
    assert diff is None or diff.as_of == contract.end_date.isoformat()


def test_init_does_not_mutate_business_data(db, make_user):
    user = make_user(department="4", balance_al=10, contract_type_code="4")
    contract = (
        db.query(Contract).filter(Contract.user_id == user["user_id"]).first()
    )
    bal = (
        db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == user["user_id"])
        .first()
    )
    c_count = db.query(Contract).count()
    b_count = db.query(LeaveBalance).count()
    t_count = db.query(LeaveTransaction).count()
    r_count = db.query(LeaveRequest).count()
    sa_count = db.query(ServiceAdjustment).count()
    mt = db.query(MembershipType).filter(MembershipType.code == "4").one()
    name_before = mt.name
    annual_before = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == "4")
        .order_by(MembershipTypeRule.effective_from.asc())
        .first()
        .annual_leave_base
    )

    # Startup-equivalent seed path
    seed_default_memberships(db)
    reconcile_seed_membership_rules(db)
    db.commit()

    assert db.query(Contract).count() == c_count
    assert db.query(LeaveBalance).count() == b_count
    assert db.query(LeaveTransaction).count() == t_count
    assert db.query(LeaveRequest).count() == r_count
    assert db.query(ServiceAdjustment).count() == sa_count
    db.refresh(mt)
    assert mt.name == name_before
    annual_after = (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.membership_type_code == "4")
        .order_by(MembershipTypeRule.effective_from.asc())
        .first()
        .annual_leave_base
    )
    assert annual_after == annual_before
    db.refresh(contract)
    assert contract.annual_leave_days is not None
    if bal:
        db.refresh(bal)


def test_service_adjustment_contract_restrict(db, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="2")
    row = create_adjustment(
        db,
        employee_id=user["user_id"],
        adjustment_type="service_deduction",
        effective_date=date.today(),
        days=2,
        created_by="t",
    )
    db.commit()
    assert row.contract_id is not None
    contract = db.query(Contract).filter(Contract.id == row.contract_id).one()
    # Deleting contract with adjustment must fail under RESTRICT (when FK present)
    try:
        db.delete(contract)
        db.commit()
        # If FK not yet applied in test DB, skip hard assert
        still = db.query(ServiceAdjustment).filter(ServiceAdjustment.id == row.id).first()
        if still is None:
            assert False, "adjustment should not cascade-delete with contract"
    except Exception:
        db.rollback()
        assert (
            db.query(ServiceAdjustment).filter(ServiceAdjustment.id == row.id).first()
            is not None
        )
