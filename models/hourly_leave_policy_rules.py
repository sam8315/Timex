"""Business-rule normalization for hourly-leave policies."""
from sqlalchemy import event

from models.attendance import HourlyLeavePolicy


def normalize_hourly_leave_policy(policy: HourlyLeavePolicy) -> HourlyLeavePolicy:
    """Apply the invariant between minimum request and time granularity.

    A one-minute minimum request means the policy must operate at one-minute
    granularity so requests such as 07:01 → 07:02 are valid.
    """
    if policy.min_request_minutes == 1:
        policy.granularity_minutes = 1
    return policy


@event.listens_for(HourlyLeavePolicy, "load")
def _normalize_loaded_hourly_leave_policy(
    target: HourlyLeavePolicy,
    context,
) -> None:
    normalize_hourly_leave_policy(target)
