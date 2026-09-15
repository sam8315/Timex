"""Authoritative admin Travel Leave preview using the effective policy."""
import jdatetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from models.city import City
from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from web.services.travel_leave_service import (
    calculate_distance,
    calculate_travel_days,
    check_quota,
    resolve_effective_service_location,
    resolve_policy,
    validate_destination_city,
)
from models.travel_leave_policy_rules import TravelLeavePolicyRule

router = APIRouter(tags=["Admin Leave"])


@router.get("/admin/leave-requests/travel-preview")
async def admin_travel_leave_preview(
    target_user_id: str = Query(...),
    from_date: str = Query(...),
    destination_city_id: int = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Use the exact same policy-scoped calculation as final Travel Leave creation."""
    enforce_permission(db, user, "approve_leave")
    try:
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        from_g = from_j.togregorian()

        policy, contract, employee = resolve_policy(db, target_user_id, from_g)
        if not employee:
            return {"success": False, "message": "اطلاعات کارمند برای کاربر یافت نشد", "travel_days": 0}
        if not contract:
            return {
                "success": False,
                "message": "عضویت/قرارداد مؤثر برای کاربر در تاریخ انتخاب‌شده یافت نشد",
                "travel_days": 0,
            }
        if not policy:
            return {
                "success": False,
                "message": f"سیاست مرخصی توراهی برای نوع عضویت {contract.contract_type_code} تعریف نشده است",
                "travel_days": 0,
            }
        if not policy.is_enabled:
            return {"success": False, "message": "مرخصی توراهی برای این نوع عضویت غیرفعال است", "travel_days": 0}
        if employee.marital_status not in ("S", "M"):
            return {"success": False, "message": "وضعیت تأهل کاربر معتبر نیست", "travel_days": 0}

        esl = resolve_effective_service_location(db, target_user_id, from_g)
        if not esl:
            return {"success": False, "message": "محل خدمت مؤثر در تاریخ انتخاب‌شده یافت نشد", "travel_days": 0}

        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        dest_city = validate_destination_city(db, destination_city_id)
        if not origin_city or not dest_city:
            return {"success": False, "message": "شهر مبدأ یا مقصد نامعتبر است", "travel_days": 0}

        distance_km = calculate_distance(policy, origin_city, dest_city)
        rules = db.query(TravelLeavePolicyRule).filter(
            TravelLeavePolicyRule.policy_id == policy.id,
            TravelLeavePolicyRule.is_active == 1,
        ).all()
        travel_days, _ = calculate_travel_days(distance_km, rules)

        jalali_year = jdatetime.date.fromgregorian(date=from_g).year
        allowed, used, max_allowed = check_quota(
            db,
            target_user_id,
            jalali_year,
            policy,
            employee.marital_status,
            from_g,
        )

        eligible = travel_days > 0 and allowed
        message = None
        if not rules:
            message = "قواعد فاصله برای این نوع عضویت تعریف نشده است"
        elif travel_days <= 0:
            message = "مسافت انتخاب‌شده مشمول مرخصی توراهی نیست"
        elif not allowed:
            message = f"سهمیه سالانه تکمیل شده است ({used}/{max_allowed})"

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
        return {"success": False, "message": f"خطا در محاسبه مرخصی توراهی: {exc}", "travel_days": 0}
