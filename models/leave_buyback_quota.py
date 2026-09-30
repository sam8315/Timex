"""
سهمیه/ماندهٔ قابل‌بازخرید (فرآیندی — نه نوع مرخصی مصرفی).
"""
from typing import Optional
from sqlalchemy import Integer, String, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class LeaveBuybackQuota(TimestampMixin, Base):
    """روزهای قابل‌بازخرید ثبت‌شده (مثلاً ورود اولیه از HR)."""

    __tablename__ = "leave_buyback_quotas"
    __table_args__ = (
        UniqueConstraint('user_id', 'year', name='uq_leave_buyback_user_year'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(
        String(30),
        default='HR_IMPORT',
        nullable=False,
        comment="HR_IMPORT / YEAR_END / MANUAL",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user = relationship("User", backref="leave_buyback_quotas")

    def __repr__(self) -> str:
        return (
            f"<LeaveBuybackQuota(user_id='{self.user_id}', year={self.year}, "
            f"days={self.days})>"
        )
