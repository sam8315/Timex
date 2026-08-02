"""
مدل جدول مانده مرخصی
"""
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
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

    # Relationships
    user = relationship("User", backref="leave_balances")

    def __repr__(self) -> str:
        return f"<LeaveBalance(user_id='{self.user_id}', year={self.year}, type='{self.leave_type}')>"