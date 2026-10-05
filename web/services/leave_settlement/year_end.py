"""Year-end storage settlement facade (Current Behavior CF caps)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from web.services.leave_entitlement_service import resolve_max_carry_forward


def resolve_storage_cap(
    db: Session,
    membership_code: str,
    *,
    region_code: Optional[str] = None,
    year_j: Optional[int] = None,
) -> Optional[int]:
    """
    Storage ceiling for year-end carry. None = unlimited (Current Behavior).

    ``region_code`` / ``year_j`` reserved for future Policy; Current Behavior
    CF resolution is membership-keyed only.
    """
    del region_code, year_j  # API stability; unused today
    return resolve_max_carry_forward(db, membership_code)
