"""Buyback settlement facade (Current Behavior buyback caps)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from web.services.leave_entitlement_service import resolve_max_buyback


def resolve_buyback_cap(
    db: Session,
    membership_code: str,
    *,
    region_code: Optional[str] = None,
    year_j: Optional[int] = None,
) -> Optional[int]:
    """Buyback cap. None = unlimited. Delegates to resolve_max_buyback."""
    return resolve_max_buyback(
        db, membership_code, region_code=region_code, year_j=year_j
    )
