"""
مدل جدول اطلاعات تکمیلی کارمندان
"""
from datetime import date
from typing import Optional
from sqlalchemy import Integer, String, Date, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class Employee(TimestampMixin, Base):
    """مدل جدول اطلاعات تکمیلی کارمندان"""
    __tablename__ = "employee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ارتباط با جدول users
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # اطلاعات هویتی
    national_code: Mapped[Optional[str]] = mapped_column(String(10), unique=True, nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    father_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # اطلاعات شخصی
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # M/F
    marital_status: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # S/M

    # اطلاعات تماس و شغلی
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hire_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    department_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    membership_type_code: Mapped[Optional[str]] = mapped_column(
        String(6),
        ForeignKey("membership_types.code", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    position_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Service region used by future annual-leave policy calculations.
    region_code: Mapped[Optional[str]] = mapped_column(
        String(20),
        default='NORMAL',
        comment="Service region: NORMAL, GRADE_2, GRADE_3, GRADE_4"
    )

    # ✅ فیلدهای جدید: وضعیت فعال و ترک کار
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    termination_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    termination_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # یادداشت
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", backref="employee")
    position_rel = relationship("Position", foreign_keys=[position_id])
    department_rel = relationship("Department", foreign_keys=[department_id])
    membership_type_rel = relationship(
        "MembershipType",
        foreign_keys=[membership_type_code],
        primaryjoin="Employee.membership_type_code==MembershipType.code",
    )
    # 🆕 عکس پروفایل
    photo_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    @property
    def position_name(self) -> Optional[str]:
        """نام سمت از جدول مرجع (null-safe)."""
        return self.position_rel.name if self.position_rel else None

    @property
    def department_name(self) -> Optional[str]:
        """نام واحد سازمانی. هرگز نام نوع عضویت نیست."""
        return self.department_rel.name if self.department_rel else None

    @property
    def membership_name(self) -> Optional[str]:
        """نام عضویت پایه کارمند."""
        return self.membership_type_rel.name if self.membership_type_rel else None

    def __repr__(self) -> str:
        status = "فعال" if self.is_active else "غیرفعال"
        return f"<Employee(user_id='{self.user_id}', name='{self.first_name} {self.last_name}', status='{status}')>"

    @property
    def full_name(self) -> str:
        """نام کامل"""
        return f"{self.first_name} {self.last_name}"

    @property
    def gender_name(self) -> str:
        """نام جنسیت"""
        return "مرد" if self.gender == 'M' else "زن" if self.gender == 'F' else "نامشخص"

    @property
    def marital_status_name(self) -> str:
        """نام وضعیت تاهل"""
        return "مجرد" if self.marital_status == 'S' else "متاهل" if self.marital_status == 'M' else "نامشخص"

    @property
    def status_name(self) -> str:
        """نام وضعیت فعال/غیرفعال"""
        return "✅ فعال" if self.is_active else "❌ غیرفعال"

    def to_dict(self) -> dict:
        """تبدیل مدل به دیکشنری"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'national_code': self.national_code,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'father_name': self.father_name,
            'birth_date': self.birth_date,
            'gender': self.gender,
            'gender_name': self.gender_name,
            'marital_status': self.marital_status,
            'marital_status_name': self.marital_status_name,
            'email': self.email,
            'hire_date': self.hire_date,
            'department': self.department_name,
            'department_id': self.department_id,
            'department_name': self.department_name,
            'membership_type_code': self.membership_type_code,
            'membership_name': self.membership_name,
            'position_id': self.position_id,
            'position': self.position_name,
            'region_code': self.region_code,
            'is_active': self.is_active,
            'status_name': self.status_name,
            'termination_date': self.termination_date,
            'termination_reason': self.termination_reason,
            'notes': self.notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'photo_path': self.photo_path,
        }
