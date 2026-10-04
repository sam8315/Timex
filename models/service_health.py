"""
Current known status of Timex Windows Services (web / adms / bale).

One row per service — last-known snapshot only (no event history).
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


SERVICE_NAMES = ("web", "adms", "bale")
PROCESS_STATES = ("unknown", "running", "stopped")
HEALTH_STATES = ("unknown", "healthy", "degraded", "offline", "failed")


class ServiceHealth(TimestampMixin, Base):
    """Last-known process/health snapshot for a single Timex service."""

    __tablename__ = "service_health"

    service_name: Mapped[str] = mapped_column(String(20), primary_key=True)

    process_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    health_state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_error_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Opaque JSON text blob for later phases (no structured metric schema here).
    metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "service_name IN ('web', 'adms', 'bale')",
            name="ck_service_health_service_name",
        ),
        CheckConstraint(
            "process_state IN ('unknown', 'running', 'stopped')",
            name="ck_service_health_process_state",
        ),
        CheckConstraint(
            "health_state IN ('unknown', 'healthy', 'degraded', 'offline', 'failed')",
            name="ck_service_health_health_state",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ServiceHealth(service_name={self.service_name!r}, "
            f"process_state={self.process_state!r}, "
            f"health_state={self.health_state!r})>"
        )
