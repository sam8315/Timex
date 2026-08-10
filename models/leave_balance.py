"""
مدل جدول مانده مرخصی
"""
from sqlalchemy import Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from models.base import Base, TimestampMixin


class LeaveBalance(TimestampMixin, Base):
    """مدل جدول مانده مرخصی"""
    __tablename__ = "leave_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    leave_type: Mapped[str] = mapped_column(String(2), nullable=False, index=True)

    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 🆕 فیلدهای انتقال مرخصی
    is_carried_forward: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    carried_from_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    user = relationship("User", backref="leave_balances")

    def __repr__(self) -> str:
        return f"<LeaveBalance(user_id='{self.user_id}', year={self.year}, type='{self.leave_type}', carried={self.is_carried_forward})>"