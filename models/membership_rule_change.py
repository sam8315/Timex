"""
درخواست و audit برای Ruleهای گذشته‌نگر (retroactive) عضویت.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class MembershipRuleChangeRequest(TimestampMixin, Base):
    __tablename__ = "membership_rule_change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    membership_type_code: Mapped[str] = mapped_column(
        String(6),
        ForeignKey("membership_types.code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("membership_type_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    # draft | previewed | confirmed | applied | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    preview_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MembershipRuleChangeAudit(Base):
    __tablename__ = "membership_rule_change_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("membership_rule_change_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
