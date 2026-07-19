"""
مدل قرارداد گروه‌ها
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base


class GroupContract(Base):
    """مدل جدول قرارداد گروه‌ها"""
    __tablename__ = "group_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(50), nullable=False)
    annual_leave_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    def __repr__(self) -> str:
        return f"<GroupContract(group_id={self.group_id}, name='{self.group_name}')>"