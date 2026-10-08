"""درخواست ثبت تردد فراموش‌شده."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


STATUS_CODES = {
    "P": "در انتظار",
    "A": "تأیید شده",
    "R": "رد شده",
    "C": "لغو شده",
}

REASON_OPTIONS = (
    ("forgot_punch", "فراموشی کارت‌زنی"),
    ("device_fault", "مشکل دستگاه"),
    ("offsite_mission", "مأموریت خارج از محل"),
    ("other", "سایر"),
)
REASON_LABELS = dict(REASON_OPTIONS)

PUNCH_LABELS = {
    0: "ورود",
    1: "خروج",
}


class MissedAttendanceRequest(TimestampMixin, Base):
    """درخواست کاربر برای ثبت یک تردد که فراموش شده است."""

    __tablename__ = "missed_attendance_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    punch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    punch: Mapped[int] = mapped_column(Integer, nullable=False)

    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(1), default="P", nullable=False, index=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    attendance_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("attendances.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = relationship("User", backref="missed_attendance_requests")

    def __repr__(self) -> str:
        return (
            f"<MissedAttendanceRequest(user_id='{self.user_id}', "
            f"status='{self.status}')>"
        )

    @property
    def status_name(self) -> str:
        return STATUS_CODES.get(self.status, "نامشخص")

    @property
    def reason_label(self) -> str:
        label = REASON_LABELS.get(self.reason_code, self.reason_code)
        if self.reason_code == "other" and self.reason_text:
            return f"{label}: {self.reason_text}"
        return label

    @property
    def punch_label(self) -> str:
        return PUNCH_LABELS.get(self.punch, "نامشخص")
