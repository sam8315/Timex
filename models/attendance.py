"""
مدل جدول رکوردهای تردد
"""
from datetime import datetime, time, date
from typing import Optional
from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint, Boolean, Time, Date, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


class Attendance(TimestampMixin, Base):
    """مدل جدول رکوردهای تردد"""
    __tablename__ = "attendances"

    # فیلدهای اصلی
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )

    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    punch: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 🆕 فیلدهای جدید
    source: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        default='M',
        server_default='M',
        index=True,
        comment="منبع رکورد: D=Device, L=Legacy MySQL, M=Manual"
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default='false',
        index=True,
        comment="حذف منطقی: true=حذف شده، false=فعال"
    )

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="attendances")

    # Constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'timestamp', name='uq_user_timestamp'),
    )

    # 🆕 ثابت‌های کلاس برای source
    SOURCE_DEVICE = 'D'
    SOURCE_LEGACY = 'L'
    SOURCE_MANUAL = 'M'
    SOURCE_ADMS = 'A'

    def __repr__(self) -> str:
        return f"<Attendance(user_id={self.user_id}, timestamp={self.timestamp}, source={self.source})>"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'timestamp': self.timestamp,
            'status': self.status,
            'punch': self.punch,
            'source': self.source,
            'is_deleted': self.is_deleted,
            'synced_at': self.synced_at,
        }

    @staticmethod
    def get_source_name(source_code: str) -> str:
        """تبدیل کد منبع به نام خوانا"""
        names = {
            'D': '📱 دستگاه',
            'L': '📦 MySQL قدیمی',
            'M': '✋ دستی',
            'A': 'ADMS 📱📱',
        }
        return names.get(source_code, f'نامشخص ({source_code})')


# ============================================
# 🆕 Attendance Policy Models (Phase 5)
# ============================================

class AttendancePolicy(TimestampMixin, Base):
    """
    سیاست حضور و غیاب برای هر نوع عضویت (Employment Type)
    هر Policy مربوط به یک نوع عضویت است و بازه زمانی فعال بودن دارد
    """
    __tablename__ = "attendance_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Employment Type (کد دپارتمان Employee: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک)
    employment_type_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="کد نوع عضویت: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک"
    )

    # Override برای کارمند خاص (اختیاری)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="اگر ست شده، این Policy فقط برای این کاربر اعمال می‌شود (Override)"
    )

    # بازه زمانی اعتبار
    effective_from_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="تاریخ شروع اعتبار"
    )
    effective_to_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
        comment="تاریخ پایان اعتبار (NULL = باز)"
    )

    # تنظیمات دیرکرد
    late_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    late_allowed_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="دقیقه مجاز دیرکرد (Grace Period)")
    late_reference_mode: Mapped[str] = mapped_column(
        String(20),
        default='FIXED_TIME',
        nullable=False,
        comment="مرجع محاسبه دیرکرد: FIXED_TIME (از Weekly Schedule) یا SHIFT (آینده)"
    )

    # تنظیمات خروج زود
    early_leave_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    early_leave_allowed_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="دقیقه مجاز خروج زود (Grace Period)")
    early_leave_reference_mode: Mapped[str] = mapped_column(
        String(20),
        default='FIXED_TIME',
        nullable=False,
        comment="مرجع محاسبه خروج زود: FIXED_TIME (از Weekly Schedule) یا SHIFT (آینده)"
    )

    # وضعیت فعال
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", backref="attendance_policy_overrides")
    days: Mapped[List["AttendancePolicyDay"]] = relationship(
        "AttendancePolicyDay",
        back_populates="policy",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        # یک Policy برای هر Employment Type در یک بازه زمانی خاص
        Index('ix_attendance_policies_emp_type_date', 'employment_type_code', 'effective_from_date'),
        # اگر user_id ست باشد، نباید Policy دیگری برای همان کاربر در همپوشانی باشد
        Index('ix_attendance_policies_user_date', 'user_id', 'effective_from_date'),
    )

    def __repr__(self) -> str:
        scope = f"user={self.user_id}" if self.user_id else f"type={self.employment_type_code}"
        return f"<AttendancePolicy({scope}, from={self.effective_from_date}, active={self.is_active})>"


class AttendancePolicyDay(TimestampMixin, Base):
    """
    برنامه هفتگی یک Attendance Policy
    هر روز هفته می‌تواند Working/Non-working باشد و ساعت ورود/خروج متفاوت داشته باشد
    """
    __tablename__ = "attendance_policy_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    policy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("attendance_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # روز هفته: 0=دوشنبه ... 6=یکشنبه (به سبک Python weekday)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False, comment="0=Mon ... 6=Sun")

    # آیا روز کاری است
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ساعت ورود (برای روزهای کاری)
    start_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    # ساعت خروج (برای روزهای کاری)
    end_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)

    # Relationships
    policy: Mapped["AttendancePolicy"] = relationship("AttendancePolicy", back_populates="days")

    __table_args__ = (
        # یک PolicyDay برای هر روز هفته در یک Policy
        Index('uq_attendance_policy_day_policy_weekday', 'policy_id', 'weekday', unique=True),
    )

    def __repr__(self) -> str:
        if self.is_working_day:
            return f"<AttendancePolicyDay(policy={self.policy_id}, wd={self.weekday}, {self.start_time}-{self.end_time})>"
        return f"<AttendancePolicyDay(policy={self.policy_id}, wd={self.weekday}, OFF)>"

    @property
    def required_minutes(self) -> Optional[int]:
        """دقیقه موظفی روز (برای روزهای کاری)"""
        if not self.is_working_day or not self.start_time or not self.end_time:
            return None
        from datetime import datetime, date
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt = datetime.combine(date.today(), self.end_time)
        if end_dt <= start_dt:
            return None
        return int((end_dt - start_dt).total_seconds() / 60)

    @property
    def scheduled_start_str(self) -> Optional[str]:
        return self.start_time.strftime('%H:%M') if self.start_time else None

    @property
    def scheduled_end_str(self) -> Optional[str]:
        return self.end_time.strftime('%H:%M') if self.end_time else None