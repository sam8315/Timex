"""
Admin panel for Global Policy Management (سیاست کلی)
Only super_admin can access these pages.
"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import Optional, List
import re
import jdatetime
from web.dependencies import get_db, require_super_admin
from web.permissions import has_permission
from web.services.notification_service import is_sms_enabled, set_sms_enabled
from models.user import User
from models.region import Region
from models.policy import Policy, PolicyValue, PolicyAuditLog
from models.employee_region import EmployeeRegion
from models.employee import Employee
from models.attendance import AttendancePolicy, AttendancePolicyDay

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# انواع عضویت (مطابق کدهای دپارتمان Employee)
DEPT_TYPES = [
    ('1', 'رسمی'),
    ('2', 'وظیفه'),
    ('3', 'خریدخدمت'),
    ('4', 'قراردادی'),
    ('5', 'پزشک'),
]

# مقدار پیش‌فرض مرخصی استحقاقی بر اساس نوع عضویت
# (استعلاجی دستی توسط مدیر ارشد شارژ می‌شود و اینجا مدیریت نمی‌شود)
DEPT_DEFAULT_ANNUAL = 30

# کد منطقه پیش‌فرض که نباید حذف شود
PROTECTED_REGION_CODES = ('NORMAL',)


def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"


def _get_leave_policy(db: Session) -> Policy:
    """دریافت یا ایجاد سیاست مرخصی"""
    policy = db.query(Policy).filter(Policy.category == 'leave').first()
    if not policy:
        policy = Policy(
            category='leave',
            name='سیاست مرخصی',
            description='سیاست کلی مرخصی شامل مرخصی استحقاقی، انتقال و بازخرید',
            is_active=True,
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


def _get_param(db: Session, policy_id: int, key: str, region_code: Optional[str] = None) -> Optional[PolicyValue]:
    """دریافت یک پارامتر سیاستی"""
    query = db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy_id,
        PolicyValue.parameter_key == key,
    )
    if region_code is None:
        query = query.filter(PolicyValue.region_code.is_(None))
    else:
        query = query.filter(PolicyValue.region_code == region_code)
    return query.first()


def _set_param(db: Session, policy: Policy, key: str, value: str,
               region_code: Optional[str] = None, notes: Optional[str] = None,
               changed_by: Optional[str] = None) -> None:
    """ایجاد یا به‌روزرسانی یک پارامتر سیاستی + ثبت لاگ"""
    existing = _get_param(db, policy.id, key, region_code)
    entity_id = f"{key}:{region_code}" if region_code else key
    if existing:
        old_value = existing.parameter_value
        if old_value != value:
            existing.parameter_value = value
            if notes:
                existing.notes = notes
            db.add(PolicyAuditLog(
                entity_type='policy_value',
                entity_id=entity_id,
                action='UPDATE',
                old_value=old_value,
                new_value=value,
                changed_by=changed_by,
                reason='ویرایش از پنل سیاست کلی',
            ))
    else:
        db.add(PolicyValue(
            policy_id=policy.id,
            region_code=region_code,
            parameter_key=key,
            parameter_value=value,
            is_editable=True,
            notes=notes,
        ))
        db.add(PolicyAuditLog(
            entity_type='policy_value',
            entity_id=entity_id,
            action='CREATE',
            old_value=None,
            new_value=value,
            changed_by=changed_by,
            reason='ایجاد از پنل سیاست کلی',
        ))


@router.get("/admin/policies", response_class=HTMLResponse)
async def admin_policies(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Main policy list page (shows all policy categories)"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    return templates.TemplateResponse(request, "admin/policies.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "sms_enabled": is_sms_enabled(db),
    })


@router.get("/admin/policies/sms", response_class=HTMLResponse)
async def admin_policies_sms(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """SMS notification settings page"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    return templates.TemplateResponse(request, "admin/policy_sms.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "sms_enabled": is_sms_enabled(db),
    })


@router.post("/admin/policies/sms/save")
async def admin_policies_sms_save(
    request: Request,
    enabled: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Enable/disable leave SMS notifications"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    set_sms_enabled(db, enabled == "true", changed_by=user.user_id)

    referer = request.headers.get("referer", "/admin/policies/sms")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "saved"),
        status_code=302
    )


