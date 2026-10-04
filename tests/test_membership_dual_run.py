"""Phase A/B/D: dual-run, non-destructive align, seed reconcile tests."""
from datetime import date

from models.contract import Contract
from models.membership_type import MembershipType
from models.membership_type_rule import MembershipTypeRule
from web.services.leave_entitlement_service import (
    resolve_annual_leave_days,
    resolve_annual_leave_days_legacy,
    resolve_membership_code_for_policy,
)
from web.services.membership_cutover_validation import (
    compare_annual_paths,
    find_orphan_membership_codes,
    snapshot_resolve_matrix,
    validate_cutover_for_all_contracts,
)
from web.services.membership_service import (
    create_membership_type,
    get_effective_rule,
    reconcile_seed_membership_rules,
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

    def test_reconcile_seed_does_not_overwrite_flags(self, db):
        from web.services.membership_service import SEED_CODE_FLAGS

        rule = (
            db.query(MembershipTypeRule)
            .filter(MembershipTypeRule.membership_type_code == "1")
            .order_by(MembershipTypeRule.effective_from.asc())
            .first()
        )
        assert rule is not None
        seed = SEED_CODE_FLAGS["1"]
        rule.supports_positive_seniority = False
        rule.supports_extra_service = True
        rule.annual_leave_base = 22
        db.commit()
        try:
            reconcile_seed_membership_rules(db)
            db.commit()
            db.refresh(rule)
            # Insert-only: drifted values must remain
            assert rule.supports_positive_seniority is False
            assert rule.supports_extra_service is True
            assert rule.annual_leave_base == 22
        finally:
            rule.annual_leave_base = seed["annual_leave_base"]
            rule.supports_service_deduction = seed["supports_service_deduction"]
            rule.supports_extra_service = seed["supports_extra_service"]
            rule.supports_positive_seniority = seed["supports_positive_seniority"]
            db.commit()


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


class TestDualRunGateAfterCutover:
    def test_dual_run_warns_not_raises_when_fk_exists(self, db, monkeypatch):
        """After contracts FK exists, mismatches must not abort create_tables."""
        from database import init_db

        monkeypatch.setattr(
            init_db, "_membership_contracts_fk_exists", lambda bind_engine=None: True
        )

        def fake_validate(db, **kwargs):
            from web.services.membership_cutover_validation import EntitlementDiff

            return [
                EntitlementDiff(
                    contract_id=46,
                    user_id="u1",
                    contract_type_code="5",
                    region_code=None,
                    old_annual=30,
                    new_annual=0,
                    old_entitlement={},
                    new_entitlement={},
                    reason="entitlement mismatch contract_id=46 code=5 old_annual=30 new_annual=0",
                )
            ]

        monkeypatch.setattr(
            "web.services.membership_cutover_validation.validate_cutover_for_all_contracts",
            fake_validate,
        )
        monkeypatch.setattr(
            "web.services.membership_cutover_validation.find_orphan_membership_codes",
            lambda db: [],
        )
        # Must not raise
        init_db.run_membership_dual_run_validation(bind_engine=db.get_bind())


class TestAlignNonDestructive:
    def test_existing_annual_leave_dept_6_preserved(self, db):
        from database.init_db import align_leave_policy_membership_67
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if not policy:
            policy = Policy(category="leave", name="leave", is_active=True)
            db.add(policy)
            db.flush()
        key = "annual_leave_dept_6"
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
            pv.parameter_value = "5"
        else:
            db.add(
                PolicyValue(
                    policy_id=policy.id,
                    parameter_key=key,
                    parameter_value="5",
                    is_editable=True,
                )
            )
        db.commit()

        align_leave_policy_membership_67(bind_engine=db.get_bind())
        db.expire_all()
        pv2 = (
            db.query(PolicyValue)
            .filter(
                PolicyValue.policy_id == policy.id,
                PolicyValue.parameter_key == key,
                PolicyValue.region_code.is_(None),
            )
            .one()
        )
        assert pv2.parameter_value == "5"


class TestDualRun:
    def test_snapshot_matrix(self, db):
        rows = snapshot_resolve_matrix(db, membership_codes=["1", "4", "6"])
        assert len(rows) >= 3
        assert all("annual_leave_days" in r for r in rows)
        assert all("legacy_annual_leave_days" in r for r in rows)

    def test_legacy_independent_of_new_mock(self, db):
        """Legacy must stay policy-based even if New resolver is mocked."""
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if not policy:
            policy = Policy(category="leave", name="leave", is_active=True)
            db.add(policy)
            db.flush()
        for key, val in (
            ("annual_leave_dept_4", "30"),
            ("region_applies_dept_4", "false"),
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

        legacy = resolve_annual_leave_days_legacy(db, "4", region_code="NORMAL")
        assert legacy == 30

        def fake_new(db, code, region_code=None, on_date=None):
            return 999

        diff = compare_annual_paths(
            db, "4", "NORMAL", new_fn=fake_new
        )
        assert diff is not None
        assert diff.old_annual == 30
        assert diff.new_annual == 999

    def test_mismatch_detected_when_new_differs(self, db, make_user):
        user = make_user(department="4", balance_al=None, contract_type_code="4")
        from models.policy import Policy, PolicyValue

        policy = db.query(Policy).filter(Policy.category == "leave").first()
        if policy:
            key = "region_applies_dept_4"
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

        def fake_new(db, code, region_code=None, on_date=None):
            return 1

        diffs = validate_cutover_for_all_contracts(db, new_annual_fn=fake_new)
        mine = [d for d in diffs if d.user_id == user["user_id"]]
        assert mine
        assert mine[0].new_annual == 1

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
            # Ensure legacy annual matches seed base
            key = "annual_leave_dept_4"
            pv = (
                db.query(PolicyValue)
                .filter(
                    PolicyValue.policy_id == policy.id,
                    PolicyValue.parameter_key == key,
                )
                .first()
            )
            if pv:
                pv.parameter_value = "30"
            else:
                db.add(
                    PolicyValue(
                        policy_id=policy.id,
                        parameter_key=key,
                        parameter_value="30",
                    )
                )
            db.commit()
        diffs = validate_cutover_for_all_contracts(db)
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


class TestEffectiveRuleByDate:
    def test_future_rule_effective_on_its_date(self, db):
        from datetime import timedelta

        from models.reserved_membership_code import ReservedMembershipCode
        from web.services.membership_service import create_rule_snapshot

        code = "92"
        db.query(MembershipTypeRule).filter(
            MembershipTypeRule.membership_type_code == code
        ).delete()
        db.query(MembershipType).filter(MembershipType.code == code).delete()
        db.query(ReservedMembershipCode).filter(
            ReservedMembershipCode.code == code
        ).delete()
        db.commit()

        create_membership_type(db, code=code, name="تاریخ", created_by="t")
        db.commit()
        # first rule annual=0
        future = date.today() + timedelta(days=30)
        create_rule_snapshot(
            db,
            membership_type_code=code,
            effective_from=future,
            annual_leave_base=22,
            supports_service_deduction=False,
            supports_extra_service=False,
            supports_positive_seniority=False,
            created_by="t",
        )
        db.commit()

        today_rule = get_effective_rule(db, code, on_date=date.today())
        assert today_rule is not None
        assert today_rule.annual_leave_base == 0

        future_rule = get_effective_rule(db, code, on_date=future)
        assert future_rule is not None
        assert future_rule.annual_leave_base == 22

        # status scheduled must not block resolve on that date
        assert future_rule.status in ("scheduled", "active")
