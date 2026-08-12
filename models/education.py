"""
مدل جدول تحصیلات
"""
from datetime import date
from typing import Optional
from sqlalchemy import Integer, String, ForeignKey, Boolean, Date, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin

# گروه‌های تحصیلی
EDUCATION_GROUPS = {
    'TECH': 'فنی و مهندسی',
    'MEDICAL': 'علوم پزشکی',
    'HUMANITIES': 'علوم انسانی',
    'BASIC': 'علوم پایه',
    'ART': 'هنر',
    'AGRICULTURE': 'کشاورزی',
    'OTHER': 'سایر',
}

# مقاطع تحصیلی
DEGREE_LEVELS = {
    'HIGH_SCHOOL': 'دیپلم',
    'DIPLOMA': 'فوق دیپلم/کاردانی',
    'BACHELOR': 'لیسانس/کارشناسی',
    'MASTER': 'فوق لیسانس/کارشناسی ارشد',
    'PHD': 'دکترا',
    'POST_DOC': 'فوق دکترا',
}

# اولویت مقاطع (برای تعیین بالاترین مدرک)
DEGREE_PRIORITY = {
    'HIGH_SCHOOL': 1,
    'DIPLOMA': 2,
    'BACHELOR': 3,
    'MASTER': 4,
    'PHD': 5,
    'POST_DOC': 6,
}


class Education(TimestampMixin, Base):
    """مدل جدول تحصیلات"""
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    education_group: Mapped[str] = mapped_column(String(20), nullable=False)
    degree_level: Mapped[str] = mapped_column(String(20), nullable=False)
    major: Mapped[str] = mapped_column(String(100), nullable=False)
    graduation_date: Mapped[date] = mapped_column(Date, nullable=False)

    certificate_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    certificate_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    is_highest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="educations")

    def __repr__(self) -> str:
        return f"<Education(user_id='{self.user_id}', degree='{self.degree_level}', major='{self.major}')>"

    @property
    def education_group_name(self) -> str:
        return EDUCATION_GROUPS.get(self.education_group, self.education_group)

    @property
    def degree_level_name(self) -> str:
        return DEGREE_LEVELS.get(self.degree_level, self.degree_level)