"""مرجع دپارتمان‌های سازمانی. مستقل از نوع عضویت."""
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Department(TimestampMixin, Base):
    """واحد سازمانی (داروخانه، مالی، …). نام آن کلید سیاست استخدامی نیست."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Department(id={self.id}, name='{self.name}', active={self.is_active})>"
