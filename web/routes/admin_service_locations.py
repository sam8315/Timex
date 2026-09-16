"""
پنل مدیریت محل خدمت کارکنان (مرجع مبدأ مرخصی توراهی)
"""
from datetime import date
from typing import Optional
import jdatetime
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from web.services.travel_leave_service import (
    resolve_effective_service_location,
    service_location_overlaps,
)
from models.user import User
from models.employee import Employee
from models.city import City
from models.employee_service_location import EmployeeServiceLocation

router = APIRouter(tags=["Admin Service Locations"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def _parse_jalali_date(value: str, field_name: str) -> date:
    try:
        d = jdatetime.datetime.strptime(value.strip(), "%Y/%m/%d").date()
        if d.year < 1300:
            raise ValueError
        return d.togregorian()
    except (ValueError, AttributeError):
        raise ValueError(f"{field_name} نامعتبر است (فرمت: ۱۴۰۴/۰۵/۰۱)")


def _get_city_or_raise(db: Session, city_id: int) -> City:
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise ValueError("شهر انتخاب‌شده یافت نشد")
    if not city.is_active:
        raise ValueError("شهر انتخاب‌شده غیرفعال است")
    return city


def _cities_list(db: Session):
    return db.query(City).filter(City.is_active == True) \
        .order_by(City.province, City.name).all()


@router.get("/service-locations", response_class=HTMLResponse)
async def service_locations_page(
    request: Request,
    search: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """جستجوی کارمند و مشاهده محل خدمت فعلی/تاریخچه"""
    enforce_permission(db, user, 'manage_service_locations')

    search_term = (search or "").strip()
    employees = []
    if search_term:
        employees = (
            db.query(Employee)
            .filter(Employee.is_active == True)
            .filter((Employee.first_name.ilike(f"%{search_term}%") |
                     Employee.last_name.ilike(f"%{search_term}%") |
                     Employee.national_code.ilike(f"%{search_term}%")))
            .order_by(Employee.first_name, Employee.last_name)
            .limit(50)
            .all()
        )

    selected = None
    locations = []
    current_location = None
    current_city = None
    employees_list_for_select = (
        db.query(Employee).filter(Employee.is_active == True)
        .order_by(Employee.first_name, Employee.last_name).all()
    )

    if user_id:
        selected = db.query(Employee).filter(Employee.user_id == user_id).first()
        if selected:
            locations = (
                db.query(EmployeeServiceLocation)
                .filter(EmployeeServiceLocation.user_id == user_id)
                .order_by(EmployeeServiceLocation.effective_from.desc())
                .all()
            )
            current_location = resolve_effective_service_location(
                db, user_id, date.today()
            )
            if current_location:
                current_city = db.query(City).filter(
                    City.id == current_location.city_id).first()

    locations_data = []
    for loc in locations:
        city = db.query(City).filter(City.id == loc.city_id).first()
        locations_data.append({
            'location': loc,
            'city_name': city.name if city else 'نامشخص',
            'from_j': jdatetime.date.fromgregorian(date=loc.effective_from).strftime('%Y/%m/%d'),
            'to_j': (jdatetime.date.fromgregorian(date=loc.effective_to).strftime('%Y/%m/%d')
                     if loc.effective_to else None),
        })

    return templates.TemplateResponse(request, "admin/service_locations.html", {
        "user": user,
        "employees": employees,
        "selected": selected,
        "locations": locations_data,
        "current_location": current_location,
        "current_city": current_city,
        "cities": _cities_list(db),
        "employees_for_select": employees_list_for_select,
        "search": search_term,
        "is_admin": True,
    })


@router.post("/service-locations/add")
async def add_service_location(
    request: Request,
    user_id: str = Form(...),
    city_id: int = Form(...),
    address_text: str = Form(""),
    effective_from_str: str = Form(...),
    effective_to_str: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """درج محل خدمت جدید با رد تداخل بازه‌ها"""
    enforce_permission(db, user, 'manage_service_locations')
    referer = request.headers.get("referer", "/admin/service-locations")
    try:
        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            raise ValueError("کارمندی با این شناسه یافت نشد")

        city = _get_city_or_raise(db, city_id)
        from_date = _parse_jalali_date(effective_from_str, "تاریخ شروع")
        to_date = _parse_jalali_date(effective_to_str, "تاریخ پایان") if effective_to_str.strip() else None
        if to_date is not None and to_date <= from_date:
            raise ValueError("تاریخ پایان باید بعد از تاریخ شروع باشد")

        overlap = service_location_overlaps(db, user_id, from_date, to_date)
        if overlap:
            raise ValueError(
                "با محل خدمت موجود تداخل بازه زمانی دارد؛ ابتدا آن را پایان دهید"
            )

        loc = EmployeeServiceLocation(
            user_id=user_id,
            city_id=city.id,
            address_text=address_text.strip() or None,
            effective_from=from_date,
            effective_to=to_date,
            created_by=user.user_id,
        )
        db.add(loc)
        db.commit()

        return RedirectResponse(
            url=build_redirect_url(referer, "success",
                                   f"محل خدمت در شهر «{city.name}» برای {employee.full_name} ثبت شد"),
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(url=build_redirect_url(referer, "error", str(e)), status_code=302)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=build_redirect_url(referer, "error", f"خطا: {str(e)}"), status_code=302)


@router.post("/service-locations/{location_id}/edit")
async def edit_service_location(
    request: Request,
    location_id: int,
    city_id: int = Form(...),
    address_text: str = Form(""),
    effective_from_str: str = Form(...),
    effective_to_str: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """ویرایش محل خدمت در انتظار/آینده (بدون تغییر مصوب‌های تأییدشده)"""
    enforce_permission(db, user, 'manage_service_locations')
    referer = request.headers.get("referer", "/admin/service-locations")
    loc = db.query(EmployeeServiceLocation).filter(
        EmployeeServiceLocation.id == location_id).first()
    if not loc:
        return RedirectResponse(url=build_redirect_url(referer, "error", "محل خدمت یافت نشد"), status_code=302)
    try:
        city = _get_city_or_raise(db, city_id)
        from_date = _parse_jalali_date(effective_from_str, "تاریخ شروع")
        to_date = _parse_jalali_date(effective_to_str, "تاریخ پایان") if effective_to_str.strip() else None
        if to_date is not None and to_date <= from_date:
            raise ValueError("تاریخ پایان باید بعد از تاریخ شروع باشد")

        overlap = service_location_overlaps(
            db, loc.user_id, from_date, to_date, exclude_id=loc.id)
        if overlap:
            raise ValueError("با محل خدمت موجود دیگری تداخل بازه زمانی دارد")

        loc.city_id = city.id
        loc.address_text = address_text.strip() or None
        loc.effective_from = from_date
        loc.effective_to = to_date
        db.commit()

        return RedirectResponse(
            url=build_redirect_url(referer, "success", "محل خدمت به‌روزرسانی شد"),
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(url=build_redirect_url(referer, "error", str(e)), status_code=302)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=build_redirect_url(referer, "error", f"خطا: {str(e)}"), status_code=302)


@router.post("/service-locations/{location_id}/end")
async def end_service_location(
    request: Request,
    location_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """پایان دادن به محل خدمت باز (set effective_to = today)"""
    enforce_permission(db, user, 'manage_service_locations')
    referer = request.headers.get("referer", "/admin/service-locations")
    loc = db.query(EmployeeServiceLocation).filter(
        EmployeeServiceLocation.id == location_id).first()
    if not loc:
        return RedirectResponse(url=build_redirect_url(referer, "error", "محل خدمت یافت نشد"), status_code=302)
    if loc.effective_to is not None:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "این محل خدمت قبلاً پایان یافته است"),
            status_code=302,
        )
    # Never produce an inverted interval; an unstarted assignment ends at its
    # own start date (empty, never-effectual interval).
    loc.effective_to = max(date.today(), loc.effective_from)
    db.commit()
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "محل خدمت پایان یافت"),
        status_code=302
    )