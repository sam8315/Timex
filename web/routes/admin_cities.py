"""
پنل مدیریت شهرهای مرجع (مبدأ/مقصد مرخصی توراهی)
"""
import math
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
import jdatetime
from typing import Optional

from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission
from models.user import User
from models.city import City

router = APIRouter(tags=["Admin Cities"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def build_redirect_url(referer: str, key: str, value: str) -> str:
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def _parse_lat_lon(lat_str: str, lon_str: str) -> tuple[float, float]:
    try:
        lat = float(lat_str.strip())
        lon = float(lon_str.strip())
    except (ValueError, TypeError):
        raise ValueError("مختصات جغرافیایی باید عددی باشد")
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("مختصات جغرافیایی نمی‌تواند نامحدود (NaN/Inf) باشد")
    if not (-90 <= lat <= 90):
        raise ValueError("عرض جغرافیایی باید بین ۹۰- تا ۹۰+ باشد")
    if not (-180 <= lon <= 180):
        raise ValueError("طول جغرافیایی باید بین ۱۸۰- تا ۱۸۰+ باشد")
    return lat, lon


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("نام شهر الزامی است")
    if len(name) > 100:
        raise ValueError("نام شهر نباید بیشتر از ۱۰۰ کاراکتر باشد")
    return name


@router.get("/cities", response_class=HTMLResponse)
async def cities_page(
    request: Request,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """لیست شهرهای مرجع با جستجو و فیلتر وضعیت"""
    enforce_permission(db, user, 'manage_cities')
    search_term = (search or "").strip()

    has_filter = any([search_term, status_filter, show_all])

    cities_data = []
    if has_filter:
        query = db.query(City)
        if search_term:
            query = query.filter(or_(
                City.name.ilike(f"%{search_term}%"),
                City.province.ilike(f"%{search_term}%"),
            ))
        if status_filter == 'active':
            query = query.filter(City.is_active == True)
        elif status_filter == 'inactive':
            query = query.filter(City.is_active == False)

        cities = query.order_by(City.is_active.desc(), City.name).all()
        for c in cities:
            cities_data.append({
                'city': c,
                'created_j': jdatetime.datetime.fromgregorian(
                    datetime=c.created_at).strftime('%Y/%m/%d %H:%M') if c.created_at else '-',
            })

    return templates.TemplateResponse(request, "admin/cities.html", {
        "user": user,
        "cities": cities_data,
        "total_count": len(cities_data),
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search_term,
        "status_filter": status_filter or "",
        "is_admin": True,
    })


@router.post("/cities/add")
async def add_city(
    request: Request,
    name: str = Form(...),
    province: str = Form(""),
    latitude: str = Form(...),
    longitude: str = Form(...),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """افزودن شهر مرجع با اعتبارسنجی سمت سرور"""
    enforce_permission(db, user, 'manage_cities')
    referer = request.headers.get("referer", "/admin/cities")
    try:
        clean_name = _validate_name(name)
        clean_province = province.strip() or None
        lat, lon = _parse_lat_lon(latitude, longitude)

        # رد کردن شهر تکراری (نام + استان)
        duplicate_q = db.query(City).filter(func.lower(City.name) == clean_name.lower())
        if clean_province:
            duplicate_q = duplicate_q.filter(City.province == clean_province)
        else:
            duplicate_q = duplicate_q.filter(City.province.is_(None))
        if duplicate_q.first():
            raise ValueError("شهری با همین نام و استان قبلاً ثبت شده است")

        city = City(
            name=clean_name,
            province=clean_province,
            latitude=lat,
            longitude=lon,
            is_active=(is_active == "on"),
        )
        db.add(city)
        db.commit()

        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"شهر «{clean_name}» ثبت شد"),
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/cities/{city_id}/edit")
async def edit_city(
    request: Request,
    city_id: int,
    name: str = Form(...),
    province: str = Form(""),
    latitude: str = Form(...),
    longitude: str = Form(...),
    is_active: str = Form("on"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ویرایش شهر مرجع (فقط شهر؛ اسنپ‌شات‌های تاریخی تغییر نمی‌کنند)"""
    enforce_permission(db, user, 'manage_cities')
    referer = request.headers.get("referer", "/admin/cities")
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "شهر یافت نشد"),
            status_code=302
        )
    try:
        clean_name = _validate_name(name)
        clean_province = province.strip() or None
        lat, lon = _parse_lat_lon(latitude, longitude)

        # رد کردن شهر تکراری (به جز خود شهر)
        duplicate_q = db.query(City).filter(
            func.lower(City.name) == clean_name.lower(),
            City.id != city_id
        )
        if clean_province:
            duplicate_q = duplicate_q.filter(City.province == clean_province)
        else:
            duplicate_q = duplicate_q.filter(City.province.is_(None))
        if duplicate_q.first():
            raise ValueError("شهری با همین نام و استان قبلاً ثبت شده است")

        city.name = clean_name
        city.province = clean_province
        city.latitude = lat
        city.longitude = lon
        city.is_active = (is_active == "on")
        db.commit()

        return RedirectResponse(
            url=build_redirect_url(referer, "success", f"شهر «{clean_name}» به‌روزرسانی شد"),
            status_code=302
        )
    except ValueError as e:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/cities/{city_id}/toggle")
async def toggle_city(
    request: Request,
    city_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """فعال/غیرفعال کردن شهر (بدون حذف فیزیکی)"""
    enforce_permission(db, user, 'manage_cities')
    referer = request.headers.get("referer", "/admin/cities")
    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "شهر یافت نشد"),
            status_code=302
        )
    city.is_active = not city.is_active
    db.commit()
    state = "فعال" if city.is_active else "غیرفعال"
    return RedirectResponse(
        url=build_redirect_url(referer, "success", f"شهر «{city.name}» {state} شد"),
        status_code=302
    )