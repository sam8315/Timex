"""
صفحه درخواست مرخصی کاربر
"""
from datetime import date, timedelta, datetime as dt_datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import jdatetime
from typing import Optional

from datetime import time as time_type
from web.dependencies import get_db, get_current_user, check_password_change
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.contract import Contract
from fastapi import Query
from models.holiday import Holiday
from web.services.hourly_leave_service import (
    validate_hourly_leave_request,
    compute_requested_minutes,
)
from web.services.travel_leave_service import (
    get_active_cities,
    resolve_effective_service_location,
    validate_destination_city,
    calculate_distance_km as calc_dist,
    calculate_travel_days,
    check_quota,
    get_quota_setting,
)
from models.city import City
from models.travel_leave_policy_rules import TravelLeavePolicyRule

router = APIRouter(tags=["Leave"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# انواع مرخصی مجاز برای درخواست
LEAVE_TYPES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'CW': 'ذخیره سال قبل',
    'HL': 'ساعتی',
}

CONDITIONAL_LEAVE_TYPES = {'RL', 'CW'}

STATUS_NAMES = {
    'P': '⏳ در انتظار',
    'A': '✅ تایید شده',
    'R': '❌ رد شده',
    'D': '🗑️ حذف شده',
}


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def calculate_leave_days(db: Session, user_id: str, from_date: date, to_date: date) -> int:
    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    user_group = employee.department if employee else None
    days = 0
    current = from_date
    while current <= to_date:
        holiday = db.query(Holiday).filter(Holiday.holiday_date == current).first()
        is_holiday_for_user = False
        if holiday and (holiday.group_id is None or holiday.group_id == user_group):
            is_holiday_for_user = True
        is_friday = current.weekday() == 4
        if not is_holiday_for_user and not is_friday:
            days += 1
        current += timedelta(days=1)
    return days


def get_user_leave_balance(db: Session, user_id: str, year: int) -> dict:
    balances = db.query(LeaveBalance).filter(
        and_(LeaveBalance.user_id == user_id, LeaveBalance.year == year)
    ).all()
    return {b.leave_type: b.balance for b in balances}


@router.get("/leave", response_class=HTMLResponse)
async def leave_page(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today_j = jdatetime.date.today()
    current_year = today_j.year
    balances = get_user_leave_balance(db, user.user_id, current_year)

    available_leave_types = {}
    for code, name in LEAVE_TYPES.items():
        if code in CONDITIONAL_LEAVE_TYPES:
            if balances.get(code, 0) > 0:
                available_leave_types[code] = name
        else:
            available_leave_types[code] = name

    recent_requests_raw = db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.user_id
    ).order_by(LeaveRequest.created_at.desc()).limit(20).all()

    recent_requests = []
    for req in recent_requests_raw:
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)
        req_data = {
            'id': req.id,
            'leave_type': req.leave_type,
            'leave_type_name': LEAVE_TYPES.get(req.leave_type, req.leave_type),
            'from_date_j': j_from.strftime('%Y/%m/%d'),
            'to_date_j': j_to.strftime('%Y/%m/%d'),
            'days_count': req.days_count,
            'reason': req.reason,
            'status': req.status,
            'status_name': STATUS_NAMES.get(req.status, req.status),
            'rejection_reason': req.rejection_reason,
            'created_at': req.created_at.strftime('%Y/%m/%d %H:%M') if req.created_at else '',
        }
        if req.leave_type == 'HL':
            req_data['start_time'] = req.start_time.strftime('%H:%M') if req.start_time else ''
            req_data['end_time'] = req.end_time.strftime('%H:%M') if req.end_time else ''
            req_data['minutes'] = compute_requested_minutes(req.start_time, req.end_time) if req.start_time and req.end_time else 0
        tl = getattr(req, 'travel_leave_detail', None)
        if tl:
            req_data['has_travel_leave'] = True
            req_data['tl_origin'] = tl.origin_city_name_snapshot or '-'
            req_data['tl_destination'] = tl.destination_city_name_snapshot
            req_data['tl_distance'] = tl.distance_km
            req_data['tl_final_days'] = tl.final_travel_days
        recent_requests.append(req_data)

    pending_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'P')
    ).count()
    approved_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'A')
    ).count()
    rejected_count = db.query(LeaveRequest).filter(
        and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status == 'R')
    ).count()

    # Resolve the effective policy using Employee (policy resolution expects Employee, not User).
    hl_granularity = 15
    hl_min_request = 15
    employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()
    if employee:
        try:
            from web.services.hourly_leave_service import resolve_hourly_leave_policy
            hl_policy = resolve_hourly_leave_policy(db, employee, date.today())
            if hl_policy:
                if hl_policy.granularity_minutes is not None:
                    hl_granularity = hl_policy.granularity_minutes
                if hl_policy.min_request_minutes is not None:
                    hl_min_request = hl_policy.min_request_minutes
        except Exception:
            pass

    # Travel Leave context
    cities = get_active_cities(db)
    cities_list = [{'id': c.id, 'name': c.name, 'province': c.province} for c in cities]

    # Resolve effective service location for display.
    # This value is only a display/enablement hint; the authoritative preview resolves
    # the service location again using the selected leave date.
    service_origin_city = None
    esl = resolve_effective_service_location(db, user.user_id, date.today())
    if esl:
        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        if origin_city:
            service_origin_city = origin_city.name
    if not service_origin_city:
        service_origin_city = "برای تاریخ انتخابی بررسی می‌شود"

    # Travel Leave quota
    today_j_year = jdatetime.date.today().year
    tl_allowed, tl_used, tl_max = check_quota(db, user.user_id, today_j_year)

    return templates.TemplateResponse(request, "leave.html", {
        "user": user,
        "today_j": today_j.strftime('%Y/%m/%d'),
        "current_year": current_year,
        "balances": balances,
        "al_balance": balances.get('AL', 0),
        "sl_balance": balances.get('SL', 0),
        "rl_balance": balances.get('RL', 0),
        "cw_balance": balances.get('CW', 0),
        "recent_requests": recent_requests,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "leave_types": available_leave_types,
        "is_admin": user.is_admin,
        "hl_granularity": hl_granularity,
        "hl_min_request": hl_min_request,
        "cities": cities_list,
        "service_origin_city": service_origin_city,
        "tl_quota_allowed": tl_allowed,
        "tl_quota_used": tl_used,
        "tl_quota_max": tl_max,
    })