@router.get("/admin/policies/leave", response_class=HTMLResponse)
async def admin_policies_leave(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Leave policy management page"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = _get_leave_policy(db)

    global_cf_pv = _get_param(db, policy.id, 'max_carry_forward')
    try:
        global_cf = int(float(global_cf_pv.parameter_value)) if global_cf_pv else 9
    except (TypeError, ValueError):
        global_cf = 9
    bb_pv = _get_param(db, policy.id, 'max_buyback')
    method_pv = _get_param(db, policy.id, 'region_change_method')

    # سقف انتقال به‌ازای هر گروه (سقوط به مقدار سراسری و بعد ۹)
    carry_rows = []
    for code, name in DEPT_TYPES:
        cf_pv = _get_param(db, policy.id, f'carry_forward_dept_{code}')
        try:
            limit = int(float(cf_pv.parameter_value)) if cf_pv else global_cf
        except (TypeError, ValueError):
            limit = global_cf
        carry_rows.append({'code': code, 'name': name, 'limit': limit})

    # مرخصی استحقاقی پیش‌فرض بر اساس نوع عضویت + پرچم اعمال قوانین منطقه
    # (ویرایش مقادیر منطقه فقط در صفحه مدیریت مناطق انجام می‌شود)
    employment_rows = []
    for code, name in DEPT_TYPES:
        a_pv = _get_param(db, policy.id, f'annual_leave_dept_{code}')
        r_pv = _get_param(db, policy.id, f'region_applies_dept_{code}')
        try:
            annual = int(float(a_pv.parameter_value)) if a_pv else DEPT_DEFAULT_ANNUAL
        except (TypeError, ValueError):
            annual = DEPT_DEFAULT_ANNUAL
        # پیش‌فرض: قوانین منطقه اعمال می‌شود (حفظ رفتار فعلی)
        region_applies = (r_pv.parameter_value != 'false') if r_pv else True
        employment_rows.append({
            'code': code, 'name': name, 'annual': annual,
            'region_applies': region_applies,
        })

    return templates.TemplateResponse(request, "admin/policy_leave.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "carry_rows": carry_rows,
        "buyback_limit": bb_pv.parameter_value if bb_pv else '15',
        "pro_rata_method": (method_pv.parameter_value != 'full_year') if method_pv else True,
        "employment_rows": employment_rows,
    })


@router.post("/admin/policies/carry-forward/save")
async def admin_policies_carry_forward_save(
    request: Request,
    cf_1: int = Form(9),
    cf_2: int = Form(9),
    cf_3: int = Form(9),
    cf_4: int = Form(9),
    cf_5: int = Form(9),
    pro_rata_method: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Save per-department carry-forward limits + region-change method"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = _get_leave_policy(db)
    dept_limits = {'1': cf_1, '2': cf_2, '3': cf_3, '4': cf_4, '5': cf_5}
    for code, name in DEPT_TYPES:
        limit = max(0, min(30, dept_limits[code]))
        _set_param(db, policy, f'carry_forward_dept_{code}', str(limit),
                   notes=f'سقف انتقال مرخصی نوع عضویت {name}',
                   changed_by=user.user_id)
    method_value = 'pro_rata' if pro_rata_method == 'true' else 'full_year'
    _set_param(db, policy, 'region_change_method', method_value,
               notes='روش اعمال تغییر منطقه وسط سال',
               changed_by=user.user_id)
    db.commit()

    referer = request.headers.get("referer", "/admin/policies/leave")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "saved"),
        status_code=302
    )


@router.post("/admin/policies/buyback/save")
async def admin_policies_buyback_save(
    request: Request,
    buyback_limit: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Save buyback limit"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = _get_leave_policy(db)
    _set_param(db, policy, 'max_buyback', str(max(0, min(30, buyback_limit))),
               notes='سقف بازخرید مرخصی (مستقل از منطقه)',
               changed_by=user.user_id)
    db.commit()

    referer = request.headers.get("referer", "/admin/policies/leave")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "saved"),
        status_code=302
    )


@router.post("/admin/policies/employment/save")
async def admin_policies_employment_save(
    request: Request,
    annual_1: int = Form(30),
    annual_2: int = Form(30),
    annual_3: int = Form(30),
    annual_4: int = Form(30),
    annual_5: int = Form(30),
    region_applies_1: str = Form("off"),
    region_applies_2: str = Form("off"),
    region_applies_3: str = Form("off"),
    region_applies_4: str = Form("off"),
    region_applies_5: str = Form("off"),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Save default annual leave per employment type + region-applicability flag"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = _get_leave_policy(db)
    dept_values = {
        '1': (annual_1, region_applies_1),
        '2': (annual_2, region_applies_2),
        '3': (annual_3, region_applies_3),
        '4': (annual_4, region_applies_4),
        '5': (annual_5, region_applies_5),
    }
    for code, name in DEPT_TYPES:
        annual, applies_raw = dept_values[code]
        annual = max(0, min(100, annual))
        applies = 'true' if applies_raw in ('on', 'true', '1') else 'false'
        _set_param(db, policy, f'annual_leave_dept_{code}', str(annual),
                   notes=f'مرخصی استحقاقی پیش‌فرض نوع عضویت {name}',
                   changed_by=user.user_id)
        _set_param(db, policy, f'region_applies_dept_{code}', applies,
                   notes=f'اعمال قوانین منطقه برای نوع عضویت {name}',
                   changed_by=user.user_id)
    db.commit()

    referer = request.headers.get("referer", "/admin/policies/leave")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "saved"),
        status_code=302
    )


