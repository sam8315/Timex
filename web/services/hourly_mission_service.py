"""
سرویس مأموریت ساعتی (Hourly Mission Service)

فقط Policy Resolution — validation/approval فازهای بعد.
Priority (mirrors HourlyLeavePolicy):
    Employee Override → Employment Type Policy → Default
"""
from datetime import date
from typing import Optional, Dict

from sqlalchemy import and_
from sqlalchemy.orm import Session

from models.employee import Employee
from models.hourly_mission import HourlyMissionPolicy


# System/default fallback (بخش ۷ راهنما)
DEFAULT_HOURLY_MISSION_SETTINGS: Dict[str, bool] = {
    'enabled': True,
    'working_hours_only': True,
    'allowed_on_holidays': False,
    'deduct_from_required_minutes': True,
}


def resolve_hourly_mission_policy(
    db: Session,
    employee: Employee,
    target_date: date
) -> Optional[HourlyMissionPolicy]:
    """
    پیدا کردن سیاست مأموریت ساعتی معتبر برای یک کارمند در یک تاریخ

    Priority:
    1. Employee Override (user_id = employee.user_id)
    2. Employment Type Policy (employment_type_code = employee.department)

    Returns:
        HourlyMissionPolicy یا None اگر پیدا نشود
    """
    employment_type = employee.department if employee else None
    if not employment_type:
        return None

    # مرحله ۱: Employee Override
    override = db.query(HourlyMissionPolicy).filter(
        and_(
            HourlyMissionPolicy.user_id == employee.user_id,
            HourlyMissionPolicy.is_active == True,
            HourlyMissionPolicy.effective_from_date <= target_date,
            (
                HourlyMissionPolicy.effective_to_date.is_(None) |
                (HourlyMissionPolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyMissionPolicy.effective_from_date.desc()).first()

    if override:
        return override

    # مرحله ۲: Employment Type Policy
    emp_policy = db.query(HourlyMissionPolicy).filter(
        and_(
            HourlyMissionPolicy.employment_type_code == employment_type,
            HourlyMissionPolicy.user_id.is_(None),
            HourlyMissionPolicy.is_active == True,
            HourlyMissionPolicy.effective_from_date <= target_date,
            (
                HourlyMissionPolicy.effective_to_date.is_(None) |
                (HourlyMissionPolicy.effective_to_date >= target_date)
            )
        )
    ).order_by(HourlyMissionPolicy.effective_from_date.desc()).first()

    return emp_policy


def get_effective_hourly_mission_settings(
    db: Session,
    employee: Employee,
    target_date: date
) -> Dict[str, bool]:
    """
    دریافت چهار تنظیم مؤثر برای کارمند در تاریخ مشخص.

    اگر policy پیدا نشود → defaultهای سراسری.
    """
    policy = resolve_hourly_mission_policy(db, employee, target_date)
    if not policy:
        return dict(DEFAULT_HOURLY_MISSION_SETTINGS)
    return policy.settings
