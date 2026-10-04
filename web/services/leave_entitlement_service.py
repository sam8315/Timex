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

from models.contract import Contract
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
    """Identity: هر کد عضویت کلید Policy مستقل خود را دارد (بدون remap)."""
    code = str(contract_type_code or '').strip()
    if code in POLICY_MEMBERSHIP_CODES:
        return code
    # Unknown codes stay as-is; callers/FK validation handle orphans.
    return code or '4'


def _parse_buyback_cap(raw: Optional[str]) -> Optional[int]:
    """
    سقف بازخرید از رشته سیاست.
    None / empty / 'none' / '-1' / 'unlimited' → نامحدود (همه CW قابل‌بازخرید).
    """
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ('', 'none', 'null', '-1', 'unlimited'):
        return None
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return None


DEFAULT_BUYBACK_BY_REGION = {
    'NORMAL': 15,
    'GRADE_2': 18,
    'GRADE_3': 20,
    'GRADE_4': 22,
}

ARTICLE11_REGION_DISPLAY_NAMES = {
    'NORMAL': 'عادی',
    'GRADE_2': 'درجه دو',
    'GRADE_3': 'درجه سه',
    'GRADE_4': 'درجه چهار',
}

DEFAULT_ERA_PRE_1390 = 'none'
DEFAULT_ERA_1390_1398 = 15
DEFAULT_ERA_GRADE4_FROM = '1391/07/15'
DEFAULT_ERA_GRADE4_CAP = 25
DEFAULT_ERA_MODERN_FROM = 1399


def default_buyback_cap_for_membership(membership_code: str) -> Optional[int]:
    """پیش‌فرض بدون رکورد سیاست: غیررسمی نامحدود؛ رسمی ۱۵."""
    code = resolve_membership_code_for_policy(membership_code)
    if code in MEMBERSHIP_PRORATE_BY_CONTRACT or code == MEMBERSHIP_PHYSICIAN:
        return None
    if code == MEMBERSHIP_CONSCRIPT:
        return None
    if code == MEMBERSHIP_PERMANENT:
        return 15
    return None


def resolve_max_carry_forward(db: Session, membership_code: str) -> Optional[int]:
    """
    سقف انتقال مرخصی به سال بعد برای نوع عضویت.
    None = بدون سقف (همه مانده قابل‌انتقال).
    """
    policy_code = resolve_membership_code_for_policy(membership_code)
    policy = _get_leave_policy(db)
    if policy:
        dept_pv = _get_policy_param(db, policy.id, f'carry_forward_dept_{policy_code}')
        if dept_pv is not None and dept_pv.parameter_value is not None:
            return _parse_buyback_cap(dept_pv.parameter_value)  # same none/int parser
        global_pv = _get_policy_param(db, policy.id, 'max_carry_forward')
        if global_pv is not None and global_pv.parameter_value is not None:
            return _parse_buyback_cap(global_pv.parameter_value)

    # بدون رکورد سیاست: سقف سراسری نامشخص → 0 (بدون fallback per-code)
    return 0


def _region_applies_for_membership(db: Session, policy_id: int, membership_code: str) -> bool:
    flag = _get_policy_param(db, policy_id, f'region_applies_dept_{membership_code}')
    if flag is None:
        return True
    return flag.parameter_value not in ('false', '0', 'off', '')


def _parse_jalali_ymd(text: str) -> Optional[jdatetime.date]:
    try:
        parts = [int(p) for p in str(text).strip().replace('-', '/').split('/')]
        if len(parts) != 3:
            return None
        return jdatetime.date(parts[0], parts[1], parts[2])
    except Exception:
        return None