@router.post("/admin/policies/regions/{region_code}/update")
async def admin_policies_regions_update(
    request: Request,
    region_code: str,
    annual_leave_days: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Update region annual leave days (regions table + policy_values)"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = _get_leave_policy(db)
    region = db.query(Region).filter(Region.code == region_code).first()
    if region:
        old_days = region.default_annual_leave_days
        region.default_annual_leave_days = annual_leave_days
        db.add(PolicyAuditLog(
            entity_type='region',
            entity_id=region_code,
            action='UPDATE',
            old_value=str(old_days),
            new_value=str(annual_leave_days),
            changed_by=user.user_id,
            reason='تغییر روزهای مرخصی منطقه',
        ))
        _set_param(db, policy, 'annual_leave_days', str(annual_leave_days),
                   region_code=region_code,
                   notes=f'مرخصی استحقاقی منطقه {region.name}',
                   changed_by=user.user_id)
        db.commit()

    referer = request.headers.get("referer", "/admin/policies/regions")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "updated"),
        status_code=302
    )


@router.post("/admin/policies/regions/{region_code}/edit")
async def admin_policies_regions_edit(
    request: Request,
    region_code: str,
    name: str = Form(...),
    description: str = Form(""),
    sort_order: int = Form(0),
    annual_leave_days: int = Form(30),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Full edit of a service region (name, description, order, leave days)"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    referer = request.headers.get("referer", "/admin/policies/regions")
    region = db.query(Region).filter(Region.code == region_code).first()
    if not region:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "not-found"), status_code=302)
    name = (name or "").strip()
    if not name:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "empty-name"), status_code=302)

    policy = _get_leave_policy(db)
    days = max(0, min(100, annual_leave_days))
    if region.name != name:
        db.add(PolicyAuditLog(
            entity_type='region', entity_id=region_code, action='UPDATE',
            old_value=region.name, new_value=name,
            changed_by=user.user_id, reason='ویرایش نام منطقه',
        ))
        region.name = name
    new_desc = description.strip() or None
    if (region.description or None) != new_desc:
        db.add(PolicyAuditLog(
            entity_type='region', entity_id=region_code, action='UPDATE',
            old_value=region.description, new_value=new_desc,
            changed_by=user.user_id, reason='ویرایش توضیح منطقه',
        ))
        region.description = new_desc
    if (region.sort_order or 0) != sort_order:
        db.add(PolicyAuditLog(
            entity_type='region', entity_id=region_code, action='UPDATE',
            old_value=str(region.sort_order), new_value=str(sort_order),
            changed_by=user.user_id, reason='ویرایش ترتیب نمایش منطقه',
        ))
        region.sort_order = sort_order
    if int(region.default_annual_leave_days) != days:
        db.add(PolicyAuditLog(
            entity_type='region', entity_id=region_code, action='UPDATE',
            old_value=str(int(region.default_annual_leave_days)), new_value=str(days),
            changed_by=user.user_id, reason='ویرایش مرخصی منطقه',
        ))
        region.default_annual_leave_days = days
        _set_param(db, policy, 'annual_leave_days', str(days),
                   region_code=region_code,
                   notes=f'مرخصی استحقاقی منطقه {region.name}',
                   changed_by=user.user_id)
    db.commit()

    return RedirectResponse(
        url=build_redirect_url(referer, "success", "updated"),
        status_code=302
    )


@router.post("/admin/policies/regions/add")
async def admin_policies_regions_add(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    annual_leave_days: int = Form(30),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Create a new service region"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    referer = request.headers.get("referer", "/admin/policies/regions")
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not re.fullmatch(r"[A-Z0-9_]{2,20}", code):
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "invalid-code"), status_code=302)
    if not name:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "empty-name"), status_code=302)
    if db.query(Region).filter(Region.code == code).first():
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "duplicate-code"), status_code=302)

    days = max(0, min(100, annual_leave_days))
    region = Region(
        code=code,
        name=name,
        description=description.strip() or None,
        default_annual_leave_days=days,
        is_active=True,
        sort_order=sort_order,
    )
    db.add(region)
    db.commit()
    db.refresh(region)

    policy = _get_leave_policy(db)
    _set_param(db, policy, 'annual_leave_days', str(days),
               region_code=code,
               notes=f'مرخصی استحقاقی منطقه {name}',
               changed_by=user.user_id)
    db.add(PolicyAuditLog(
        entity_type='region',
        entity_id=code,
        action='CREATE',
        old_value=None,
        new_value=name,
        changed_by=user.user_id,
        reason='ایجاد منطقه جدید',
    ))
    db.commit()

    return RedirectResponse(
        url=build_redirect_url(referer, "success", "added"),
        status_code=302
    )


