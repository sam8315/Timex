"""
مرجع انواع مدارک پرونده پرسنلی (قابل مدیریت از پنل ادمین)
"""
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class EmployeeDocumentType(TimestampMixin, Base):
    """نوع مدرک پرسنلی — code پایدار و یکتا."""

    __tablename__ = "employee_document_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<EmployeeDocumentType(id={self.id}, code='{self.code}', "
            f"active={self.is_active})>"
        )