def resolve_buyback_cap_for_region(
    db: Session,
    region_code: Optional[str],
) -> int:
    """سقف ماده ۱۱ از ۱۳۹۹ برای یک منطقه."""
    code = (region_code or DEFAULT_REGION_CODE).strip().upper() or DEFAULT_REGION_CODE
    # سازگاری عقب‌رو: درجه یک دیگر منطقه جدا نیست
    if code == 'GRADE_1':
        code = DEFAULT_REGION_CODE
    policy = _get_leave_policy(db)
    if policy:
        pv = _get_policy_param(db, policy.id, 'buyback_cap', region_code=code)
        if pv is not None and pv.parameter_value is not None:
            parsed = _parse_buyback_cap(pv.parameter_value)
            if parsed is not None:
                return parsed
    return DEFAULT_BUYBACK_BY_REGION.get(code, 15)


def resolve_historical_buyback_cap(
    db: Session,
    *,
    region_code: Optional[str],
    year_j: int,
    as_of_j: Optional[jdatetime.date] = None,
) -> Optional[int]:
    """سقف بازخرید طبق بازه‌های تاریخی ماده ۱۱/۱."""
    policy = _get_leave_policy(db)

    def _era_val(key: str, default):
        if not policy:
            return default
        pv = _get_policy_param(db, policy.id, key)
        if pv is None or pv.parameter_value is None:
            return default
        return pv.parameter_value

    modern_raw = _era_val('buyback_era_modern_from_year', str(DEFAULT_ERA_MODERN_FROM))
    try:
        modern_from = int(float(modern_raw))
    except (TypeError, ValueError):
        modern_from = DEFAULT_ERA_MODERN_FROM

    if year_j >= modern_from:
        return resolve_buyback_cap_for_region(db, region_code)

    if year_j <= 1389:
        return _parse_buyback_cap(str(_era_val('buyback_era_pre_1390_cap', DEFAULT_ERA_PRE_1390)))

    # 1390 .. modern_from-1
    base = _parse_buyback_cap(str(_era_val('buyback_era_1390_1398_cap', str(DEFAULT_ERA_1390_1398))))
    region = (region_code or DEFAULT_REGION_CODE).strip().upper()
    if region == 'GRADE_4':
        from_raw = str(_era_val('buyback_era_grade4_from', DEFAULT_ERA_GRADE4_FROM))
        grade4_cap = _parse_buyback_cap(
            str(_era_val('buyback_era_grade4_cap', str(DEFAULT_ERA_GRADE4_CAP)))
        )
        start_j = _parse_jalali_ymd(from_raw) or jdatetime.date(1391, 7, 15)
        point = as_of_j or jdatetime.date(year_j, 12, 29)
        try:
            # سال کبیسه ممکن است ۳۰ داشته باشد
            point = as_of_j or jdatetime.date(year_j, 12, 30)
        except ValueError:
            point = as_of_j or jdatetime.date(year_j, 12, 29)
        if point >= start_j and grade4_cap is not None:
            return grade4_cap
    return base if base is not None else 15