@router.post("/admin/policies/regions/{region_code}/delete")
async def admin_policies_regions_delete(
    request: Request,
    region_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Delete a service region (blocked if employees are assigned or protected)"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    referer = request.headers.get("referer", "/admin/policies/regions")
    region = db.query(Region).filter(Region.code == region_code).first()
    if not region:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "not-found"), status_code=302)
    if region_code in PROTECTED_REGION_CODES:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "protected"), status_code=302)
    emp_count = db.query(Employee).filter(Employee.region_code == region_code).count()
    if emp_count > 0:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "has-employees"), status_code=302)

    policy = _get_leave_policy(db)
    db.query(PolicyValue).filter(
        PolicyValue.policy_id == policy.id,
        PolicyValue.parameter_key == 'annual_leave_days',
        PolicyValue.region_code == region_code,
    ).delete(synchronize_session=False)
    db.add(PolicyAuditLog(
        entity_type='region',
        entity_id=region_code,
        action='DELETE',
        old_value=region.name,
        new_value=None,
        changed_by=user.user_id,
        reason='حذف منطقه',
    ))
    db.delete(region)
    db.commit()

    return RedirectResponse(
        url=build_redirect_url(referer, "success", "deleted"),
        status_code=302
    )


@router.post("/admin/policies/regions/{region_code}/toggle")
async def admin_policies_regions_toggle(
    request: Request,
    region_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Activate/deactivate a service region"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    referer = request.headers.get("referer", "/admin/policies/regions")
    region = db.query(Region).filter(Region.code == region_code).first()
    if not region:
        return RedirectResponse(
            url=build_redirect_url(referer, "error", "not-found"), status_code=302)

    old_value = 'فعال' if region.is_active else 'غیرفعال'
    region.is_active = not region.is_active
    new_value = 'فعال' if region.is_active else 'غیرفعال'
    db.add(PolicyAuditLog(
        entity_type='region',
        entity_id=region_code,
        action='UPDATE',
        old_value=old_value,
        new_value=new_value,
        changed_by=user.user_id,
        reason='تغییر وضعیت فعال بودن منطقه',
    ))
    db.commit()

    return RedirectResponse(
        url=build_redirect_url(referer, "success", "toggled"),
        status_code=302
    )


@router.get("/admin/policies/regions", response_class=HTMLResponse)
async def admin_policies_regions(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """Region management page"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    regions = db.query(Region).order_by(Region.sort_order).all()
    region_data = []
    for region in regions:
        emp_count = db.query(Employee).filter(Employee.region_code == region.code).count()
        region_data.append({
            'code': region.code,
            'name': region.name,
            'description': region.description or '',
            'sort_order': region.sort_order or 0,
            'annual_leave_days': int(region.default_annual_leave_days),
            'employee_count': emp_count,
            'is_active': region.is_active,
        })

    history = db.query(EmployeeRegion).order_by(EmployeeRegion.created_at.desc()).limit(20).all()

    return templates.TemplateResponse(request, "admin/policy_regions.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "regions": region_data,
        "history": history,
    })


# ============================================
# 🆕 Attendance Policy Management (Phase 5)
# ============================================

@router.get("/admin/policies/attendance", response_class=HTMLResponse)
async def admin_policies_attendance(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """صفحه مدیریت سیاست‌های حضور و غیاب"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    # دریافت همه سیاست‌های فعال
    policies = db.query(AttendancePolicy).filter(
        AttendancePolicy.is_active == True
    ).order_by(AttendancePolicy.employment_type_code, AttendancePolicy.effective_from_date.desc()).all()

    # ساخت دیکشنری سیاست‌ها به تفکیک employment_type
    policies_by_type = {code: [] for code, _ in DEPT_TYPES}
    for p in policies:
        if p.user_id:
            # Employee Override - در بخش جداگانه نمایش داده می‌شود
            continue
        if p.employment_type_code in policies_by_type:
            from_date_j = ''
            to_date_j = 'نامحدود'
            if p.effective_from_date:
                from_date_j = jdatetime.date.fromgregorian(date=p.effective_from_date).strftime('%Y/%m/%d')
            if p.effective_to_date:
                to_date_j = jdatetime.date.fromgregorian(date=p.effective_to_date).strftime('%Y/%m/%d')
            policies_by_type[p.employment_type_code].append({
                'id': p.id,
                'from_date': from_date_j,
                'to_date': to_date_j,
                'late_enabled': p.late_enabled,
                'late_allowed': p.late_allowed_minutes,
                'early_enabled': p.early_leave_enabled,
                'early_allowed': p.early_leave_allowed_minutes,
            })

    # دریافت Employee Overrides
    overrides = db.query(AttendancePolicy).filter(
        AttendancePolicy.user_id.isnot(None),
        AttendancePolicy.is_active == True
    ).all()
    override_list = []
    for ov in overrides:
        emp = db.query(Employee).filter(Employee.user_id == ov.user_id).first()
        ov_from_j = ''
        ov_to_j = 'نامحدود'
        if ov.effective_from_date:
            ov_from_j = jdatetime.date.fromgregorian(date=ov.effective_from_date).strftime('%Y/%m/%d')
        if ov.effective_to_date:
            ov_to_j = jdatetime.date.fromgregorian(date=ov.effective_to_date).strftime('%Y/%m/%d')
        override_list.append({
            'id': ov.id,
            'user_id': ov.user_id,
            'full_name': emp.full_name if emp else ov.user_id,
            'from_date': ov_from_j,
            'to_date': ov_to_j,
        })

    return templates.TemplateResponse(request, "admin/policy_attendance.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "dept_types": DEPT_TYPES,
        "policies_by_type": policies_by_type,
        "overrides": override_list,
    })


# ============================================
# Phase 6: Attendance Policy CRUD
# ============================================

@router.get("/admin/policies/attendance/add", response_class=HTMLResponse)
async def admin_policies_attendance_add(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """صفحه افزودن سیاست حضور و غیاب جدید"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    # Get employees for override autocomplete
    employees = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.last_name, Employee.first_name).limit(100).all()

    return templates.TemplateResponse(request, "admin/policy_attendance_form.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "dept_types": DEPT_TYPES,
        "policy": None,  # Add mode
        "schedule": None,
        "employees": [{"user_id": e.user_id, "full_name": e.full_name} for e in employees],
        "form_action": "/admin/policies/attendance/save",
        "form_title": "افزودن سیاست جدید",
    })


@router.post("/admin/policies/attendance/save")
async def admin_policies_attendance_save(
    request: Request,
    employment_type_code: str = Form(...),
    user_id_override: str = Form(""),
    effective_from_date_str: str = Form(...),
    effective_to_date_str: str = Form(""),
    late_enabled: str = Form(""),
    late_allowed_minutes: int = Form(0),
    late_reference_mode: str = Form("FIXED_TIME"),
    early_leave_enabled: str = Form(""),
    early_leave_allowed_minutes: int = Form(0),
    early_reference_mode: str = Form("FIXED_TIME"),
    # Schedule: 7 days (weekday 0-6)
    wd0_working: str = Form(""),
    wd0_start: str = Form(""),
    wd0_end: str = Form(""),
    wd1_working: str = Form(""),
    wd1_start: str = Form(""),
    wd1_end: str = Form(""),
    wd2_working: str = Form(""),
    wd2_start: str = Form(""),
    wd2_end: str = Form(""),
    wd3_working: str = Form(""),
    wd3_start: str = Form(""),
    wd3_end: str = Form(""),
    wd4_working: str = Form(""),
    wd4_start: str = Form(""),
    wd4_end: str = Form(""),
    wd5_working: str = Form(""),
    wd5_start: str = Form(""),
    wd5_end: str = Form(""),
    wd6_working: str = Form(""),
    wd6_start: str = Form(""),
    wd6_end: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """ذخیره سیاست حضور و غیاب جدید"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    try:
        # Validation: employment_type_code
        valid_codes = [code for code, _ in DEPT_TYPES]
        if employment_type_code not in valid_codes:
            raise ValueError("نوع عضویت نامعتبر است")

        # Validation: late/early grace minutes (0-120)
        late_allowed_minutes = max(0, min(120, late_allowed_minutes))
        early_leave_allowed_minutes = max(0, min(120, early_leave_allowed_minutes))

        # Validation: reference mode
        if late_reference_mode not in ('FIXED_TIME',):
            late_reference_mode = 'FIXED_TIME'
        if early_reference_mode not in ('FIXED_TIME',):
            early_reference_mode = 'FIXED_TIME'

        # Parse dates (Persian to Gregorian)
        from datetime import date as date_class

        try:
            from_j = jdatetime.datetime.strptime(effective_from_date_str.strip(), "%Y/%m/%d").date()
            effective_from_date = from_j.togregorian()
        except (ValueError, AttributeError):
            raise ValueError("تاریخ شروع نامعتبر است")

        effective_to_date = None
        if effective_to_date_str.strip():
            try:
                to_j = jdatetime.datetime.strptime(effective_to_date_str.strip(), "%Y/%m/%d").date()
                effective_to_date = to_j.togregorian()
            except (ValueError, AttributeError):
                raise ValueError("تاریخ پایان نامعتبر است")
            if effective_to_date <= effective_from_date:
                raise ValueError("تاریخ پایان باید بعد از تاریخ شروع باشد")

        # Validate override user exists if provided
        override_user_id = user_id_override.strip() or None
        if override_user_id:
            emp = db.query(Employee).filter(Employee.user_id == override_user_id).first()
            if not emp:
                raise ValueError("کارمند یافت نشد")

        # Check for overlapping active policies
        overlap_query = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == employment_type_code,
            AttendancePolicy.is_active == True
        )
        if override_user_id:
            overlap_query = overlap_query.filter(AttendancePolicy.user_id == override_user_id)
        else:
            overlap_query = overlap_query.filter(AttendancePolicy.user_id.is_(None))

        # Date overlap check
        overlap_query = overlap_query.filter(
            AttendancePolicy.effective_from_date <= (effective_to_date or date_class.max),
            or_(
                AttendancePolicy.effective_to_date.is_(None),
                AttendancePolicy.effective_to_date >= effective_from_date
            )
        )
        existing = overlap_query.first()
        if existing:
            raise ValueError("سیاست همپوشانی با سیاست موجود دارد")

        # Parse schedule
        schedule_data = []
        working_days_count = 0
        for wd in range(7):
            working = locals()[f'wd{wd}_working'] == 'on'
            start_str = locals()[f'wd{wd}_start']
            end_str = locals()[f'wd{wd}_end']

            start_time = None
            end_time = None

            if working:
                if not start_str or not end_str:
                    raise ValueError(f"ساعت ورود/خروج برای روز {wd} الزامی است")
                start_time = parse_time(start_str)
                end_time = parse_time(end_str)
                if not start_time or not end_time:
                    raise ValueError(f"ساعت نامعتبر برای روز {wd}")
                if start_time >= end_time:
                    raise ValueError(f"ساعت ورود باید قبل از خروج برای روز {wd} باشد")
                working_days_count += 1
            else:
                # Non-working day: ensure null times
                if start_str or end_str:
                    raise ValueError(f"روز غیرکاری نباید ساعت داشته باشد")

            schedule_data.append({
                'weekday': wd,
                'is_working_day': working,
                'start_time': start_time,
                'end_time': end_time
            })

        # Validation: at least one working day
        if working_days_count == 0:
            raise ValueError("حداقل یک روز کاری باید تعریف شود")

        # Create policy
        policy = AttendancePolicy(
            employment_type_code=employment_type_code,
            user_id=override_user_id,
            effective_from_date=effective_from_date,
            effective_to_date=effective_to_date,
            late_enabled=(late_enabled == 'on'),
            late_allowed_minutes=late_allowed_minutes,
            late_reference_mode=late_reference_mode,
            early_leave_enabled=(early_leave_enabled == 'on'),
            early_leave_allowed_minutes=early_leave_allowed_minutes,
            early_leave_reference_mode=early_reference_mode,
            is_active=True
        )
        db.add(policy)
        db.flush()  # Get policy ID

        # Create schedule (7 days)
        for day_data in schedule_data:
            policy_day = AttendancePolicyDay(
                policy_id=policy.id,
                weekday=day_data['weekday'],
                is_working_day=day_data['is_working_day'],
                start_time=day_data['start_time'],
                end_time=day_data['end_time']
            )
            db.add(policy_day)

        db.commit()

        referer = request.headers.get("referer", "/admin/policies/attendance")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "saved"),
            status_code=302
        )

    except ValueError as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/policies/attendance/add")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", "/admin/policies/attendance/add")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.get("/admin/policies/attendance/{policy_id}/edit", response_class=HTMLResponse)
