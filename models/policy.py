"""Configurable global policies and their audit trail."""
from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Policy(TimestampMixin, Base):
    """Main policy container."""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="leave / attendance / overtime / absence"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from_year: Mapped[Optional[int]] = mapped_column(Integer)
    effective_to_year: Mapped[Optional[int]] = mapped_column(Integer)


class PolicyValue(TimestampMixin, Base):
    """Policy parameter values, optionally scoped to a service region."""

    __tablename__ = "policy_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[int] = mapped_column(Integer, nullable=False)
    region_code: Mapped[Optional[str]] = mapped_column(String(20))
    parameter_key: Mapped[str] = mapped_column(String(100), nullable=False)
    parameter_value: Mapped[str] = mapped_column(String(500), nullable=False)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class PolicyAuditLog(TimestampMixin, Base):
    """Audit log for policy-related changes."""

    __tablename__ = "policy_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    changed_by: Mapped[Optional[str]] = mapped_column(String(50))
    reason: Mapped[Optional[str]] = mapped_column(Text)