def resolve_max_buyback(
    db: Session,
    membership_code: str,
    *,
    user_id: Optional[str] = None,
    region_code: Optional[str] = None,
    year_j: Optional[int] = None,
) -> Optional[int]:
    """
    سقف بازخرید روز برای تقسیم منطقی CW.

    - غیررسمی با buyback_dept=none → None (همه CW قابل‌بازخرید)
    - رسمی + اعمال منطقه → ماده ۱۱/منطقه یا عصر تاریخی
    - در غیر این صورت buyback_dept یا پیش‌فرض عضویت
    """
    policy_code = resolve_membership_code_for_policy(membership_code)
    policy = _get_leave_policy(db)
    year = year_j if year_j is not None else jdatetime.date.today().year

    # صریح گروه: برای غیررسمی اولویت دارد
    if policy:
        dept_pv = _get_policy_param(db, policy.id, f'buyback_dept_{policy_code}')
        if policy_code != MEMBERSHIP_PERMANENT:
            if dept_pv is not None and dept_pv.parameter_value is not None:
                return _parse_buyback_cap(dept_pv.parameter_value)
            if policy_code in MEMBERSHIP_PRORATE_BY_CONTRACT or policy_code == MEMBERSHIP_PHYSICIAN:
                return None
            if policy_code == MEMBERSHIP_CONSCRIPT:
                return None

        # رسمی با اعمال منطقه → سقف منطقه/عصر
        if policy_code == MEMBERSHIP_PERMANENT and _region_applies_for_membership(
            db, policy.id, policy_code
        ):
            effective_region = region_code
            if not effective_region and user_id:
                effective_region = resolve_region_code_from_service_location(db, user_id)
            if not effective_region:
                effective_region = DEFAULT_REGION_CODE
            return resolve_historical_buyback_cap(
                db,
                region_code=effective_region,
                year_j=year,
            )

        # رسمی بدون اعمال منطقه → buyback_dept_1 یا max_buyback
        if policy_code == MEMBERSHIP_PERMANENT:
            if dept_pv is not None and dept_pv.parameter_value is not None:
                return _parse_buyback_cap(dept_pv.parameter_value)
            global_pv = _get_policy_param(db, policy.id, 'max_buyback')
            if global_pv is not None and global_pv.parameter_value is not None:
                return _parse_buyback_cap(global_pv.parameter_value)

    return default_buyback_cap_for_membership(policy_code)


def resolve_membership_for_user(db: Session, user_id: str) -> str:
    """عضویت مؤثر کاربر از قرارداد فعال یا Employee.department."""
    today = date.today()
    contracts = (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.start_date.desc())
        .all()
    )
    for c in contracts:
        if c.start_date <= today and c.is_active:
            return resolve_membership_code_for_policy(c.contract_type_code)
    if contracts:
        return resolve_membership_code_for_policy(contracts[0].contract_type_code)

    employee = db.query(Employee).filter(Employee.user_id == user_id).first()
    if employee and employee.department:
        return resolve_membership_code_for_policy(str(employee.department))
    return '4'


def _has_membership_rule(db: Session, membership_code: str) -> bool:
    try:
        from models.membership_type_rule import MembershipTypeRule
        return (
            db.query(MembershipTypeRule.id)
            .filter(MembershipTypeRule.membership_type_code == membership_code)
            .first()
            is not None
        )
    except Exception:
        return False


def resolve_annual_leave_days_legacy(
    db: Session,
    membership_code: str,
    region_code: Optional[str] = None,
) -> int:
    """
    مسیر Legacy مستقل برای dual-run:
    فقط PolicyValue annual_leave_dept_* + region_applies_dept_* + region override.
    هرگز membership_type_rules / resolve_annual_leave_base_with_region را صدا نمی‌زند.
    """
    policy_code = resolve_membership_code_for_policy(membership_code)
    policy = _get_leave_policy(db)
    if not policy:
        return 0 if policy_code in ('5', '6', '7') else DEPT_DEFAULT_ANNUAL

    annual_pv = _get_policy_param(db, policy.id, f'annual_leave_dept_{policy_code}')
    default_annual = 0 if policy_code in ('5', '6', '7') else DEPT_DEFAULT_ANNUAL
    annual = _parse_int(
        annual_pv.parameter_value if annual_pv else None,
        default_annual,
    )

    region_flag_pv = _get_policy_param(
        db, policy.id, f'region_applies_dept_{policy_code}'
    )
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

    return max(0, annual)


