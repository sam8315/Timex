"""
مدل جدول مأموریت ساعتی

مستقل از LeaveRequest (مرخصی) و DailyStatus (وضعیت روزانه).
مأموریت ساعتی فقط بخشی از یک روز را پوشش می‌دهد.
"""
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


# وضعیت‌های درخواست (همان convention مدل LeaveRequest)
STATUS_CODES = {
    'P': '⏳ در انتظار',
    'A': '✅ تایید شده',
    'R': '❌ رد شده',
    'D': '🗑️ لغو شده',
}


class HourlyMission(TimestampMixin, Base):
    """مدل جدول مأموریت ساعتی"""
    __tablename__ = "hourly_missions"

    __table_args__ = (
        # ساعت شروع باید قبل از ساعت پایان باشد
        CheckConstraint(
            'start_time < end_time',
            name='ck_hourly_missions_time_order',
        ),
        # مقادیر مجاز وضعیت
        CheckConstraint(
            "status IN ('P', 'A', 'R', 'D')",
            name='ck_hourly_missions_status',
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    mission_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="مقصد مأموریت"
    )

    # وضعیت: P=Pending, A=Approved, R=Rejected, D=Cancelled
    status: Mapped[str] = mapped_column(String(1), default='P', nullable=False, index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="hourly_missions")

    def __repr__(self) -> str:
        return f"<HourlyMission(user_id='{self.user_id}', date={self.mission_date}, status='{self.status}')>"

    @property
    def status_name(self) -> str:
        """نام فارسی وضعیت"""
        return STATUS_CODES.get(self.status, 'نامشخص')

    @property
    def duration_minutes(self) -> int:
        """مدت مأموریت به دقیقه (محاسبه‌شده — ذخیره نمی‌شود)"""
        if not self.start_time or not self.end_time:
            return 0
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return max(0, end - start)

    @property
    def duration_display(self) -> str:
        """نمایش مدت مأموریت به شکل ساعت"""
        minutes = self.duration_minutes
        return f"{minutes // 60}:{minutes % 60:02d}"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'mission_date': self.mission_date.isoformat(),
            'start_time': self.start_time.strftime('%H:%M'),
            'end_time': self.end_time.strftime('%H:%M'),
            'duration_minutes': self.duration_minutes,
            'reason': self.reason,
            'destination': self.destination,
            'status': self.status,
            'status_name': self.status_name,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejection_reason': self.rejection_reason,
        }
