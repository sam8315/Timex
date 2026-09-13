"""
مدل جدول کاربران
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Integer, String, BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """مدل جدول کاربران"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    card: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    privilege: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default='user', nullable=False)
    web_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    attendances: Mapped[List["Attendance"]] = relationship(
        "Attendance", back_populates="user", cascade="all, delete-orphan"
    )
    user_read_states: Mapped[List["UserAnnouncement"]] = relationship(
        "UserAnnouncement", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User(user_id='{self.user_id}', name='{self.name}', role='{self.role}')>"

    @property
    def is_admin(self) -> bool:
        return self.role in ('admin', 'super_admin')

    @property
    def is_super_admin(self) -> bool:
        return self.role == 'super_admin'

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and datetime.now() < self.locked_until)

    def to_dict(self) -> dict:
        return {
            'id': self.id, 'user_id': self.user_id, 'name': self.name,
            'card': self.card, 'group_id': self.group_id, 'privilege': self.privilege,
            'role': self.role, 'web_enabled': self.web_enabled,
            'last_login': self.last_login, 'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
