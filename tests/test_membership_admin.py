"""Admin UI + permissions + service adjustments for membership types."""
from datetime import date, timedelta

from web.permissions import ALL_PERMISSIONS
from web.services.membership_service import (
    MembershipError,
    activate_membership,
    count_business_dependencies,
    create_membership_type,
    create_rule_snapshot,
    deactivate_membership,
    delete_membership,
    delete_scheduled_rule,
    get_effective_rule,
    membership_types_as_dict,
    update_scheduled_rule,
)
from web.services.service_adjustment_service import (
    ServiceAdjustmentError,
    correct_adjustment,
    create_adjustment,
    void_adjustment,
)
from .conftest import login_as

HTML_ACCEPT = {"Accept": "text/html"}


def test_permissions_catalog_super_only():
    for code in (
        "manage_membership_types",
        "manage_membership_rules",
        "manage_service_adjustments",
    ):
        assert code in ALL_PERMISSIONS
        assert ALL_PERMISSIONS[code]["admin"] is False
        assert ALL_PERMISSIONS[code]["super_admin"] is True


def test_membership_types_page_requires_perm(client, db, make_user):
    admin = make_user(role="admin")
    login_as(client, admin["national_code"])
    resp = client.get("/admin/membership-types?show_all=1", headers=HTML_ACCEPT)
    # admin without grant should be blocked (403/redirect)
    assert resp.status_code in (302, 403)


def test_membership_types_page_super(client, db, make_user):
    super_u = make_user(role="super_admin")
    login_as(client, super_u["national_code"])
    resp = client.get("/admin/membership-types?show_all=1", headers=HTML_ACCEPT)
    assert resp.status_code == 200
    body = resp.text
    assert "رسمی" in body
    assert "انواع عضویت" in body


def test_hard_delete_unused_and_reserve(db):
    from models.membership_type import MembershipType
    from models.membership_type_rule import MembershipTypeRule
    from models.reserved_membership_code import ReservedMembershipCode

    code = "88"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="موقت")
    db.commit()
    delete_membership(db, code, reserved_by="tester")
    db.commit()
    try:
        create_membership_type(db, code=code, name="دوباره")
        assert False, "should not reuse reserved code"
    except MembershipError:
        pass


def test_rule_snapshot_and_effective(db):
    from models.membership_type import MembershipType
    from models.membership_type_rule import MembershipTypeRule
    from models.reserved_membership_code import ReservedMembershipCode

    code = "77"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="تست قاعده")
    db.commit()
    create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=date(2020, 1, 1),
        annual_leave_base=12,
        supports_service_deduction=False,
        supports_extra_service=True,
        supports_positive_seniority=False,
        created_by="tester",
    )
    db.commit()
    rule = get_effective_rule(db, code, on_date=date(2021, 1, 1))
    assert rule is not None
    assert rule.annual_leave_base == 12
    assert rule.supports_extra_service is True


def test_service_adjustment_gate_and_correction(db, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="2")
    # type 2 supports service_deduction
    row = create_adjustment(
        db,
        employee_id=user["user_id"],
        adjustment_type="service_deduction",
        effective_date=date.today(),
        days=10,
        created_by="tester",
    )
    db.commit()
    assert row.status == "active"

    # After seed reconcile: type 2 supports extra_service; type 1 does not
    extra = create_adjustment(
        db,
        employee_id=user["user_id"],
        adjustment_type="extra_service",
        effective_date=date.today(),
        days=1,
        created_by="tester",
    )
    db.commit()
    assert extra.status == "active"
    void_adjustment(db, extra.id)
    db.commit()

    try:
        create_adjustment(
            db,
            employee_id=user["user_id"],
            adjustment_type="positive_seniority",
            effective_date=date.today(),
            days=1,
            created_by="tester",
        )
        assert False, "positive_seniority should be gated off for type 2 seed"
    except ServiceAdjustmentError:
        db.rollback()

    corr = correct_adjustment(
        db, original_id=row.id, years=0, months=0, days=5, created_by="tester"
    )
    db.commit()
    assert corr.corrects_adjustment_id == row.id
    assert corr.days == 5
    db.refresh(row)
    assert row.status == "corrected"

    active2 = create_adjustment(
        db,
        employee_id=user["user_id"],
        adjustment_type="service_deduction",
        effective_date=date.today(),
        days=3,
        created_by="tester",
    )
    db.commit()
    void_adjustment(db, active2.id)
    db.commit()
    db.refresh(active2)
    assert active2.status == "void"


