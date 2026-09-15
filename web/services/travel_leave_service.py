"""Travel Leave domain service.

Responsible for:
- AL-only validation
- Effective service-location resolution
- Destination validation
- Policy resolution / distance-band rule selection
- Distance calculation (delegates to distance_engine)
- Quota validation
- Constructing/persisting TravelLeaveDetail
- Authorized manual override
"""
import logging
from datetime import date, datetime
from typing import Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from models.city import City
from models.employee_service_location import EmployeeServiceLocation
from models.leave_request import LeaveRequest
from models.travel_leave_detail import TravelLeaveDetail
from models.travel_leave_policy_rules import (
    TravelLeavePolicyRule,
    TravelLeaveQuotaSetting,
)
from core.distance_engine import calculate_distance_km

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service-location resolution
# ---------------------------------------------------------------------------

def resolve_effective_service_location(
    db: Session, user_id: str, effective_date: date
) -> Optional[EmployeeServiceLocation]:
    """Return the effective EmployeeServiceLocation for user on effective_date.

    Rules:
      effective_from <= effective_date AND (effective_to IS NULL OR effective_date < effective_to)

    If multiple match, reject (return None) to avoid ambiguity.
    """
    locations = (
        db.query(EmployeeServiceLocation)
        .filter(
            EmployeeServiceLocation.user_id == user_id,
            EmployeeServiceLocation.effective_from <= effective_date,
            (
                EmployeeServiceLocation.effective_to.is_(None)
                | (EmployeeServiceLocation.effective_to > effective_date)
            ),
        )
        .order_by(EmployeeServiceLocation.effective_from.desc())
        .all()
    )

    if len(locations) == 0:
        return None
    if len(locations) == 1:
        return locations[0]

    # Multiple effective assignments — deterministic: use most recent effective_from
    # If still ambiguous (same effective_from), reject.
    if len(locations) >= 2 and locations[0].effective_from == locations[1].effective_from:
        logger.warning(
            "Ambiguous service locations for %s on %s: %d matches with same effective_from",
            user_id, effective_date, len(locations),
        )
        return None

    return locations[0]


# ---------------------------------------------------------------------------
# Destination validation
# ---------------------------------------------------------------------------

def validate_destination_city(
    db: Session, city_id: int
) -> Optional[City]:
    """Return active City with valid coordinates, or None."""
    city = db.query(City).filter(City.id == city_id).first()
    if not city or not city.is_active:
        return None
    if city.latitude is None or city.longitude is None:
        return None
    return city


# ---------------------------------------------------------------------------
# Distance + travel days
# ---------------------------------------------------------------------------

def calculate_travel_days(distance_km: float, rules: list) -> Tuple[int, Optional[TravelLeavePolicyRule]]:
    """Determine travel days from distance using the provided rules.

    Returns (travel_days, matched_rule).
    If no rule matches, returns (0, None).
    """
    for rule in sorted(rules, key=lambda r: r.min_km):
        if rule.min_km <= distance_km <= rule.max_km:
            return rule.travel_days, rule
    return 0, None


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------

def get_quota_setting(db: Session) -> TravelLeaveQuotaSetting:
    """Return the active quota setting (create default if missing)."""
    setting = db.query(TravelLeaveQuotaSetting).first()
    if not setting:
        setting = TravelLeaveQuotaSetting(
            annual_max_usage=3,
            description="Max approved travel leave uses per Jalali year",
            parameter_key="annual_max_usage",
            parameter_value="3",
        )
        db.add(setting)
        db.flush()
    return setting


def count_approved_travel_leaves_in_year(
    db: Session, user_id: str, jalali_year: int
) -> int:
    """Count approved Travel Leave requests for user in the given Jalali year."""
    return (
        db.query(TravelLeaveDetail)
        .join(LeaveRequest, LeaveRequest.id == TravelLeaveDetail.leave_request_id)
        .filter(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == "A",
            TravelLeaveDetail.jalali_year == jalali_year,
        )
        .count()
    )


def check_quota(
    db: Session, user_id: str, jalali_year: int
) -> Tuple[bool, int, int]:
    """Check if user has remaining Travel Leave quota.

    Returns (allowed, used, max_allowed).
    """
    setting = get_quota_setting(db)
    used = count_approved_travel_leaves_in_year(db, user_id, jalali_year)
    max_allowed = setting.annual_max_usage
    return used < max_allowed, used, max_allowed


# ---------------------------------------------------------------------------
# Main: create Travel Leave detail
# ---------------------------------------------------------------------------

def create_travel_leave_detail(
    db: Session,
    leave_request: LeaveRequest,
    destination_city_id: int,
) -> TravelLeaveDetail:
    """Validate and create a TravelLeaveDetail for an AL request.

    All calculations are server-side; the browser is never trusted.
    Raises ValueError with a user-facing message on any validation failure.
    """
    # 1. AL-only validation
    if leave_request.leave_type != "AL":
        raise ValueError("Travel Leave is only available for Annual Leave (AL)")

    # 2. Resolve effective service location
    esl = resolve_effective_service_location(db, leave_request.user_id, leave_request.from_date)
    if not esl:
        raise ValueError(
            "محل خدمت مؤثر برای تاریخ مرخصی یافت نشد. "
            "لطفاً ابتدا محل خدمت خود را تنظیم کنید."
        )

    origin_city = db.query(City).filter(City.id == esl.city_id).first()
    if not origin_city:
        raise ValueError("شهر محل خدمت یافت نشد")

    # 3. Validate destination
    dest_city = validate_destination_city(db, destination_city_id)
    if not dest_city:
        raise ValueError("شهر مقصد نامعتبر یا غیرفعال است")

    # 4. Calculate distance
    distance_km = calculate_distance_km(
        (origin_city.latitude, origin_city.longitude),
        (dest_city.latitude, dest_city.longitude),
    )
    distance_km = round(distance_km, 2)

    # 5. Resolve rules
    rules = (
        db.query(TravelLeavePolicyRule)
        .filter(TravelLeavePolicyRule.is_active == 1)
        .all()
    )
    if not rules:
        raise ValueError("Travel Leave policy rules are not configured")

    calculated_days, matched_rule = calculate_travel_days(distance_km, rules)

    # 6. Quota check (only matters for eligible requests, but check always)
    jalali_year = jdatetime.date.fromgregorian(date=leave_request.from_date).year
    allowed, used, max_allowed = check_quota(db, leave_request.user_id, jalali_year)
    if not allowed:
        raise ValueError(
            f"سهمیه مرخصی توراهی سال {jalali_year} به اتمام رسیده "
            f"({used}/{max_allowed} استفاده شده)"
        )

    if calculated_days == 0:
        raise ValueError(
            f"فاصله {distance_km} کیلومتر است و کمتر از ۲۰۰ کیلومتر می‌باشد. "
            "مرخصی توراهی برای این مسیر قابل استفاده نیست."
        )

    # 7. Get quota setting snapshot
    quota = get_quota_setting(db)

    # 8. Build detail
    now = datetime.now()
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
        policy_id=None,
        policy_rule_id=matched_rule.id if matched_rule else None,
        annual_max_usage_snapshot=quota.annual_max_usage,
        rule_min_km_snapshot=matched_rule.min_km if matched_rule else None,
        rule_max_km_snapshot=matched_rule.max_km if matched_rule else None,
        rule_travel_days_snapshot=matched_rule.travel_days if matched_rule else None,
        jalali_year=jalali_year,
        calculated_at=now,
    )
    db.add(detail)
    db.flush()
    return detail


# ---------------------------------------------------------------------------
# Admin override
# ---------------------------------------------------------------------------

def override_travel_days(
    db: Session,
    detail_id: int,
    new_final_days: int,
    admin_user_id: str,
    reason: str,
) -> TravelLeaveDetail:
    """Admin override of final travel days.

    Preserves calculated value, records actor/timestamp/reason.
    Only allowed for pending requests.
    """
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

    now = datetime.now()
    detail.final_travel_days = new_final_days
    detail.manual_override = True
    detail.override_reason = reason.strip()
    detail.overridden_by = admin_user_id
    detail.overridden_at = now
    db.flush()
    return detail


# ---------------------------------------------------------------------------
# Cities for dropdown
# ---------------------------------------------------------------------------

def get_active_cities(db: Session):
    """Return all active cities ordered by name."""
    return db.query(City).filter(City.is_active == True).order_by(City.name).all()