def resolve_annual_leave_days(
    db: Session,
    membership_code: str,
    region_code: Optional[str] = None,
) -> int:
    """
    استحقاق سالانه (مسیر New پس از seed):
    Membership annual_leave_base → region_applies → regional override → fallback base.

    اگر هنوز Rule عضویت seed نشده باشد، مسیر legacy annual_leave_dept_* استفاده می‌شود.
    """
    policy_code = resolve_membership_code_for_policy(membership_code)

    if _has_membership_rule(db, policy_code):
        from web.services.membership_service import (
            resolve_annual_leave_base_with_region,
        )
        return resolve_annual_leave_base_with_region(
            db, policy_code, region_code=region_code
        )

    return resolve_annual_leave_days_legacy(
        db, policy_code, region_code=region_code
    )


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
    تقسیم پوشش قرارداد برای شارژ مرخصی — فقط سال شمسی جاری.

    - رسمی: اگر در سال جاری فعال باشد، از max(شروع، اول سال) تا پایان سال جاری
      (پایان بلندمدت قرارداد روی سال‌های قبل/بعد شارژ نمی‌سازد)
    - وظیفه: تا actual_end_date، فقط بخش سال جاری
    - قراردادی و مشابه: تا end_date، فقط بخش سال جاری
    """
    code = contract.contract_type_code
    start_g = contract.start_date
    current_year = jdatetime.date.today().year
    y_start, y_end = jalali_year_bounds_g(current_year)

    if start_g > y_end:
        return []

    if code == MEMBERSHIP_PERMANENT:
        # رسمی: پایان قرارداد روی شارژ سال جاری اثر ندارد (تا پایان سال جاری)
        if start_g > y_end:
            return []
        # اگر قرارداد صریحاً قبل از سال جاری تمام شده باشد، شارژ نکن
        if contract.end_date is not None and contract.end_date < y_start:
            return []
        seg_start = max(start_g, y_start)
        return [(current_year, seg_start, y_end)]

    # وظیفه: actual_end_date
    if code == MEMBERSHIP_CONSCRIPT:
        end_g = contract_effective_end(contract)
        if end_g is None:
            if start_g > y_end:
                return []
            seg_start = max(start_g, y_start)
            return [(current_year, seg_start, y_end)]
        if end_g < start_g or end_g < y_start:
            return []
        seg_start = max(start_g, y_start)
        seg_end = min(end_g, y_end)
        if seg_start <= seg_end:
            return [(current_year, seg_start, seg_end)]
        return []

    # قراردادی / خریدخدمت / سایر / بیمه / پزشکی
    end_g = contract.end_date
    if end_g is None:
        seg_start = max(start_g, y_start)
        return [(current_year, seg_start, y_end)]

    if end_g < start_g or end_g < y_start:
        return []
    seg_start = max(start_g, y_start)
    seg_end = min(end_g, y_end)
    if seg_start <= seg_end:
        return [(current_year, seg_start, seg_end)]
    return []


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
    محاسبه استحقاق قابل‌شارژ هنگام تنظیم قرارداد.

    فقط AL سال شمسی جاری؛ استعلاجی (SL) هرگز شارژ نمی‌شود.

    Returns: {year: {'AL': float, 'SL': 0.0}}
    """
    if employee is None:
        employee = db.query(Employee).filter(Employee.user_id == contract.user_id).first()

    annual = (
        annual_override
        if annual_override is not None
        else resolve_annual_for_employee_contract(db, employee, contract)
    )
    code = contract.contract_type_code
    segments = split_contract_coverage_by_year(contract)
    result: Dict[int, Dict[str, float]] = {}

    for year_j, seg_start, seg_end in segments:
        al = charge_amount_for_segment(code, annual, year_j, seg_start, seg_end)
        if year_j not in result:
            result[year_j] = {'AL': 0.0, 'SL': 0.0}
        result[year_j]['AL'] += al
        # سیاست: هنگام تنظیم قرارداد استعلاجی شارژ نمی‌شود
        result[year_j]['SL'] = 0.0
        logger.info(
            "Entitlement contract=%s type=%s year=%s AL=%.2f SL=0 "
            "seg=%s..%s annual_base=%s",
            contract.id, code, year_j, al, seg_start, seg_end, annual,
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
    # بدون remap: همان کد عضویت مؤثر روی department نوشته می‌شود
    dept = resolve_membership_code_for_policy(code)
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

