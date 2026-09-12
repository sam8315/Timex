"""Business-rule normalization for hourly-leave policies."""
from sqlalchemy import event

from models.attendance import HourlyLeavePolicy


def normalize_hourly_leave_policy(policy: HourlyLeavePolicy) -> HourlyLeavePolicy:
    """Apply the invariant between minimum request and time granularity."""
    if policy.min_request_minutes == 1:
        policy.granularity_minutes = 1
    return policy


@event.listens_for(HourlyLeavePolicy, "load")
def _normalize_loaded_hourly_leave_policy(target, context) -> None:
    normalize_hourly_leave_policy(target)


@event.listens_for(HourlyLeavePolicy, "before_insert")
def _normalize_inserted_hourly_leave_policy(mapper, connection, target) -> None:
    normalize_hourly_leave_policy(target)


@event.listens_for(HourlyLeavePolicy, "before_update")
def _normalize_updated_hourly_leave_policy(mapper, connection, target) -> None:
    normalize_hourly_leave_policy(target)
