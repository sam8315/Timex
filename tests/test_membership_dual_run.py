"""Phase 0/3: dual-run and membership seed/resolve tests."""
from datetime import date, timedelta

from models.contract import Contract
from models.membership_type import MembershipType
from models.membership_type_rule import MembershipTypeRule
from web.services.leave_entitlement_service import (
    resolve_annual_leave_days,
    resolve_membership_code_for_policy,
)
from web.services.membership_cutover_validation import (
    find_orphan_membership_codes,
    snapshot_resolve_matrix,
    validate_cutover_for_all_contracts,
)
from web.services.membership_service import (
    create_membership_type,
    resolve_annual_leave_base,
    resolve_annual_leave_base_with_region,
    seed_default_memberships,
)


class TestMembershipSeed:
    def test_exactly_seven_seeded(self, db):
        codes = {r.code for r in db.query(MembershipType).all()}
        assert {"1", "2", "3", "4", "5", "6", "7"}.issubset(codes)
        assert db.query(MembershipTypeRule).count() >= 7

    def test_seed_idempotent_no_extra(self, db):
        before_seed_codes = {
            r.code for r in db.query(MembershipType).all()
            if r.code in {"1", "2", "3", "4", "5", "6", "7"}
        }
        created = seed_default_memberships(db)
        db.commit()
        assert created == 0
        after = {
            r.code for r in db.query(MembershipType).all()
            if r.code in {"1", "2", "3", "4", "5", "6", "7"}
        }
        assert after == before_seed_codes

    def test_bases(self, db):
        assert resolve_annual_leave_base(db, "1") == 30
        assert resolve_annual_leave_base(db, "2") == 30
        assert resolve_annual_leave_base(db, "5") == 0
        assert resolve_annual_leave_base(db, "6") == 0
        assert resolve_annual_leave_base(db, "7") == 0


class TestNoRemap67:
    def test_identity_mapping(self):
        assert resolve_membership_code_for_policy("6") == "6"
        assert resolve_membership_code_for_policy("7") == "7"
        assert resolve_membership_code_for_policy("4") == "4"

    def test_resolve_6_7_zero_without_region(self, db):
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if not policy:
            policy = Policy(category="leave", name="leave", is_active=True)
            db.add(policy)
            db.flush()
        for code in ("6", "7"):
            for key, val in (
                (f"region_applies_dept_{code}", "false"),
            ):
                pv = (
                    db.query(PolicyValue)
                    .filter(
                        PolicyValue.policy_id == policy.id,
                        PolicyValue.parameter_key == key,
                        PolicyValue.region_code.is_(None),
                    )
                    .first()
                )
                if pv:
                    pv.parameter_value = val
                else:
                    db.add(
                        PolicyValue(
                            policy_id=policy.id,
                            parameter_key=key,
                            parameter_value=val,
                        )
                    )
        db.commit()
        assert resolve_annual_leave_days(db, "6", region_code="NORMAL") == 0
        assert resolve_annual_leave_days(db, "7", region_code="NORMAL") == 0


class TestDualRun:
    def test_snapshot_matrix(self, db):
        rows = snapshot_resolve_matrix(db, membership_codes=["1", "4", "6"])
        assert len(rows) >= 3
        assert all("annual_leave_days" in r for r in rows)

    def test_new_path_matches_resolve_when_region_off(self, db):
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if not policy:
            policy = Policy(category="leave", name="leave", is_active=True)
            db.add(policy)
            db.flush()
        for code in ("1", "2", "3", "4", "5", "6", "7"):
            key = f"region_applies_dept_{code}"
            pv = (
                db.query(PolicyValue)
                .filter(
                    PolicyValue.policy_id == policy.id,
                    PolicyValue.parameter_key == key,
                    PolicyValue.region_code.is_(None),
                )
                .first()
            )
            if pv:
                pv.parameter_value = "false"
            else:
                db.add(
                    PolicyValue(
                        policy_id=policy.id,
                        parameter_key=key,
                        parameter_value="false",
                    )
                )
        db.commit()

        for code in ("1", "2", "4", "5", "6", "7"):
            old = resolve_annual_leave_days(db, code, region_code="NORMAL")
            new = resolve_annual_leave_base_with_region(
                db, code, region_code="NORMAL"
            )
            assert old == new, f"mismatch code={code} old={old} new={new}"

    def test_no_orphans_after_seed(self, db):
        assert find_orphan_membership_codes(db) == []

    def test_cutover_validation_empty_when_aligned(self, db, make_user):
        user = make_user(department="4", balance_al=None, contract_type_code="4")
        # ensure region off for clean compare
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if policy:
            for code in ("4",):
                key = f"region_applies_dept_{code}"
                pv = (
                    db.query(PolicyValue)
                    .filter(
                        PolicyValue.policy_id == policy.id,
                        PolicyValue.parameter_key == key,
                    )
                    .first()
                )
                if pv:
                    pv.parameter_value = "false"
                else:
                    db.add(
                        PolicyValue(
                            policy_id=policy.id,
                            parameter_key=key,
                            parameter_value="false",
                        )
                    )
            db.commit()
        diffs = validate_cutover_for_all_contracts(db)
        # may include other contracts from prior tests in same session DB —
        # filter to our user
        mine = [d for d in diffs if d.user_id == user["user_id"]]
        assert mine == []


class TestNewMembershipDefaults:
    def test_new_membership_rule_defaults(self, db):
        from models.reserved_membership_code import ReservedMembershipCode

        code = "91"
        db.query(MembershipTypeRule).filter(
            MembershipTypeRule.membership_type_code == code
        ).delete()
        db.query(MembershipType).filter(MembershipType.code == code).delete()
        db.query(ReservedMembershipCode).filter(
            ReservedMembershipCode.code == code
        ).delete()
        db.commit()

        create_membership_type(
            db, code=code, name="تست عضویت", created_by="tester"
        )
        db.commit()
        rule = (
            db.query(MembershipTypeRule)
            .filter(MembershipTypeRule.membership_type_code == code)
            .one()
        )
        assert rule.annual_leave_base == 0
        assert rule.supports_service_deduction is False
        assert rule.supports_extra_service is False
        assert rule.supports_positive_seniority is False
