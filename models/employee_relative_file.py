"""فایل‌های پیوست بستگان کارکنان (چند فایل به ازای هر فرد)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


class EmployeeRelativeFile(TimestampMixin, Base):
    __tablename__ = "employee_relative_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    relative_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("employee_relatives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    uploaded_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    relative = relationship("EmployeeRelative", back_populates="files")

    def __repr__(self) -> str:
        return (
            f"<EmployeeRelativeFile(id={self.id}, relative_id={self.relative_id}, "
            f"file={self.original_filename!r})>"
        )
