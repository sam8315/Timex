"""
کدهای عضویت مصرف‌شده که دیگر قابل استفاده نیستند.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ReservedMembershipCode(Base):
    """کدهایی که hard-delete شده‌اند و نباید دوباره ساخته شوند."""

    __tablename__ = "reserved_membership_codes"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reserved_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:
        return f"<ReservedMembershipCode(code='{self.code}')>"
