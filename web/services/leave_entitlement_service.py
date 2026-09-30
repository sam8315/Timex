"""
Resolve annual leave entitlement from leave policy + membership + region,
and compute membership-aware charge amounts per Jalali year.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

import jdatetime
from sqlalchemy.orm import Session

from models.contract import CONTRACT_TYPES, Contract
from models.employee import Employee
from models.leave_glossary import (
    MEMBERSHIP_CONSCRIPT,
    MEMBERSHIP_PERMANENT,
    MEMBERSHIP_PHYSICIAN,
    MEMBERSHIP_PRORATE_BY_CONTRACT,
    POLICY_MEMBERSHIP_CODES,
)
from models.policy import Policy, PolicyValue
from models.region import Region

logger = logging.getLogger(__name__)

DEPT_DEFAULT_ANNUAL = 30


def get_jalali_year_days(year: int) -> int:
    try:
        jdatetime.date(year, 12, 30)
        return 366
    except ValueError:
        return 365


def jalali_year_bounds_g(year: int) -> Tuple[date, date]:
    start_j = jdatetime.date(year, 1, 1)
    try:
        end_j = jdatetime.date(year, 12, 30)
    except ValueError:
        end_j = jdatetime.date(year, 12, 29)
    return start_j.togregorian(), end_j.togregorian()


def _get_leave_policy(db: Session) -> Optional[Policy]:
    return db.query(Policy).filter(Policy.category == 'leave').first()


def _get_policy_param(
    db: Session,
    policy_id: int,
    key: str,
    region_code: Optional[str] = None,
) -> Optional[PolicyValue]:
    query = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy_id,
        PolicyValue.parameter_key == key,
    )
    if region_code is None:
        query = query.filter(PolicyValue.region_code.is_(None))
    else:
        query = query.filter(PolicyValue.region_code == region_code)
    return query.first()


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def resolve_membership_code_for_policy(contract_type_code: str) -> str:
    """Map contract type 6/7 onto policy dept keys (fallback to 4=قراردادی)."""
    if contract_type_code in POLICY_MEMBERSHIP_CODES:
        return contract_type_code
    return '4'


def resolve_annual_leave_days(
    db: Session,
    membership_code: str,
    region_code: Optional[str] = None,
) -> int:
    """
    استحقاق سالانه از سیاست عضویت (+ منطقه فقط اگر flag صریحاً true باشد).

    Fallback: DEPT_DEFAULT_ANNUAL (نه CONTRACT_TYPES).
    """
    policy_code = resolve_membership_code_for_policy(membership_code)

    policy = _get_leave_policy(db)
    if not policy:
        return DEPT_DEFAULT_ANNUAL

    annual_pv = _get_policy_param(db, policy.id, f'annual_leave_dept_{policy_code}')
    annual = _parse_int(
        annual_pv.parameter_value if annual_pv else None,
        DEPT_DEFAULT_ANNUAL,
    )

    region_flag_pv = _get_policy_param(
        db, policy.id, f'region_applies_dept_{policy_code}'
    )
    # هم‌خوان با UI سیاست مرخصی: پیش‌فرض اعمال منطقه؛ فقط با false صریح خاموش
    if region_flag_pv is None:
        region_applies = True
    else:
        region_applies = region_flag_pv.parameter_value not in (
            'false', '0', 'off', '',
        )

    if region_applies and region_code:
        region = db.query(Region).filter(Region.code == region_code).first()
        if region is not None:
            region_days = int(region.default_annual_leave_days)
            scoped = _get_policy_param(
                db, policy.id, 'annual_leave_days', region_code=region_code
            )
            if scoped:
                region_days = _parse_int(scoped.parameter_value, region_days)
            annual = region_days

    return max(0, annual)


def resolve_annual_for_employee_contract(
    db: Session,
    employee: Optional[Employee],
    contract: Contract,
) -> int:
    region_code = employee.region_code if employee else None
    return resolve_annual_leave_days(
        db,
        contract.contract_type_code,
        region_code=region_code,
    )


def contract_effective_end(contract: Contract) -> Optional[date]:
    """پایان مؤثر با احتساب کسر خدمت (وظیفه)."""
    return contract.actual_end_date


def split_contract_coverage_by_year(
    contract: Contract,
) -> List[Tuple[int, date, Optional[date]]]:
    """
    تقسیم پوشش قرارداد بر سال شمسی با توجه به نوع عضویت.

    - رسمی: پایان قرارداد نادیده گرفته می‌شود → از start تا پایان سال شروع
      (یا سال‌های بین start و امروز/سال جاری برای قرارداد باز فقط سال شروع در رویداد شارژ)
    - وظیفه: تا actual_end_date
    - قراردادی و مشابه: تا end_date قرارداد
    """
    code = contract.contract_type_code
    start_g = contract.start_date
    start_j = jdatetime.date.fromgregorian(date=start_g)

    if code == MEMBERSHIP_PERMANENT:
        # رسمی: فقط سال شمسی شروع شارژ می‌شود (حتی اگر end_date سی‌ساله باشد)
        _, year_end = jalali_year_bounds_g(start_j.year)
        return [(start_j.year, start_g, year_end)]

    # وظیفه: actual_end_date
    if code == MEMBERSHIP_CONSCRIPT:
        end_g = contract_effective_end(contract)
        if end_g is None:
            _, year_end = jalali_year_bounds_g(start_j.year)
            return [(start_j.year, start_g, year_end)]
        if end_g < start_g:
            return []
        end_j = jdatetime.date.fromgregorian(date=end_g)
        segments = []
        for year in range(start_j.year, end_j.year + 1):
            y_start, y_end = jalali_year_bounds_g(year)
            seg_start = max(start_g, y_start)
            seg_end = min(end_g, y_end)
            if seg_start <= seg_end:
                segments.append((year, seg_start, seg_end))
        return segments

    # قراردادی / خریدخدمت / سایر / بیمه / پزشک
    if contract.end_date is None:
        _, year_end = jalali_year_bounds_g(start_j.year)
        return [(start_j.year, start_g, year_end)]

    end_g = contract.end_date
    if end_g < start_g:
        return []
    end_j = jdatetime.date.fromgregorian(date=end_g)
    segments = []
    for year in range(start_j.year, end_j.year + 1):
        y_start, y_end = jalali_year_bounds_g(year)
        seg_start = max(start_g, y_start)
        seg_end = min(end_g, y_end)
        if seg_start <= seg_end:
            segments.append((year, seg_start, seg_end))
    return segments


def charge_amount_for_segment(
    membership_code: str,
    annual_days: float,
    year_j: int,
    seg_start: date,
    seg_end: Optional[date],
) -> float:
    """محاسبه مقدار شارژ AL برای یک سگمنت سال."""
    year_days = get_jalali_year_days(year_j)
    y_start, y_end = jalali_year_bounds_g(year_j)

    if seg_end is None:
        seg_end = y_end

    # clamp to year
    start = max(seg_start, y_start)
    end = min(seg_end, y_end)
    if end < start:
        return 0.0

    duration = (end - start).days + 1

    if membership_code == MEMBERSHIP_PERMANENT:
        # رسمی: اگر از اول سال (یا کل سال) پوشش دارد → کامل؛
        # اگر وسط سال عضو شده → تناسب از شروع عضویت تا پایان سال
        if start <= y_start and end >= y_end:
            return float(annual_days)
        return float(annual_days) * (duration / year_days)

    if membership_code == MEMBERSHIP_PHYSICIAN:
        if duration >= year_days:
            return float(annual_days)
        return float(annual_days) * (duration / year_days)

    # قراردادی و وظیفه و سایر: تناسب مدت پوشش
    if duration >= year_days:
        return float(annual_days)
    return float(annual_days) * (duration / year_days)


def calculate_entitlement_by_year(
    db: Session,
    contract: Contract,
    employee: Optional[Employee] = None,
    annual_override: Optional[int] = None,
) -> Dict[int, Dict[str, float]]:
    """
    محاسبه AL (و SL از فیلد قرارداد) به تفکیک سال شمسی با قواعد عضویت.

    Returns: {year: {'AL': float, 'SL': float}}
    """
    if employee is None:
        employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()

    annual = (
        annual_override
        if annual_override is not None
        else resolve_annual_for_employee_contract(db, employee, contract)
    )
    sick = float(contract.sick_leave_days or 0)
    code = contract.contract_type_code
    segments = split_contract_coverage_by_year(contract)
    result: Dict[int, Dict[str, float]] = {}

    for year_j, seg_start, seg_end in segments:
        al = charge_amount_for_segment(code, annual, year_j, seg_start, seg_end)
        # SL: همان تناسب زمانی برای غیررسمی؛ برای رسمی مثل AL
        sl = charge_amount_for_segment(code, sick, year_j, seg_start, seg_end)
        if year_j not in result:
            result[year_j] = {'AL': 0.0, 'SL': 0.0}
        result[year_j]['AL'] += al
        result[year_j]['SL'] += sl
        logger.info(
            "Entitlement contract=%s type=%s year=%s AL=%.2f SL=%.2f "
            "seg=%s..%s annual_base=%s",
            contract.id, code, year_j, al, sl, seg_start, seg_end, annual,
        )

    return result


def get_membership_timeline(db: Session, user_id: str) -> List[dict]:
    """تایم‌لاین سیکل عضویت از قراردادها (مرتب بر اساس شروع)."""
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.asc())
        .all()
    )
    timeline = []
    for c in contracts:
        start_j = jdatetime.date.fromgregorian(date=c.start_date)
        end = c.actual_end_date
        end_j = jdatetime.date.fromgregorian(date=end) if end else None
        timeline.append({
            'contract_id': c.id,
            'contract_type_code': c.contract_type_code,
            'contract_type_name': c.contract_type_name,
            'start_date': c.start_date,
            'end_date': c.end_date,
            'actual_end_date': end,
            'start_j': start_j.strftime('%Y/%m/%d'),
            'end_j': end_j.strftime('%Y/%m/%d') if end_j else 'دائمی',
            'is_active': c.is_active,
            'annual_leave_days': c.annual_leave_days,
            'service_deduction_days': c.service_deduction_days,
        })
    return timeline


def sync_employee_department_from_active_contract(
    db: Session,
    user_id: str,
    commit: bool = False,
) -> Optional[str]:
    """
    هم‌ترازی Employee.department با عضویت مؤثر:
    1) قرارداد فعال امروز
    2) در غیر این صورت آخرین رکورد بر اساس start_date
    """
    today = date.today()
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.desc())
        .all()
    )
    if not contracts:
        return None

    chosen = None
    for c in contracts:
        if c.start_date <= today and c.is_active:
            chosen = c
            break
    if chosen is None:
        chosen = contracts[0]  # آخرین بر اساس start_date

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if not employee:
        return None

    code = chosen.contract_type_code
    dept = code if code in POLICY_MEMBERSHIP_CODES else resolve_membership_code_for_policy(code)
    if employee.department != dept:
        employee.department = dept
        if commit:
            db.commit()
    return dept


DEFAULT_REGION_CODE = 'NORMAL'


def resolve_region_code_from_service_location(
    db: Session,
    user_id: str,
    effective_date: Optional[date] = None,
) -> str:
    """منطقه خدمتی مشتق از شهر محل خدمت مؤثر؛ بدون محل خدمت → NORMAL."""
    from models.city import City
    from web.services.travel_leave_service import resolve_effective_service_location

    on_date = effective_date or date.today()
    esl = resolve_effective_service_location(db, user_id, on_date)
    if not esl:
        return DEFAULT_REGION_CODE
    city = db.query(City).filter(City.id == esl.city_id).first()
    if not city or not city.region_code:
        return DEFAULT_REGION_CODE
    return city.region_code


def sync_employee_region_from_service_location(
    db: Session,
    user_id: str,
    *,
    commit: bool = False,
    approved_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """
    هم‌ترازی Employee.region_code با منطقهٔ شهر محل خدمت مؤثر امروز.
    در صورت تغییر: بستن تاریخچه باز و درج EmployeeRegion جدید.
    """
    from models.employee_region import EmployeeRegion

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if not employee:
        return DEFAULT_REGION_CODE

    today = date.today()
    new_region = resolve_region_code_from_service_location(db, user_id, today)
    old_region = employee.region_code or DEFAULT_REGION_CODE

    if old_region == new_region:
        if commit:
            db.commit()
        return new_region

    employee.region_code = new_region

    open_rows = (
        db.query(EmployeeRegion)
        .filter(
            EmployeeRegion.user_id == user_id,
            EmployeeRegion.effective_to.is_(None),
        )
        .all()
    )
    for row in open_rows:
        row.effective_to = today

    db.add(EmployeeRegion(
        user_id=user_id,
        region_code=new_region,
        effective_from=today,
        approved_by=approved_by,
        reason=reason or f"همگام‌سازی از محل خدمت (قبلی: {old_region})",
    ))

    if commit:
        db.commit()
    return new_region


def sync_employees_for_city(
    db: Session,
    city_id: int,
    *,
    commit: bool = False,
    approved_by: Optional[str] = None,
) -> int:
    """همگام‌سازی منطقه برای همهٔ کارمندانی که محل خدمت مؤثرشان این شهر است."""
    from models.employee_service_location import EmployeeServiceLocation
    from sqlalchemy import or_

    today = date.today()
    locs = (
        db.query(EmployeeServiceLocation)
        .filter(
            EmployeeServiceLocation.city_id == city_id,
            EmployeeServiceLocation.effective_from <= today,
            or_(
                EmployeeServiceLocation.effective_to.is_(None),
                EmployeeServiceLocation.effective_to > today,
            ),
        )
        .all()
    )
    user_ids = {loc.user_id for loc in locs}
    for uid in user_ids:
        sync_employee_region_from_service_location(
            db,
            uid,
            commit=False,
            approved_by=approved_by,
            reason="همگام‌سازی پس از تغییر منطقه شهر",
        )
    if commit and user_ids:
        db.commit()
    return len(user_ids)


def add_years(d: date, years: int) -> date:
    """افزودن سال به تاریخ میلادی با مراقبت از ۲۹ فوریه."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def find_overlapping_contract(
    db: Session,
    user_id: str,
    start_date: date,
    end_date: Optional[date],
    exclude_id: Optional[int] = None,
) -> Optional[Contract]:
    """
    یافتن قرارداد هم‌پوشان برای همان کاربر.
    end_date=None به‌معنی بازه‌ی باز (بی‌نهایت) است.
    """
    others = db.query(Contract).filter(Contract.user_id == user_id).all()
    new_end = end_date  # None = open

    for other in others:
        if exclude_id is not None and other.id == exclude_id:
            continue
        other_end = other.actual_end_date  # respects service deduction
        # overlap if new_start <= other_end AND new_end >= other_start
        if other_end is not None and start_date > other_end:
            continue
        if new_end is not None and new_end < other.start_date:
            continue
        return other
    return None