@router.post("/leave/request")
async def submit_leave_request(
    request: Request,
    leave_type: str = Form(...),
    from_date_str: str = Form(...),
    to_date_str: str = Form(...),
    start_time_str: str = Form(""),
    end_time_str: str = Form(""),
    reason: str = Form(""),
    travel_leave_enabled: str = Form("off"),
    destination_city_id: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if leave_type not in LEAVE_TYPES:
            raise ValueError("نوع مرخصی نامعتبر است")
        from_j = jdatetime.datetime.strptime(from_date_str.strip(), "%Y/%m/%d").date()
        to_j = jdatetime.datetime.strptime(to_date_str.strip(), "%Y/%m/%d").date()
        from_date = from_j.togregorian()
        to_date = to_j.togregorian()
        if from_date > to_date:
            raise ValueError("تاریخ شروع باید قبل یا مساوی تاریخ پایان باشد")
        if from_date < date.today():
            raise ValueError("تاریخ شروع نمی‌تواند در گذشته باشد")
        hl_start_time = None
        hl_end_time = None
        if leave_type == 'HL':
            if from_date != to_date:
                raise ValueError("مرخصی ساعتی فقط برای یک روز امکان‌پذیر است")
            if not start_time_str or not end_time_str:
                raise ValueError("ساعت شروع و پایان برای مرخصی ساعتی الزامی است")
            try:
                hl_start_time = dt_datetime.strptime(start_time_str.strip(), "%H:%M").time()
                hl_end_time = dt_datetime.strptime(end_time_str.strip(), "%H:%M").time()
            except ValueError:
                raise ValueError("فرمت ساعت نامعتبر است (HH:MM)")
            employee = db.query(Employee).filter(Employee.user_id == user.user_id).first()
            if not employee:
                raise ValueError("کارمند یافت نشد")
            is_valid, error_msg = validate_hourly_leave_request(db, employee, from_date, hl_start_time, hl_end_time)
            if not is_valid:
                raise ValueError(error_msg or "درخواست نامعتبر است")
            days_count = 0
        else:
            if (to_date - from_date).days > 30:
                raise ValueError("حداکثر بازه مرخصی ۳۰ روز است")
            days_count = calculate_leave_days(db, user.user_id, from_date, to_date)
            if days_count <= 0:
                raise ValueError("در بازه انتخابی، هیچ روز کاری وجود ندارد (همه تعطیل هستند)")
            balance = db.query(LeaveBalance).filter(and_(LeaveBalance.user_id == user.user_id, LeaveBalance.year == from_j.year, LeaveBalance.leave_type == leave_type)).first()
            current_balance = balance.balance if balance else 0
            if current_balance < days_count:
                type_name = LEAVE_TYPES.get(leave_type, '')
                raise ValueError(f"مانده کافی نیست! مانده {type_name}: {current_balance} روز، درخواست: {days_count} روز")

        if leave_type != 'HL':
            overlapping = db.query(LeaveRequest).filter(and_(LeaveRequest.user_id == user.user_id, LeaveRequest.status.in_(['P', 'A']), LeaveRequest.from_date <= to_date, LeaveRequest.to_date >= from_date)).first()
            if overlapping:
                raise ValueError("در این بازه، درخواست مرخصی دیگری دارید")

        # Validate travel leave request
        tl_enabled = travel_leave_enabled == "on" and leave_type == "AL"
        tl_dest_city_id = None
        if tl_enabled:
            if not destination_city_id or not destination_city_id.strip():
                raise ValueError("شهر مقصد برای مرخصی توراهی الزامی است")
            try:
                tl_dest_city_id = int(destination_city_id.strip())
            except (ValueError, TypeError):
                raise ValueError("شهر مقصد نامعتبر است")

        new_request = LeaveRequest(
            user_id=user.user_id,
            leave_type=leave_type,
            from_date=from_date,
            to_date=to_date,
            days_count=days_count,
            reason=reason.strip() or None,
            status='P',
            start_time=hl_start_time,
            end_time=hl_end_time,
        )
        db.add(new_request)
        db.flush()

        # Create Travel Leave detail atomically
        if tl_enabled:
            from web.services.travel_leave_service import create_travel_leave_detail
            try:
                create_travel_leave_detail(db, new_request, tl_dest_city_id)
            except ValueError as te:
                db.rollback()
                return RedirectResponse(
                    url=build_redirect_url(request.headers.get("referer", "/leave"), "error", str(te)),
                    status_code=302,
                )

        db.commit()
        type_name = LEAVE_TYPES.get(leave_type, '')
        referer = request.headers.get("referer", "/leave")
        if leave_type == 'HL':
            minutes = compute_requested_minutes(hl_start_time, hl_end_time)
            return RedirectResponse(url=build_redirect_url(referer, "success", f"درخواست مرخصی {type_name} ({minutes // 60}:{minutes % 60:02d} ساعت) با موفقیت ثبت شد"), status_code=302)

        tl_msg = " + مرخصی توراهی" if tl_enabled else ""
        return RedirectResponse(url=build_redirect_url(referer, "success", f"درخواست مرخصی {type_name} ({days_count} روز){tl_msg} با موفقیت ثبت شد"), status_code=302)
    except ValueError as e:
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "error", str(e)), status_code=302)
    except Exception as e:
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "error", f"خطا: {str(e)}"), status_code=302)


