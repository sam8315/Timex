"""
Membership Change Settlement — architecture only for owner-dependent rules.

Current Behavior: each membership/contract owns its own period; remainders are
not auto-merged (KEEP_SEPARATE). Other modes are configurable via PolicyValue
but must not invent legal transfer/cash-out amounts.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from web.services.leave_entitlement_service import _get_leave_policy, _get_policy_param


class MembershipChangeMode(str, Enum):
    KEEP_SEPARATE = 'keep_separate'  # Current Behavior
    TRANSFER = 'transfer'  # owner-dependent; not auto-applied
    EXPIRE = 'expire'
    CASH_OUT = 'cash_out'


MEMBERSHIP_CHANGE_MODES = frozenset(m.value for m in MembershipChangeMode)

_POLICY_KEY = 'membership_change_settlement_mode'


def resolve_membership_change_mode(
    db: Session,
    membership_code: Optional[str] = None,
) -> MembershipChangeMode:
    """
    Read configurable mode; default KEEP_SEPARATE (Current Behavior).

    Does not execute settlement — callers must implement ledger effects only
    after an explicit owner-approved Policy value is set.
    """
    policy = _get_leave_policy(db)
    if policy is None:
        return MembershipChangeMode.KEEP_SEPARATE
    row = _get_policy_param(db, policy.id, _POLICY_KEY, region_code=None)
    raw = (row.parameter_value if row else None) or MembershipChangeMode.KEEP_SEPARATE.value
    text = str(raw).strip().lower()
    if text not in MEMBERSHIP_CHANGE_MODES:
        return MembershipChangeMode.KEEP_SEPARATE
    return MembershipChangeMode(text)
