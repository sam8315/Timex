"""
مدل جدول قراردادها
"""
from datetime import date
from typing import Optional
from sqlalchemy import Integer, String, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class Contract(TimestampMixin, Base):
    """مدل جدول قراردادها"""
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # انواع مرخصی بر اساس قرارداد
    annual_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sick_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reward_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unpaid_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="contracts")

    def __repr__(self) -> str:
        return f"<Contract(user_id='{self.user_id}', type='{self.contract_type}')>"