@router.post("/leave/request/{request_id}/cancel")
async def cancel_leave_request(request: Request, request_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    leave_req = db.query(LeaveRequest).filter(and_(LeaveRequest.id == request_id, LeaveRequest.user_id == user.user_id)).first()
    if not leave_req:
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "error", "درخواست یافت نشد"), status_code=302)
    if leave_req.status != 'P':
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "error", "فقط درخواست‌های در انتظار قابل لغو هستند"), status_code=302)
    try:
        leave_req.status = 'R'
        leave_req.rejection_reason = "لغو شده توسط کاربر"
        db.commit()
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "success", "درخواست با موفقیت لغو شد"), status_code=302)
    except Exception as e:
        return RedirectResponse(url=build_redirect_url(request.headers.get("referer", "/leave"), "error", f"خطا: {str(e)}"), status_code=302)


@router.get("/leave/calculate-days")
async def calculate_leave_days_api(from_date: str = Query(...), to_date: str = Query(...), user: User = Depends(check_password_change), db: Session = Depends(get_db)):
    try:
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        to_j = jdatetime.datetime.strptime(to_date.strip(), "%Y/%m/%d").date()
        from_g = from_j.togregorian()
        to_g = to_j.togregorian()
        if from_g > to_g:
            return {"success": False, "days_count": 0, "message": "تاریخ شروع باید قبل از پایان باشد"}
        days_count = 0
        current = from_g
        while current <= to_g:
            if current.weekday() == 4:
                current += timedelta(days=1)
                continue
            holiday = db.query(Holiday).filter(Holiday.holiday_date == current).first()
            if holiday:
                current += timedelta(days=1)
                continue
            days_count += 1
            current += timedelta(days=1)
        return {"success": True, "days_count": days_count}
    except Exception as e:
        return {"success": False, "days_count": 0, "message": str(e)}