def test_future_rule_edit_delete_past_immutable(db):
    from models.membership_type import MembershipType
    from models.membership_type_rule import MembershipTypeRule
    from models.reserved_membership_code import ReservedMembershipCode

    code = "76"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="lifecycle")
    db.commit()
    past = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=date(2019, 1, 1),
        annual_leave_base=10,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    future = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=date.today() + timedelta(days=40),
        annual_leave_base=18,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()

    try:
        update_scheduled_rule(
            db,
            past.id,
            annual_leave_base=11,
            supports_service_deduction=False,
            supports_extra_service=False,
            supports_positive_seniority=False,
        )
        assert False, "past rule must be immutable"
    except MembershipError:
        db.rollback()

    update_scheduled_rule(
        db,
        future.id,
        annual_leave_base=19,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()
    db.refresh(future)
    assert future.annual_leave_base == 19
    delete_scheduled_rule(db, future.id)
    db.commit()
    assert (
        db.query(MembershipTypeRule)
        .filter(MembershipTypeRule.id == future.id)
        .first()
        is None
    )


def test_inactive_hidden_from_active_dict_and_reactivate(db):
    from models.membership_type import MembershipType
    from models.membership_type_rule import MembershipTypeRule
    from models.reserved_membership_code import ReservedMembershipCode

    code = "75"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="غیرفعال‌شدنی")
    db.commit()
    deactivate_membership(db, code)
    db.commit()
    assert code not in membership_types_as_dict(db, active_only=True)
    assert code in membership_types_as_dict(db, active_only=False)
    activate_membership(db, code)
    db.commit()
    assert code in membership_types_as_dict(db, active_only=True)


def test_business_deps_include_contracts(db, make_user):
    user = make_user(department="4", balance_al=None, contract_type_code="4")
    deps = count_business_dependencies(db, "4")
    assert deps["contracts"] >= 1
    assert "employees" in deps
    assert "service_adjustments" in deps
    assert "membership_rule_change_requests" in deps
    _ = user


def test_service_adjustment_requires_covering_contract(db, make_user):
    user = make_user(role="user", balance_al=None, contract_type_code="2")
    from models.contract import Contract

    # End the covering contract so effective_date has no coverage
    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .order_by(Contract.start_date.desc())
        .first()
    )
    assert contract is not None
    contract.end_date = date.today() - timedelta(days=10)
    db.commit()

    try:
        create_adjustment(
            db,
            employee_id=user["user_id"],
            adjustment_type="service_deduction",
            effective_date=date.today(),
            days=2,
            created_by="tester",
        )
        assert False, "must fail without covering contract"
    except ServiceAdjustmentError:
        db.rollback()


def test_retroactive_preview_no_leave_mutation(db, make_user):
    from models.membership_type import MembershipType
    from models.membership_type_rule import MembershipTypeRule
    from models.reserved_membership_code import ReservedMembershipCode
    from web.services.membership_retroactive_service import (
        build_impact_preview,
        create_preview_request,
    )

    code = "74"
    db.query(MembershipTypeRule).filter(
        MembershipTypeRule.membership_type_code == code
    ).delete()
    db.query(MembershipType).filter(MembershipType.code == code).delete()
    db.query(ReservedMembershipCode).filter(
        ReservedMembershipCode.code == code
    ).delete()
    db.commit()

    create_membership_type(db, code=code, name="retro")
    db.commit()
    user = make_user(department=code, balance_al=None, contract_type_code=code)
    from models.contract import Contract

    contract = (
        db.query(Contract)
        .filter(Contract.user_id == user["user_id"])
        .first()
    )
    old_annual = contract.annual_leave_days
    rule = create_rule_snapshot(
        db,
        membership_type_code=code,
        effective_from=date.today() - timedelta(days=1),
        annual_leave_base=21,
        supports_service_deduction=False,
        supports_extra_service=False,
        supports_positive_seniority=False,
    )
    db.commit()
    preview = build_impact_preview(db, code, rule)
    assert "affected_count" in preview
    db.refresh(contract)
    assert contract.annual_leave_days == old_annual

    req = create_preview_request(db, rule_id=rule.id, created_by="tester")
    db.commit()
    assert req.status == "previewed"
    db.refresh(contract)
    assert contract.annual_leave_days == old_annual