async def admin_policies_attendance_edit(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """صفحه ویرایش سیاست حضور و غیاب"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = db.query(AttendancePolicy).filter(AttendancePolicy.id == policy_id).first()
    if not policy:
        return RedirectResponse(url="/admin/policies/attendance?error=یافت نشد", status_code=302)

    # Get schedule
    schedule_days = db.query(AttendancePolicyDay).filter(
        AttendancePolicyDay.policy_id == policy_id
    ).order_by(AttendancePolicyDay.weekday).all()

    schedule = {}
    for day in schedule_days:
        schedule[day.weekday] = {
            'is_working_day': day.is_working_day,
            'start_time': day.start_time.strftime('%H:%M') if day.start_time else '',
            'end_time': day.end_time.strftime('%H:%M') if day.end_time else ''
        }

    # Get employees for override autocomplete
    employees = db.query(Employee).filter(
        Employee.is_active == True
    ).order_by(Employee.last_name, Employee.first_name).limit(100).all()

    # Convert Gregorian effective dates to Jalali for form pre-filling
    effective_from_j = ""
    effective_to_j = ""
    if policy.effective_from_date:
        effective_from_j = jdatetime.date.fromgregorian(
            date=policy.effective_from_date
        ).strftime('%Y/%m/%d')
    if policy.effective_to_date:
        effective_to_j = jdatetime.date.fromgregorian(
            date=policy.effective_to_date
        ).strftime('%Y/%m/%d')

    return templates.TemplateResponse(request, "admin/policy_attendance_form.html", {
        "user": user,
        "is_admin": True,
        "is_super_admin": True,
        "dept_types": DEPT_TYPES,
        "policy": policy,
        "schedule": schedule,
        "effective_from_j": effective_from_j,
        "effective_to_j": effective_to_j,
        "employees": [{"user_id": e.user_id, "full_name": e.full_name} for e in employees],
        "form_action": f"/admin/policies/attendance/{policy_id}/update",
        "form_title": "ویرایش سیاست",
    })


@router.post("/admin/policies/attendance/{policy_id}/update")
async def admin_policies_attendance_update(
    request: Request,
    policy_id: int,
    employment_type_code: str = Form(...),
    user_id_override: str = Form(""),
    effective_from_date_str: str = Form(...),
    effective_to_date_str: str = Form(""),
    late_enabled: str = Form(""),
    late_allowed_minutes: int = Form(0),
    late_reference_mode: str = Form("FIXED_TIME"),
    early_leave_enabled: str = Form(""),
    early_leave_allowed_minutes: int = Form(0),
    early_reference_mode: str = Form("FIXED_TIME"),
    # Schedule
    wd0_working: str = Form(""),
    wd0_start: str = Form(""),
    wd0_end: str = Form(""),
    wd1_working: str = Form(""),
    wd1_start: str = Form(""),
    wd1_end: str = Form(""),
    wd2_working: str = Form(""),
    wd2_start: str = Form(""),
    wd2_end: str = Form(""),
    wd3_working: str = Form(""),
    wd3_start: str = Form(""),
    wd3_end: str = Form(""),
    wd4_working: str = Form(""),
    wd4_start: str = Form(""),
    wd4_end: str = Form(""),
    wd5_working: str = Form(""),
    wd5_start: str = Form(""),
    wd5_end: str = Form(""),
    wd6_working: str = Form(""),
    wd6_start: str = Form(""),
    wd6_end: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """به‌روزرسانی سیاست حضور و غیاب"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = db.query(AttendancePolicy).filter(AttendancePolicy.id == policy_id).first()
    if not policy:
        return RedirectResponse(url="/admin/policies/attendance?error=یافت نشد", status_code=302)

    try:
        # Validation: employment_type_code
        valid_codes = [code for code, _ in DEPT_TYPES]
        if employment_type_code not in valid_codes:
            raise ValueError("نوع عضویت نامعتبر است")

        # Validation: late/early grace minutes (0-120)
        late_allowed_minutes = max(0, min(120, late_allowed_minutes))
        early_leave_allowed_minutes = max(0, min(120, early_leave_allowed_minutes))

        # Validation: reference mode
        if late_reference_mode not in ('FIXED_TIME',):
            late_reference_mode = 'FIXED_TIME'
        if early_reference_mode not in ('FIXED_TIME',):
            early_reference_mode = 'FIXED_TIME'

        # Parse dates
        from datetime import date as date_class

        try:
            from_j = jdatetime.datetime.strptime(effective_from_date_str.strip(), "%Y/%m/%d").date()
            effective_from_date = from_j.togregorian()
        except (ValueError, AttributeError):
            raise ValueError("تاریخ شروع نامعتبر است")

        effective_to_date = None
        if effective_to_date_str.strip():
            try:
                to_j = jdatetime.datetime.strptime(effective_to_date_str.strip(), "%Y/%m/%d").date()
                effective_to_date = to_j.togregorian()
            except (ValueError, AttributeError):
                raise ValueError("تاریخ پایان نامعتبر است")
            if effective_to_date <= effective_from_date:
                raise ValueError("تاریخ پایان باید بعد از تاریخ شروع باشد")

        # Validate override user
        override_user_id = user_id_override.strip() or None
        if override_user_id:
            emp = db.query(Employee).filter(Employee.user_id == override_user_id).first()
            if not emp:
                raise ValueError("کارمند یافت نشد")

        # Check for overlapping policies (exclude current)
        overlap_query = db.query(AttendancePolicy).filter(
            AttendancePolicy.employment_type_code == employment_type_code,
            AttendancePolicy.is_active == True,
            AttendancePolicy.id != policy_id
        )
        if override_user_id:
            overlap_query = overlap_query.filter(AttendancePolicy.user_id == override_user_id)
        else:
            overlap_query = overlap_query.filter(AttendancePolicy.user_id.is_(None))

        overlap_query = overlap_query.filter(
            AttendancePolicy.effective_from_date <= (effective_to_date or date_class.max),
            or_(
                AttendancePolicy.effective_to_date.is_(None),
                AttendancePolicy.effective_to_date >= effective_from_date
            )
        )
        existing = overlap_query.first()
        if existing:
            raise ValueError("سیاست همپوشانی با سیاست موجود دارد")

        # Parse schedule
        working_days_count = 0
        for wd in range(7):
            working = locals()[f'wd{wd}_working'] == 'on'
            start_str = locals()[f'wd{wd}_start']
            end_str = locals()[f'wd{wd}_end']

            start_time = None
            end_time = None

            if working:
                if not start_str or not end_str:
                    raise ValueError(f"ساعت ورود/خروج برای روز {wd} الزامی است")
                start_time = parse_time(start_str)
                end_time = parse_time(end_str)
                if not start_time or not end_time:
                    raise ValueError(f"ساعت نامعتبر برای روز {wd}")
                if start_time >= end_time:
                    raise ValueError(f"ساعت ورود باید قبل از خروج برای روز {wd} باشد")
                working_days_count += 1
            else:
                if start_str or end_str:
                    raise ValueError(f"روز غیرکاری نباید ساعت داشته باشد")

        if working_days_count == 0:
            raise ValueError("حداقل یک روز کاری باید تعریف شود")

        # Update policy
        policy.employment_type_code = employment_type_code
        policy.user_id = override_user_id
        policy.effective_from_date = effective_from_date
        policy.effective_to_date = effective_to_date
        policy.late_enabled = (late_enabled == 'on')
        policy.late_allowed_minutes = late_allowed_minutes
        policy.late_reference_mode = late_reference_mode
        policy.early_leave_enabled = (early_leave_enabled == 'on')
        policy.early_leave_allowed_minutes = early_leave_allowed_minutes
        policy.early_leave_reference_mode = early_reference_mode

        # Delete existing schedule and recreate
        db.query(AttendancePolicyDay).filter(
            AttendancePolicyDay.policy_id == policy_id
        ).delete()

        for wd in range(7):
            working = locals()[f'wd{wd}_working'] == 'on'
            start_str = locals()[f'wd{wd}_start']
            end_str = locals()[f'wd{wd}_end']

            start_time = parse_time(start_str) if start_str else None
            end_time = parse_time(end_str) if end_str else None

            policy_day = AttendancePolicyDay(
                policy_id=policy_id,
                weekday=wd,
                is_working_day=working,
                start_time=start_time,
                end_time=end_time
            )
            db.add(policy_day)

        db.commit()

        referer = request.headers.get("referer", "/admin/policies/attendance")
        return RedirectResponse(
            url=build_redirect_url(referer, "success", "updated"),
            status_code=302
        )

    except ValueError as e:
        db.rollback()
        referer = request.headers.get("referer", f"/admin/policies/attendance/{policy_id}/edit")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", str(e)),
            status_code=302
        )
    except Exception as e:
        db.rollback()
        referer = request.headers.get("referer", f"/admin/policies/attendance/{policy_id}/edit")
        return RedirectResponse(
            url=build_redirect_url(referer, "error", f"خطا: {str(e)}"),
            status_code=302
        )


