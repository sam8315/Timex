"""
مدل جدول کاربران
"""
from typing import Optional, List
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """مدل جدول کاربران"""
    __tablename__ = "users"

    # فیلدهای اصلی
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    card: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    privilege: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    attendances: Mapped[List["Attendance"]] = relationship(
        "Attendance",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, uid={self.uid}, name='{self.name}')>"

    def to_dict(self) -> dict:
        """تبدیل مدل به دیکشنری"""
        return {
            'id': self.id,
            'uid': self.uid,
            'name': self.name,
            'card': self.card,
            'group_id': self.group_id,
            'privilege': self.privilege,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }