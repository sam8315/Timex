"""Buyback settlement facade (dated periods + Current Behavior buyback caps)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session


def resolve_buyback_cap(
    db: Session,
    membership_code: str,
    *,
    region_code: Optional[str] = None,
    year_j: Optional[int] = None,
    user_id: Optional[str] = None,
    as_of_date: Optional[date] = None,
) -> Optional[int]:
    """Buyback cap. None = unlimited."""
    from web.services.leave_settlement.caps import resolve_settlement_caps

    caps = resolve_settlement_caps(
        db,
        membership_code,
        region_code=region_code,
        user_id=user_id,
        year_j=year_j,
        as_of_date=as_of_date,
    )
    return caps.get("buyback_cap")