@router.post("/admin/policies/attendance/{policy_id}/delete")
async def admin_policies_attendance_delete(
    request: Request,
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin)
):
    """حذف (غیرفعال کردن) سیاست حضور و غیاب - Soft Delete

    سیاستی که قبلاً شروع به کار کرده است ممکن است برای رزولوشن تردد تاریخی
    استفاده شده باشد؛ حذف آن باعث می‌شود آن تاریخ‌ها به پیش‌فرض یا سیاست
    دیگری برگردند و رزولوشن تاریخی خراب شود. بنابراین فقط سیاست‌هایی که هنوز
    در آینده شروع نشده‌اند قابل حذف (غیرفعال‌سازی) هستند. برای تغییر یک
    سیاستِ جاری، از ویرایش استفاده می‌شود.
    """
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    policy = db.query(AttendancePolicy).filter(AttendancePolicy.id == policy_id).first()
    if not policy:
        return RedirectResponse(
            url="/admin/policies/attendance?error=سیاست یافت نشد",
            status_code=302
        )

    # Correction #5: رد حذف سیاستی که بازه‌اش قبلاً شروع شده (استفاده‌شده در
    # بازه‌ی تاریخی) تا رزولوشن تاریخی خراب نشود.
    from datetime import date as date_class
    today = date_class.today()
    if policy.effective_from_date and policy.effective_from_date <= today:
        return RedirectResponse(
            url="/admin/policies/attendance?error=این سیاست در بازه‌ی تاریخی استفاده شده است و قابل حذف نیست. برای تغییر، آن را ویرایش کنید.",
            status_code=302
        )

    policy.is_active = False
    db.commit()

    referer = request.headers.get("referer", "/admin/policies/attendance")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "deleted"),
        status_code=302
    )


def parse_time(time_str: str):
    """Parse HH:MM time string to time object"""
    if not time_str:
        return None
    try:
        from datetime import time
        parts = time_str.strip().split(':')
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return time(hour, minute)
    except (ValueError, IndexError):
        return None
