"""
Annual Leave policy authority — single source of truth for LIVE annual base.

Authoritative (live):
  MembershipTypeRule.annual_leave_base
  → region_applies_dept_{code} (PolicyValue flag)
  → Region / scoped annual_leave_days override when applies
  via resolve_annual_leave_base_with_region / resolve_annual_leave_days

Compatibility mirror (non-authoritative when Rules exist):
  PolicyValue annual_leave_dept_{code}
  Kept aligned FROM the Rule base so dual-run / legacy helpers do not
  invent a second live amount.

Charge / mutation Current Behavior:
  Contract.annual_leave_days snapshot (not rewritten by mirror sync).

Physician (code 5):
  Repository seed + Target Spec mismatch #11 use static base 0 and
  Policy-driven ownership via Membership Rules — no invented legal 30.
  Historical contract snapshots may still be 30; that is snapshot drift,
  not a second live policy source.

Engine promotion is blocked while any Rule↔mirror base conflict remains.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from models.leave_glossary import MEMBERSHIP_PHYSICIAN, POLICY_MEMBERSHIP_CODES
from models.membership_type_rule import MembershipTypeRule
from models.policy import Policy, PolicyValue

logger = logging.getLogger(__name__)

PHYSICIAN_CODE = MEMBERSHIP_PHYSICIAN  # '5'
MIRROR_KEY_TMPL = 'annual_leave_dept_{code}'
MIRROR_NOTES_PREFIX = 'compat mirror of MembershipTypeRule.annual_leave_base'


@dataclass(frozen=True)
class AnnualPolicyConflict:
    """Explicit, auditable Rule vs compatibility-mirror divergence."""

    membership_code: str
    rule_base: int
    mirror_annual: Optional[int]
    kind: str  # missing_mirror | mirror_drift
    detail: str


@dataclass(frozen=True)
class MirrorSyncChange:
    membership_code: str
    old_mirror: Optional[str]
    new_mirror: str
    rule_base: int


def _leave_policy(db: Session) -> Optional[Policy]:
    return db.query(Policy).filter(Policy.category == 'leave').first()


def _get_mirror_pv(
    db: Session, policy_id: int, membership_code: str
) -> Optional[PolicyValue]:
    return (
        db.query(PolicyValue)
        .filter(
            PolicyValue.policy_id == policy_id,
            PolicyValue.parameter_key == MIRROR_KEY_TMPL.format(
                code=membership_code
            ),
            PolicyValue.region_code.is_(None),
        )
        .first()
    )


def _parse_mirror_int(raw: Optional[str]) -> Optional[int]:
    if raw is None or str(raw).strip() == '':
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def effective_rule_base(
    db: Session,
    membership_code: str,
    *,
    on_date: Optional[date] = None,
) -> Optional[int]:
    """Authoritative live base from MembershipTypeRule, or None if no rule."""
    from web.services.membership_service import get_effective_rule

    rule = get_effective_rule(db, membership_code, on_date=on_date)
    if rule is None:
        return None
    return max(0, int(rule.annual_leave_base))


def audit_annual_policy_conflicts(
    db: Session,
    *,
    membership_codes: Optional[Sequence[str]] = None,
    on_date: Optional[date] = None,
) -> List[AnnualPolicyConflict]:
    """
    Detect Rule base vs PolicyValue annual_leave_dept_* mirror drift.

    Does not compare contract snapshots (historical charge snapshots are
    allowed to differ from live Rule — Current Behavior mismatch #16).
    """
    codes = list(membership_codes) if membership_codes else sorted(
        POLICY_MEMBERSHIP_CODES
    )
    policy = _leave_policy(db)
    conflicts: List[AnnualPolicyConflict] = []
    for code in codes:
        base = effective_rule_base(db, code, on_date=on_date)
        if base is None:
            continue  # no Rule yet → legacy PolicyValue remains temporary SoT
        if policy is None:
            conflicts.append(
                AnnualPolicyConflict(
                    membership_code=str(code),
                    rule_base=base,
                    mirror_annual=None,
                    kind='missing_mirror',
                    detail='leave policy missing; cannot host compatibility mirror',
                )
            )
            continue
        pv = _get_mirror_pv(db, policy.id, str(code))
        mirror = _parse_mirror_int(
            pv.parameter_value if pv is not None else None
        )
        if pv is None or mirror is None:
            conflicts.append(
                AnnualPolicyConflict(
                    membership_code=str(code),
                    rule_base=base,
                    mirror_annual=mirror,
                    kind='missing_mirror',
                    detail=(
                        f'{MIRROR_KEY_TMPL.format(code=code)} missing or '
                        f'unparseable; Rule base={base}'
                    ),
                )
            )
            continue
        if mirror != base:
            conflicts.append(
                AnnualPolicyConflict(
                    membership_code=str(code),
                    rule_base=base,
                    mirror_annual=mirror,
                    kind='mirror_drift',
                    detail=(
                        f'Rule base={base} vs '
                        f'{MIRROR_KEY_TMPL.format(code=code)}={mirror}'
                    ),
                )
            )
    return conflicts


def sync_compat_policy_mirrors_from_rules(
    db: Session,
    *,
    membership_codes: Optional[Sequence[str]] = None,
    on_date: Optional[date] = None,
    dry_run: bool = False,
) -> List[MirrorSyncChange]:
    """
    One-way sync: MembershipTypeRule.annual_leave_base → PolicyValue mirror.

    Never touches Contract.annual_leave_days or LeaveBalance.
    Reversible by restoring prior mirror values from returned changes /
    migration reverse SQL.
    """
    codes = list(membership_codes) if membership_codes else sorted(
        POLICY_MEMBERSHIP_CODES
    )
    policy = _leave_policy(db)
    if policy is None:
        return []

    changes: List[MirrorSyncChange] = []
    for code in codes:
        base = effective_rule_base(db, code, on_date=on_date)
        if base is None:
            continue
        key = MIRROR_KEY_TMPL.format(code=code)
        pv = _get_mirror_pv(db, policy.id, str(code))
        new_val = str(int(base))
        old_val = pv.parameter_value if pv is not None else None
        if old_val is not None and str(old_val).strip() == new_val:
            continue
        changes.append(
            MirrorSyncChange(
                membership_code=str(code),
                old_mirror=None if old_val is None else str(old_val),
                new_mirror=new_val,
                rule_base=int(base),
            )
        )
        if dry_run:
            continue
        notes = f'{MIRROR_NOTES_PREFIX} code={code}'
        if pv is None:
            db.add(
                PolicyValue(
                    policy_id=policy.id,
                    parameter_key=key,
                    parameter_value=new_val,
                    region_code=None,
                    notes=notes,
                    is_editable=True,
                )
            )
        else:
            pv.parameter_value = new_val
            pv.notes = notes
    if not dry_run and changes:
        db.flush()
        logger.info(
            'al_policy_mirror_sync codes=%s changes=%s',
            ','.join(c.membership_code for c in changes),
            len(changes),
        )
    return changes


def physician_live_annual_base(
    db: Session, *, on_date: Optional[date] = None
) -> int:
    """Authoritative physician live base (Membership Rule; seed default 0)."""
    base = effective_rule_base(db, PHYSICIAN_CODE, on_date=on_date)
    return 0 if base is None else base


def engine_promotion_blockers(
    db: Session,
    *,
    on_date: Optional[date] = None,
) -> List[str]:
    """
    Reasons engine promotion must stay blocked.

    Empty list ⇒ Rule↔mirror conflicts cleared (AL charge parity still
    enforced separately by cutover fail-closed).
    """
    blockers: List[str] = []
    for c in audit_annual_policy_conflicts(db, on_date=on_date):
        blockers.append(
            f'annual_policy_conflict code={c.membership_code} '
            f'kind={c.kind} {c.detail}'
        )
    return blockers


def is_engine_promotion_allowed(
    db: Session, *, on_date: Optional[date] = None
) -> bool:
    return not engine_promotion_blockers(db, on_date=on_date)


def count_active_rules(db: Session, membership_code: str) -> int:
    return (
        db.query(MembershipTypeRule)
        .filter(
            MembershipTypeRule.membership_type_code == str(membership_code),
            MembershipTypeRule.status == 'active',
        )
        .count()
    )
