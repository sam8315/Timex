"""Travel Leave domain service."""
import logging
from datetime import date, datetime
from typing import Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session

from core.distance_engine import calculate_distance_km as _calculate_distance_km
from models.city import City
from models.contract import Contract
from models.employee import Employee
from models.employee_service_location import EmployeeServiceLocation
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail
from models.travel_leave_policy import TravelLeavePolicy
from models.travel_leave_policy_rules import TravelLeavePolicyRule, TravelLeaveQuotaSetting

logger = logging.getLogger(__name__)


def resolve_effective_service_location(db: Session, user_id: str, effective_date: date) -> Optional[EmployeeServiceLocation]:
    locations = db.query(EmployeeServiceLocation).filter(
        EmployeeServiceLocation.user_id == user_id,
        EmployeeServiceLocation.effective_from <= effective_date,
        EmployeeServiceLocation.effective_to.is_(None) | (EmployeeServiceLocation.effective_to > effective_date),
    ).order_by(EmployeeServiceLocation.effective_from.desc()).all()
    if not locations:
        return None
    if len(locations) > 1 and locations[0].effective_from == locations[1].effective_from:
        logger.warning("Ambiguous service locations for %s on %s", user_id, effective_date)
        return None
    return locations[0]


def service_location_overlaps(db: Session, user_id: str, from_date: date, to_date: Optional[date], exclude_id: Optional[int] = None):
    locations = db.query(EmployeeServiceLocation).filter(EmployeeServiceLocation.user_id == user_id).all()
    for loc in locations:
        if exclude_id is not None and loc.id == exclude_id:
            continue
        if (to_date is None or loc.effective_from < to_date) and (loc.effective_to is None or from_date < loc.effective_to):
            return loc
    return None


def validate_destination_city(db: Session, city_id: int) -> Optional[City]:
    city = db.query(City).filter(City.id == city_id).first()
    if not city or not city.is_active or city.latitude is None or city.longitude is None:
        return None
    return city


def resolve_effective_contract(db: Session, user_id: str, effective_date: date) -> Optional[Contract]:
    contracts = db.query(Contract).filter(
        Contract.user_id == user_id,
        Contract.start_date <= effective_date,
        Contract.end_date.is_(None) | (Contract.end_date >= effective_date),
    ).order_by(Contract.start_date.desc(), Contract.id.desc()).all()
    if not contracts:
        return None
    if len(contracts) > 1 and contracts[0].start_date == contracts[1].start_date:
        return None
    return contracts[0]


def resolve_policy(db: Session, user_id: str, effective_date: date) -> Tuple[Optional[TravelLeavePolicy], Optional[Contract], Optional[Employee]]:
    contract = resolve_effective_contract(db, user_id, effective_date)
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if not contract or not employee:
        return None, contract, employee
    policy = db.query(TravelLeavePolicy).filter(TravelLeavePolicy.contract_type_code == contract.contract_type_code).first()
    return policy, contract, employee


def calculate_travel_days(distance_km: float, rules: list) -> Tuple[int, Optional[TravelLeavePolicyRule]]:
    for rule in sorted(rules, key=lambda r: r.min_km):
        if rule.min_km <= distance_km <= rule.max_km:
            return rule.travel_days, rule
    return 0, None


def get_quota_setting(db: Session, policy: Optional[TravelLeavePolicy] = None, marital_status: Optional[str] = None, user_id: Optional[str] = None, effective_date: Optional[date] = None) -> Optional[TravelLeaveQuotaSetting]:
    if policy is None and user_id:
        policy, _, employee = resolve_policy(db, user_id, effective_date or date.today())
        marital_status = marital_status or (employee.marital_status if employee else None)
    if not policy or marital_status not in ("S", "M"):
        return None
    return db.query(TravelLeaveQuotaSetting).filter(
        TravelLeaveQuotaSetting.policy_id == policy.id,
        TravelLeaveQuotaSetting.marital_status == marital_status,
    ).first()


def count_approved_travel_leaves_in_year(db: Session, user_id: str, jalali_year: int) -> int:
    return db.query(TravelLeaveDetail).join(LeaveRequest, LeaveRequest.id == TravelLeaveDetail.leave_request_id).filter(
        LeaveRequest.user_id == user_id,
        LeaveRequest.status == "A",
        TravelLeaveDetail.jalali_year == jalali_year,
    ).count()


def check_quota(db: Session, user_id: str, jalali_year: int, policy: Optional[TravelLeavePolicy] = None, marital_status: Optional[str] = None, effective_date: Optional[date] = None) -> Tuple[bool, int, int]:
    if policy is None:
        policy, _, employee = resolve_policy(db, user_id, effective_date or date.today())
        marital_status = marital_status or (employee.marital_status if employee else None)
    setting = get_quota_setting(db, policy, marital_status)
    used = count_approved_travel_leaves_in_year(db, user_id, jalali_year)
    if not setting:
        return False, used, 0
    return used < setting.annual_max_usage, used, setting.annual_max_usage


def calculate_distance(policy: TravelLeavePolicy, origin_city: City, destination_city: City) -> float:
    if policy.distance_method != "geographic":
        raise ValueError("روش محاسبه فاصله انتخاب‌شده هنوز در سامانه پیاده‌سازی نشده است")
    return round(_calculate_distance_km(
        (origin_city.latitude, origin_city.longitude),
        (destination_city.latitude, destination_city.longitude),
    ), 2)


