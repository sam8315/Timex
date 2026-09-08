"""
مدل جدول رکوردهای تردد
"""
from datetime import datetime, time, date
from typing import Optional
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, Boolean, Time, Date, Enum, Index
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


# ============================================
# Phase 7: Hourly Leave Models
# ============================================

class HourlyLeavePolicy(TimestampMixin, Base):
    """
    سیاست مرخصی ساعتی برای هر نوع عضویت (Employment Type)
    هر Policy مربوط به یک نوع عضویت است و بازه زمانی فعال بودن دارد
    NO weekly schedule — uses AttendancePolicyDay for working hours
    """
    __tablename__ = "hourly_leave_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Scope (mirrors AttendancePolicy)
    employment_type_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="کد نوع عضویت: 1=رسمی، 2=وظیفه، 3=خریدخدمت، 4=قراردادی، 5=پزشک"
    )

    user_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="اگر ست شده، این Policy فقط برای این کاربر اعمال می‌شود (Override)"
    )

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

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # HL-specific rules (NO weekly schedule — uses AttendancePolicyDay)
    hourly_leave_entitled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="اگر false: می‌توان درخواست داد اما معافیت ماهانه ندارد (100% مشمول استحقاقی)"
    )

    max_daily_minutes: Mapped[int] = mapped_column(
        Integer,
        default=180,
        nullable=False,
        comment="حداکثر دقیقه مرخصی ساعتی در روز — بیشتر از این = تبدیل به یک روز کامل"
    )

    monthly_exempt_minutes: Mapped[int] = mapped_column(
        Integer,
        default=480,
        nullable=False,
        comment="دقایق معاف از مرخصی استحقاقی در ماه (هر ماه ریست می‌شود، بدون انتقال)"
    )

    conversion_minutes_per_day: Mapped[int] = mapped_column(
        Integer,
        default=480,
        nullable=False,
        comment="دقیقه معادل یک روز مرخصی استحقاقی (مستقل از ساعت کاری روزانه)"
    )

    granularity_minutes: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
        comment="حداقل و واحد گرد زمانی (مثلاً ۱۵ دقیقه)"
    )

    min_request_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=15,
        comment="حداقل دقایق درخواست مرخصی ساعتی"
    )

    max_request_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=240,
        comment="حداکثر دقایق درخواست مرخصی ساعتی"
    )

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", backref="hourly_leave_policy_overrides")

    __table_args__ = (
        Index('ix_hourly_leave_policies_emp_type_date', 'employment_type_code', 'effective_from_date'),
        Index('ix_hourly_leave_policies_user_date', 'user_id', 'effective_from_date'),
    )

    def __repr__(self) -> str:
        scope = f"user={self.user_id}" if self.user_id else f"type={self.employment_type_code}"
        return f"<HourlyLeavePolicy({scope}, from={self.effective_from_date}, active={self.is_active})>"


class HourlyLeaveResolution(TimestampMixin, Base):
    """
    تاریخچه تصمیم‌گیری برای هر درخواست مرخصی ساعتی
    شامل تمام محاسبات در زمان تایید: معافیت ماهانه، محدودیت روزانه، انباشت سالانه، تبدیل به استحقاقی
    """
    __tablename__ = "hourly_leave_resolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leave_request_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="شناسه درخواست مرخصی"
    )

    # Input
    requested_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="دقایق درخواست شده"
    )

    # Policy snapshot at approval time
    policy_conversion_rate: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="نرخ تبدیل policy در زمان تایید (دقیقه = 1 روز)"
    )
    policy_monthly_exempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="معافیت ماهانه policy در زمان تایید"
    )
    policy_daily_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="محدودیت روزانه policy در زمان تایید"
    )
    policy_entitled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="آیا در زمان تایید entitled بوده یا خیر"
    )

    # Daily limit check
    daily_usage_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="دقایق مرخصی ساعتی تایید شده در همان روز قبل از این درخواست"
    )
    daily_usage_after: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="دقایق مرخصی ساعتی تایید شده در همان روز بعد از این درخواست"
    )
    daily_limit_exceeded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="آیا محدودیت روزانه نقض شده است"
    )
    full_day_conversion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="آیا به دلیل نقض محدودیت روزانه، به یک روز کامل تبدیل شده است"
    )

    # Monthly exempt calculation
    monthly_exempt_used_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="دقایق معاف استفاده شده در همان ماه قبل از این درخواست"
    )
    monthly_exempt_applied: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="دقایق معاف اعمال شده برای این درخواست"
    )

    # Subject to AL
    minutes_subject_to_al: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="دقایق مشمول کسر از مرخصی استحقاقی"
    )

    # Annual accumulation
    annual_subject_minutes_before: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="مجموع دقایق مشمول استحقاقی در سال قبل از این درخواست"
    )
    annual_subject_minutes_after: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="مجموع دقایق مشمول استحقاقی در سال بعد از این درخواست"
    )
    annual_remainder_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="باقیمانده دقایق مشمول استحقاقی پس از تبدیل به روز"
    )

    # AL conversion (only newly completed days)
    new_al_days_deducted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="تعداد روزهای مرخصی استحقاقی کسر شده در این درخواست"
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default='PENDING',
        comment="وضعیت: PENDING, APPROVED, REJECTED, REVERSED"
    )

    # Relationships
    leave_request: Mapped["LeaveRequest"] = relationship("LeaveRequest", backref="hourly_resolution")

    def __repr__(self) -> str:
        return f"<HourlyLeaveResolution(request={self.leave_request_id}, status={self.status}, al_days={self.new_al_days_deducted})>"


class HourlyLeaveTransaction(TimestampMixin, Base):
    """
    تراکنش‌های مرخصی ساعتی بر اساس دقیقه (جدا از تراکنش‌های روزانه)
    """
    __tablename__ = "hourly_leave_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="شناسه کاربر"
    )
    year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="سال شمسی"
    )
    month: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="ماه شمسی"
    )
    amount_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="دقایق مرخصی ساعتی"
    )
    transaction_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        comment="نوع تراکنش: USE, REVERSE"
    )
    exempt_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="دقایق معاف از کسر"
    )
    subject_to_al_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="دقایق مشمول کسر از استحقاقی"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="توضیحات"
    )
    reference_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="شناسه درخواست مرخصی مرتبط"
    )

    # Relationships
    user: Mapped["User"] = relationship("User", backref="hourly_leave_transactions")

    __table_args__ = (
        Index('idx_hourly_leave_transactions_user_year_month', 'user_id', 'year', 'month'),
    )

    def __repr__(self) -> str:
        return f"<HourlyLeaveTransaction(user={self.user_id}, {self.year}/{self.month}, {self.amount_minutes}min, {self.transaction_type})>"