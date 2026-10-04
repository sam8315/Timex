"""Admin UI + permissions + service adjustments for membership types."""
from datetime import date

from web.permissions import ALL_PERMISSIONS
from web.services.membership_service import (
    MembershipError,
    create_membership_type,
    create_rule_snapshot,
    delete_membership,
    get_effective_rule,
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

    try:
        create_adjustment(
            db,
            employee_id=user["user_id"],
            adjustment_type="extra_service",
            effective_date=date.today(),
            days=1,
            created_by="tester",
        )
        assert False, "extra_service should be gated off for type 2 seed"
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
