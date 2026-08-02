"""
مدل جدول کاربران
"""
from typing import Optional, List
from sqlalchemy import Integer, String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """مدل جدول کاربران"""
    __tablename__ = "users"

    # فیلدهای اصلی
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # user_id: کد پرسنلی (همان user_id در دستگاه ZKTeco)
    user_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    card: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    privilege: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    attendances: Mapped[List["Attendance"]] = relationship(
        "Attendance",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(user_id='{self.user_id}', name='{self.name}')>"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'card': self.card,
            'group_id': self.group_id,
            'privilege': self.privilege,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }