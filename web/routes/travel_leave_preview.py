"""Authoritative Travel Leave preview endpoint using the effective policy."""
import jdatetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from models.city import City
from web.dependencies import get_current_user, get_db
from models.user import User
from web.services.travel_leave_service import (
    calculate_distance,
    calculate_travel_days,
    check_quota,
    resolve_effective_service_location,
    resolve_policy,
    validate_destination_city,
)

router = APIRouter(tags=["Leave"])


def _preview_error(message: str, **extra):
    return {
        "success": True,
        "origin_city": extra.get("origin_city", "-"),
        "destination_city": extra.get("destination_city", "-"),
        "distance_km": extra.get("distance_km", 0),
        "travel_days": 0,
        "eligible": False,
        "message": message,
        "quota_used": extra.get("quota_used", 0),
        "quota_max": extra.get("quota_max", 0),
        "quota_allowed": False,
    }


@router.get("/leave/travel-preview")
async def travel_leave_preview(
    from_date: str = Query(...),
    destination_city_id: int = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        from_g = from_j.togregorian()
        policy, contract, employee = resolve_policy(db, user.user_id, from_g)

        if not employee:
            return _preview_error("اطلاعات کارمند برای کاربر یافت نشد")
        if not contract:
            return _preview_error("عضویت/قرارداد مؤثر برای تاریخ انتخاب‌شده یافت نشد")
        if not policy:
            return _preview_error(
                f"سیاست مرخصی توراهی برای نوع عضویت {contract.contract_type_code} تعریف نشده است"
            )
        if not policy.is_enabled:
            return _preview_error("مرخصی توراهی برای نوع عضویت شما غیرفعال است")
        if employee.marital_status not in ("S", "M"):
            return _preview_error("وضعیت تأهل کاربر معتبر نیست")

        esl = resolve_effective_service_location(db, user.user_id, from_g)
        if not esl:
            return _preview_error("محل خدمت مؤثر برای تاریخ انتخاب‌شده یافت نشد")
        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        dest_city = validate_destination_city(db, destination_city_id)
        if not origin_city or not dest_city:
            return _preview_error("شهر مبدأ یا مقصد نامعتبر است")

        distance_km = calculate_distance(policy, origin_city, dest_city)
        from models.travel_leave_policy_rules import TravelLeavePolicyRule
        rules = db.query(TravelLeavePolicyRule).filter(
            TravelLeavePolicyRule.policy_id == policy.id,
            TravelLeavePolicyRule.is_active == 1,
        ).all()
        if not rules:
            return _preview_error(
                "قواعد فاصله برای این نوع عضویت تعریف نشده است",
                origin_city=origin_city.name,
                destination_city=dest_city.name,
                distance_km=distance_km,
            )

        travel_days, _ = calculate_travel_days(distance_km, rules)
        jalali_year = jdatetime.date.fromgregorian(date=from_g).year
        allowed, used, max_allowed = check_quota(
            db, user.user_id, jalali_year, policy, employee.marital_status, from_g
        )
        eligible = travel_days > 0 and allowed
        message = None if eligible else (
            f"سهمیه سالانه تکمیل شده است ({used}/{max_allowed})"
            if travel_days > 0 and not allowed
            else "مسافت انتخاب‌شده مشمول مرخصی توراهی نیست"
        )
        return {
            "success": True,
            "origin_city": origin_city.name,
            "destination_city": dest_city.name,
            "destination_province": dest_city.province or "",
            "distance_km": distance_km,
            "travel_days": travel_days,
            "eligible": eligible,
            "message": message,
            "quota_used": used,
            "quota_max": max_allowed,
            "quota_allowed": allowed,
            "jalali_year": jalali_year,
            "distance_method": policy.distance_method,
            "contract_type_code": contract.contract_type_code,
            "marital_status": employee.marital_status,
        }
    except Exception as exc:
        return _preview_error(f"خطا در محاسبه مرخصی توراهی: {exc}")