@router.get("/leave/travel-preview")
async def travel_leave_preview(
    from_date: str = Query(...),
    destination_city_id: int = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Advisory preview for Travel Leave. Not authoritative — submission recalculates."""
    try:
        from_j = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
        from_g = from_j.togregorian()

        # Resolve origin
        esl = resolve_effective_service_location(db, user.user_id, from_g)
        if not esl:
            return {"success": False, "message": "محل خدمت مؤثر یافت نشد"}

        origin_city = db.query(City).filter(City.id == esl.city_id).first()
        if not origin_city:
            return {"success": False, "message": "شهر محل خدمت یافت نشد"}

        dest_city = validate_destination_city(db, destination_city_id)
        if not dest_city:
            return {"success": False, "message": "شهر مقصد نامعتبر است"}

        distance_km = calc_dist(
            (origin_city.latitude, origin_city.longitude),
            (dest_city.latitude, dest_city.longitude),
        )
        distance_km = round(distance_km, 2)

        rules = db.query(TravelLeavePolicyRule).filter(
            TravelLeavePolicyRule.is_active == 1
        ).all()
        travel_days, matched_rule = calculate_travel_days(distance_km, rules)

        jalali_year = jdatetime.date.fromgregorian(date=from_g).year
        allowed, used, max_allowed = check_quota(db, user.user_id, jalali_year)

        return {
            "success": True,
            "origin_city": origin_city.name,
            "destination_city": dest_city.name,
            "destination_province": dest_city.province or "",
            "distance_km": distance_km,
            "travel_days": travel_days,
            "eligible": travel_days > 0,
            "message": (
                f"فاصله {distance_km} کیلومتر — {travel_days} روز توراهی"
                if travel_days > 0 else
                (f"فاصله {distance_km} کیلومتر است. مرخصی توراهی برای این مسیر قابل استفاده نیست (کمتر از ۲۰۰ کیلومتر)."
                 if distance_km < 200 else
                 f"فاصله {distance_km} کیلومتر — مرخصی توراهی برای این مسیر قابل استفاده نیست (خارج از محدوده مجاز).")
            ),
            "quota_used": used,
            "quota_max": max_allowed,
            "quota_allowed": allowed,
            "jalali_year": jalali_year,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
