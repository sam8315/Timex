"""
مدل جدول تراکنش‌های مرخصی
"""
from sqlalchemy import Integer, String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class LeaveTransaction(TimestampMixin, Base):
    """مدل جدول تراکنش‌های مرخصی"""
    __tablename__ = "leave_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    reference_id: Mapped[int] = mapped_column(Integer, nullable=True)

    # Relationships
    user = relationship("User", backref="leave_transactions")

    def __repr__(self) -> str:
        return f"<LeaveTransaction(user_id='{self.user_id}', amount={self.amount}, type='{self.transaction_type}')>"