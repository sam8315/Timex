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
        if not policy or not contract or not employee:
            return {"success": False, "message": "سیاست مرخصی توراهی برای عضویت مؤثر یافت نشد"}
        if not policy.is_enabled:
            return {"success": False, "message": "مرخصی توراهی برای عضویت شما فعال نیست"}
        if employee.marital_status not in ("S", "M"):
            return {"success": False, "message": "وضعیت تأهل کاربر معتبر نیست"}

        esl = resolve_effective_service_location(db, user.user_id, from_g)
        if not esl:
            return {"success": False, "message": "محل خدمت مؤثر یافت نشد"}
        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        dest_city = validate_destination_city(db, destination_city_id)
        if not origin_city or not dest_city:
            return {"success": False, "message": "شهر مبدأ یا مقصد نامعتبر است"}

        distance_km = calculate_distance(policy, origin_city, dest_city)
        from models.travel_leave_policy_rules import TravelLeavePolicyRule
        rules = db.query(TravelLeavePolicyRule).filter(
            TravelLeavePolicyRule.policy_id == policy.id,
            TravelLeavePolicyRule.is_active == 1,
        ).all()
        travel_days, _ = calculate_travel_days(distance_km, rules)
        jalali_year = jdatetime.date.fromgregorian(date=from_g).year
        allowed, used, max_allowed = check_quota(
            db, user.user_id, jalali_year, policy, employee.marital_status, from_g
        )
        return {
            "success": True,
            "origin_city": origin_city.name,
            "destination_city": dest_city.name,
            "destination_province": dest_city.province or "",
            "distance_km": distance_km,
            "travel_days": travel_days,
            "eligible": policy.is_enabled and travel_days > 0 and allowed,
            "quota_used": used,
            "quota_max": max_allowed,
            "quota_allowed": allowed,
            "jalali_year": jalali_year,
            "distance_method": policy.distance_method,
            "contract_type_code": contract.contract_type_code,
            "marital_status": employee.marital_status,
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}