def calculate_distance_km(origin: tuple, destination: tuple) -> float:
    """Backward-compatible direct geographic distance helper."""
    return round(_calculate_distance_km(origin, destination), 2)


def create_travel_leave_detail(db: Session, leave_request: LeaveRequest, destination_city_id: int) -> TravelLeaveDetail:
    if leave_request.leave_type != "AL":
        raise ValueError("Travel Leave is only available for Annual Leave (AL)")
    policy, contract, employee = resolve_policy(db, leave_request.user_id, leave_request.from_date)
    if not policy or not contract or not employee:
        raise ValueError("سیاست مرخصی توراهی برای عضویت مؤثر کاربر یافت نشد")
    if not policy.is_enabled:
        raise ValueError("مرخصی توراهی برای عضویت شما فعال نیست")
    if employee.marital_status not in ("S", "M"):
        raise ValueError("وضعیت تأهل کاربر برای محاسبه سهمیه معتبر نیست")
    esl = resolve_effective_service_location(db, leave_request.user_id, leave_request.from_date)
    if not esl:
        raise ValueError("محل خدمت مؤثر برای تاریخ مرخصی یافت نشد. لطفاً ابتدا محل خدمت خود را تنظیم کنید.")
    origin_city = db.query(City).filter(City.id == esl.city_id).first()
    if not origin_city:
        raise ValueError("شهر محل خدمت یافت نشد")
    dest_city = validate_destination_city(db, destination_city_id)
    if not dest_city:
        raise ValueError("شهر مقصد نامعتبر یا غیرفعال است")
    distance_km = calculate_distance(policy, origin_city, dest_city)
    rules = db.query(TravelLeavePolicyRule).filter(
        TravelLeavePolicyRule.policy_id == policy.id,
        TravelLeavePolicyRule.is_active == 1,
    ).all()
    if not rules:
        raise ValueError("قواعد فاصله مرخصی توراهی برای این عضویت تنظیم نشده است")
    calculated_days, matched_rule = calculate_travel_days(distance_km, rules)
    jalali_year = jdatetime.date.fromgregorian(date=leave_request.from_date).year
    allowed, used, max_allowed = check_quota(db, leave_request.user_id, jalali_year, policy, employee.marital_status)
    if not allowed:
        raise ValueError(f"سهمیه مرخصی توراهی سال {jalali_year} به اتمام رسیده ({used}/{max_allowed} استفاده شده)")
    if calculated_days == 0:
        raise ValueError(f"فاصله {distance_km} کیلومتر است و مرخصی توراهی برای این مسیر قابل استفاده نیست")
    quota = get_quota_setting(db, policy, employee.marital_status)
    detail = TravelLeaveDetail(
        leave_request_id=leave_request.id,
        origin_service_location_id=esl.id,
        origin_city_id=origin_city.id,
        origin_city_name_snapshot=origin_city.name,
        origin_latitude_snapshot=origin_city.latitude,
        origin_longitude_snapshot=origin_city.longitude,
        destination_city_id=dest_city.id,
        destination_city_name_snapshot=dest_city.name,
        destination_province_snapshot=dest_city.province,
        destination_latitude_snapshot=dest_city.latitude,
        destination_longitude_snapshot=dest_city.longitude,
        distance_km=distance_km,
        calculated_travel_days=calculated_days,
        final_travel_days=calculated_days,
        manual_override=False,
        policy_id=policy.id,
        policy_rule_id=matched_rule.id if matched_rule else None,
        membership_code_snapshot=contract.contract_type_code,
        marital_status_snapshot=employee.marital_status,
        distance_method_snapshot=policy.distance_method,
        annual_max_usage_snapshot=quota.annual_max_usage if quota else None,
        rule_min_km_snapshot=matched_rule.min_km if matched_rule else None,
        rule_max_km_snapshot=matched_rule.max_km if matched_rule else None,
        rule_travel_days_snapshot=matched_rule.travel_days if matched_rule else None,
        jalali_year=jalali_year,
        calculated_at=datetime.now(),
    )
    db.add(detail)
    db.flush()
    return detail


def override_travel_days(db: Session, detail_id: int, new_final_days: int, admin_user_id: str, reason: str) -> TravelLeaveDetail:
    if not reason or not reason.strip():
        raise ValueError("دلیل تغییر الزامی است")
    if new_final_days < 0 or new_final_days > 3:
        raise ValueError("تعداد روز باید بین ۰ تا ۳ باشد")
    detail = db.query(TravelLeaveDetail).filter(TravelLeaveDetail.id == detail_id).first()
    if not detail:
        raise ValueError("جزئیات مرخصی توراهی یافت نشد")
    leave_req = db.query(LeaveRequest).filter(LeaveRequest.id == detail.leave_request_id).first()
    if not leave_req or leave_req.status != "P":
        raise ValueError("فقط درخواست‌های در انتظار قابل تغییر هستند")
    detail.final_travel_days = new_final_days
    detail.manual_override = True
    detail.override_reason = reason.strip()
    detail.overridden_by = admin_user_id
    detail.overridden_at = datetime.now()
    db.flush()
    return detail


def get_active_cities(db: Session):
    return db.query(City).filter(City.is_active == True).order_by(City.name).all()
