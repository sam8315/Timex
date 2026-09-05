"""
مدل جدول سوابق نظام وظیفه
"""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import Integer, String, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models.base import Base, TimestampMixin


# وضعیت‌های نظام وظیفه
MILITARY_STATUS = {
    'not_started': {
        'name': 'شروع نشده',
        'color': 'secondary',
        'icon': '⏳',
    },
    'in_progress': {
        'name': 'در حال خدمت',
        'color': 'warning',
        'icon': '🎖️',
    },
    'completed': {
        'name': 'پایان یافته',
        'color': 'success',
        'icon': '✅',
    },
    'exempted': {
        'name': 'معاف',
        'color': 'info',
        'icon': '🛡️',
    },
}

# انواع معافیت
EXEMPTION_TYPES = {
    'medical': {
        'name': 'پزشکی',
        'description': 'معافیت به دلیل مشکلات پزشکی',
    },
    'family': {
        'name': 'کفالت',
        'description': 'معافیت به دلیل کفالت خانواده',
    },
    'hardship': {
        'name': 'سختی',
        'description': 'معافیت به دلیل شرایط خاص',
    },
    'education': {
        'name': 'تحصیلی',
        'description': 'معافیت به دلیل ادامه تحصیل',
    },
    'other': {
        'name': 'سایر',
        'description': 'سایر موارد معافیت',
    },
}

# انواع خدمت و مدت هرکدام بر اساس ماه
SERVICE_TYPES = {
    'normal': {
        'name': 'مناطق عادی (دوره ضرورت)',
        'months': 21,
        'description': 'خدمت در مناطق عادی',
    },
    'amriyeh': {
        'name': 'امریه',
        'months': 24,
        'description': 'سربازان امریه (دستگاه‌های غیرنظامی)',
    },
    'combat': {
        'name': 'مناطق عملیاتی و امنیتی',
        'months': 14,
        'description': 'مناطق عملیاتی و امنیتی درگیر',
    },
    'border': {
        'name': 'مناطق مرزی و جزیره‌ای',
        'months': 15,
        'description': 'مناطق مرزی و جزیره‌ای',
    },
    'non_local': {
        'name': 'غیربومی (+۲۰۰ کیلومتر)',
        'months': 18,
        'description': 'افراد غیربومی با فاصله بیش از ۲۰۰ کیلومتر',
    },
}


def calculate_end_date(start_date: date, service_type: str, deduction_days: int = 0) -> date:
    """
    محاسبه تاریخ پایان مورد انتظار بر اساس نوع خدمت و کسر خدمت.
    ابتدا ماه‌ها اضافه می‌شود، سپس روزهای کسر خدمت کم می‌شود.
    """
    months = SERVICE_TYPES.get(service_type, {}).get('months', 21)
    # اضافه کردن ماه‌ها
    end_month = start_date.month + months
    end_year = start_date.year + (end_month - 1) // 12
    end_month = ((end_month - 1) % 12) + 1
    # حفظ روز (با توجه به تعداد روزهای ماه)
    import calendar
    max_day = calendar.monthrange(end_year, end_month)[1]
    end_day = min(start_date.day, max_day)
    expected = date(end_year, end_month, end_day)
    # کسر روزهای کسری
    expected -= timedelta(days=deduction_days)
    return expected


class MilitaryService(TimestampMixin, Base):
    """مدل جدول سوابق نظام وظیفه"""
    __tablename__ = "military_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ارتباط با جدول کاربران
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # وضعیت نظام وظیفه
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='not_started',
        index=True
    )

    # نوع خدمت
    service_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True
    )

    # نوع معافیت (فقط در صورت معاف بودن)
    exemption_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True
    )

    # توضیحات معافیت
    exemption_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # تاریخ‌های خدمت
    start_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True
    )

    expected_end_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True
    )

    actual_end_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True
    )

    # روزهای کسر خدمت
    total_deduction_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    used_deduction_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    # شماره خدمت
    service_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True
    )

    # یادداشت
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # مسیر فایل گواهی
    file_path: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )

    # Relationships
    user = relationship("User", backref="military_service")

    def __repr__(self) -> str:
        return f"<MilitaryService(user_id='{self.user_id}', status='{self.status}')>"

    # ============================================
    # Properties
    # ============================================

    @property
    def status_name(self) -> str:
        """نام فارسی وضعیت"""
        return MILITARY_STATUS.get(self.status, {}).get('name', 'نامشخص')

    @property
    def status_color(self) -> str:
        """رنگ وضعیت"""
        return MILITARY_STATUS.get(self.status, {}).get('color', 'secondary')

    @property
    def status_icon(self) -> str:
        """آیکون وضعیت"""
        return MILITARY_STATUS.get(self.status, {}).get('icon', '❓')

    @property
    def service_type_name(self) -> Optional[str]:
        """نام فارسی نوع خدمت"""
        if not self.service_type:
            return None
        return SERVICE_TYPES.get(self.service_type, {}).get('name', 'نامشخص')

    @property
    def service_duration_months(self) -> Optional[int]:
        """مدت خدمت به ماه بر اساس نوع خدمت"""
        if not self.service_type:
            return None
        return SERVICE_TYPES.get(self.service_type, {}).get('months')

    @property
    def service_duration_days(self) -> Optional[int]:
        """مدت خدمت به روز"""
        if not self.start_date:
            return None

        end = self.actual_end_date or self.expected_end_date or date.today()
        return (end - self.start_date).days + 1

    @property
    def exemption_type_name(self) -> Optional[str]:
        """نام فارسی نوع معافیت"""
        if not self.exemption_type:
            return None
        return EXEMPTION_TYPES.get(self.exemption_type, {}).get('name', 'نامشخص')

    @property
    def remaining_deduction_days(self) -> int:
        """روزهای کسر خدمت باقیمانده"""
        return max(0, self.total_deduction_days - self.used_deduction_days)

    @property
    def is_active(self) -> bool:
        """آیا در حال خدمت است؟"""
        return self.status == 'in_progress'

    @property
    def can_use_deduction(self) -> bool:
        """آیا می‌تواند از کسر خدمت استفاده کند؟"""
        return self.status in ['in_progress', 'completed'] and self.remaining_deduction_days > 0

    def to_dict(self) -> dict:
        """تبدیل مدل به دیکشنری"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'status': self.status,
            'status_name': self.status_name,
            'status_color': self.status_color,
            'status_icon': self.status_icon,
            'service_type': self.service_type,
            'service_type_name': self.service_type_name,
            'exemption_type': self.exemption_type,
            'exemption_type_name': self.exemption_type_name,
            'exemption_reason': self.exemption_reason,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'expected_end_date': self.expected_end_date.isoformat() if self.expected_end_date else None,
            'actual_end_date': self.actual_end_date.isoformat() if self.actual_end_date else None,
            'total_deduction_days': self.total_deduction_days,
            'used_deduction_days': self.used_deduction_days,
            'remaining_deduction_days': self.remaining_deduction_days,
            'service_number': self.service_number,
            'notes': self.notes,
            'file_path': self.file_path,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
