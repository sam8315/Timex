"""سابقه تغییر درخواست مرخصی؛ ردیف درخواست پاک نمی‌شود."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class LeaveRequestAudit(Base):
    __tablename__ = "leave_request_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leave_request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
