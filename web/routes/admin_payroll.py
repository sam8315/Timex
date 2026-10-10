"""مسیرهای مدیریت عملیات حقوق و سیاست حقوق."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import jdatetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database.engine import SessionLocal
from models.employee import Employee
from models.membership_type import MembershipType
from models.payroll import PayrollRun
from models.user import User
from web.dependencies import get_current_user, get_db
from web.permissions import has_permission, role_label_map
from web.services.payroll import policy_service, run_service
from web.services.payroll.policy_service import PayrollPolicyError
from web.services.payroll.run_service import PayrollRunError
from core.payroll.pdf_payslip import build_payslip_pdf
from core.payroll.payslip_present import fa_digits, line_detail, money_text, payslip_sort
from core.payroll.shift import PATTERN_LABELS, PATTERN_NONE, SHIFT_OPTIONS
from web.services.payroll.payslip_profile import load_payslip_profile

router = APIRouter(tags=["Admin Payroll"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
templates.env.filters["line_detail"] = line_detail
templates.env.filters["money_text"] = money_text
templates.env.filters["fa_digits"] = fa_digits
templates.env.filters["payslip_sort"] = payslip_sort


def _fmt_num(value) -> str:
    """نمایش عدد بدون صفرهای اضافی بعد از اعشار."""
    if value is None or value == "":
        return ""
    try:
        text = format(Decimal(str(value)), "f")
    except (InvalidOperation, ValueError):
        return str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_jalali(value) -> str:
    if not value:
        return "—"
    if isinstance(value, date):
        return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")
    return str(value)


templates.env.filters["payroll_num"] = _fmt_num
templates.env.filters["jalali"] = _fmt_jalali

CALC_MODE_LABELS = {
    "manual": "دستی",
    "fixed_monthly_prorata": "ثابت ماهانه",
    "daily_x_covered": "روزانه × پوشش",
    "friday_attendance": "جمعه‌کاری",
    "seniority_chain": "سنوات",
    "policy_eidi": "عیدی",
    "policy_bonus": "پاداش",
    "percent_insurance": "٪ بیمه",
    "percent_tax": "٪ مالیات",
    "child_allowance": "حق اولاد",
    "overtime_policy": "اضافه‌کار",
    "holiday_work": "تعطیل‌کاری",
    "work_deficit": "کسر کار",
    "shift_policy": "نوبت‌کاری",
    "night_work": "شب‌کاری",
}

STATUS_LABELS = {
    "draft": "پیش‌نویس",
    "calculated": "محاسبه‌شده",
    "approved": "تأییدشده",
    "published": "منتشرشده",
}


def _can_view(db: Session, user: User) -> bool:
    return has_permission(db, user, "view_payroll") or has_permission(db, user, "manage_payroll")


def _actor_names(db: Session, user_ids) -> dict:
    ids = list(dict.fromkeys(item for item in user_ids if item))
    if not ids:
        return {}
    employees = {
        row.user_id: row
        for row in db.query(Employee).filter(Employee.user_id.in_(ids)).all()
    }
    users = {
        row.user_id: row for row in db.query(User).filter(User.user_id.in_(ids)).all()
    }
    roles = role_label_map(db)
    labels = {}
    for uid in ids:
        emp = employees.get(uid)
        full = ""
        if emp:
            full = f"{(emp.first_name or '').strip()} {(emp.last_name or '').strip()}".strip()
        if not full:
            user_row = users.get(uid)
            full = (user_row.name or "").strip() if user_row else ""
        if not full:
            full = uid
        role_label = roles.get(users[uid].role, "") if uid in users else ""
        labels[uid] = f"{full} — {role_label}" if role_label else full
    return labels


def _can_mutate_run(user: User, run: PayrollRun) -> bool:
    """حذف و محاسبه فقط برای ایجادکننده؛ مدیر ارشد همیشه."""
    if user.role == "super_admin":
        return True
    if not run.created_by:
        return True
    return run.created_by == user.user_id


_MUTATE_DENIED = "فقط ایجادکنندهٔ این لیست می‌تواند آن را تغییر دهد"


def _can_manage(db: Session, user: User) -> bool:
    return has_permission(db, user, "manage_payroll")


def _can_approve(db: Session, user: User) -> bool:
    return has_permission(db, user, "approve_payroll")


def _deny():
    return RedirectResponse(url="/admin/?error=" + quote("دسترسی ندارید"), status_code=302)


def _redirect(url: str, *, error: str = "", success: str = "") -> RedirectResponse:
    sep = "&" if "?" in url else "?"
    if error:
        return RedirectResponse(url=f"{url}{sep}error={quote(error)}", status_code=302)
    if success:
        return RedirectResponse(url=f"{url}{sep}success={quote(success)}", status_code=302)
    return RedirectResponse(url=url, status_code=302)


def _dec(value: str, field: str = "مبلغ") -> Decimal:
    try:
        text = (value or "0").replace(",", "").strip()
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise PayrollPolicyError(f"{field} نامعتبر است")


def _parse_date(value: str) -> date:
    text = (value or "").strip().replace("-", "/")
    parts = text.split("/")
    if len(parts) != 3:
        raise PayrollPolicyError("تاریخ نامعتبر است")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    if y > 1500:
        return date(y, m, d)
    return jdatetime.date(y, m, d).togregorian()


# ---------- Operations ----------

@router.get("/admin/payroll", response_class=HTMLResponse)
async def payroll_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_view(db, user):
        return _deny()
    runs = run_service.list_runs(db)
    names = _actor_names(
        db,
        [run.created_by for run in runs] + [run.approved_by for run in runs],
    )
    return templates.TemplateResponse(
        request,
        "admin/payroll_list.html",
        {
            "user": user,
            "is_admin": True,
            "runs": runs,
            "actor_names": names,
            "status_labels": STATUS_LABELS,
            "can_manage": _can_manage(db, user),
            "mutable_run_ids": {run.id for run in runs if _can_mutate_run(user, run)},
            "is_super_admin": user.role == "super_admin",
            "error": request.query_params.get("error"),
            "success": request.query_params.get("success"),
        },
    )


@router.get("/admin/payroll/new", response_class=HTMLResponse)
async def payroll_new_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    today = jdatetime.date.today()
    memberships = policy_service.list_enabled_payroll_memberships(db)
    components = [
        comp
        for comp in policy_service.list_components(db)
        if comp.is_active and not comp.deleted_at
    ]
    return templates.TemplateResponse(
        request,
        "admin/payroll_new.html",
        {
            "user": user,
            "is_admin": True,
            "memberships": memberships,
            "components": components,
            "default_year": today.year,
            "default_month": today.month,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/admin/payroll/new")
async def payroll_new_submit(
    request: Request,
    year_j: int = Form(...),
    month_j: int = Form(...),
    membership_type_code: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    try:
        form = await request.form()
        codes = [str(item) for item in form.getlist("component_codes")]
        membership_code = membership_type_code.strip() or None
        if membership_code and not policy_service.is_payroll_membership_allowed(
            db, membership_code
        ):
            raise PayrollRunError("نوع عضویت انتخاب‌شده برای ایجاد حقوق مجاز نیست")
        run = run_service.create_run(
            db,
            year_j=year_j,
            month_j=month_j,
            membership_type_code=membership_code,
            created_by=user.user_id,
            notes=notes.strip() or None,
            component_codes=codes,
            calculate=False,
        )
        return _redirect(f"/admin/payroll/runs/{run.id}")
    except PayrollRunError as exc:
        return _redirect("/admin/payroll/new", error=str(exc))


@router.get("/admin/payroll/runs/{run_id}", response_class=HTMLResponse)
async def payroll_run_detail(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_view(db, user):
        return _deny()
    try:
        run = run_service.get_run(db, run_id)
    except PayrollRunError as exc:
        return _redirect("/admin/payroll", error=str(exc))
    manuals = {(m.user_id, m.component_code): m for m in run.manual_entries}
    names = _actor_names(db, [run.created_by, run.approved_by])
    chosen_codes = run_service.selected_component_codes(run)
    active_components = [
        comp
        for comp in policy_service.list_components(db)
        if comp.is_active and not comp.deleted_at
    ]
    if chosen_codes is None:
        chosen_components = active_components
    else:
        chosen_components = [comp for comp in active_components if comp.code in chosen_codes]
    return templates.TemplateResponse(
        request,
        "admin/payroll_run_detail.html",
        {
            "user": user,
            "is_admin": True,
            "run": run,
            "roster": run_service.shift_roster(db, run),
            "chosen_components": chosen_components,
            "components_explicit": chosen_codes is not None,
            "shift_options": SHIFT_OPTIONS,
            "shift_labels": PATTERN_LABELS,
            "status_labels": STATUS_LABELS,
            "manuals": manuals,
            "can_manage": _can_manage(db, user),
            "can_mutate_run": _can_mutate_run(user, run),
            "can_approve": _can_approve(db, user),
            "is_super_admin": user.role == "super_admin",
            "creator_name": names.get(run.created_by) if run.created_by else None,
            "approver_name": names.get(run.approved_by) if run.approved_by else None,
            "error": request.query_params.get("error"),
            "success": request.query_params.get("success"),
            "auto_calc": request.query_params.get("calc") == "1",
        },
    )


@router.post("/admin/payroll/runs/{run_id}/calculate-stream")
async def payroll_calculate_stream(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    try:
        run = run_service.get_run(db, run_id)
    except PayrollRunError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    if not _can_mutate_run(user, run):
        return JSONResponse({"ok": False, "error": _MUTATE_DENIED}, status_code=403)

    def events():
        stream_db = SessionLocal()
        try:
            for event in run_service.iter_calculate(stream_db, run_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            payload = {
                "done": True,
                "error": str(exc),
                "percent": 0,
                "name": "",
                "user_id": "",
                "index": 0,
                "total": 0,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/admin/payroll/runs/{run_id}/shift-choices")
async def payroll_shift_choices(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return JSONResponse({"ok": False, "error": "دسترسی ندارید"}, status_code=403)
    try:
        run = run_service.get_run(db, run_id)
        if not _can_mutate_run(user, run):
            return JSONResponse({"ok": False, "error": _MUTATE_DENIED}, status_code=403)
        payload = await request.json()
        raw = payload.get("choices") or []
        pairs = [(str(item.get("user_id") or ""), str(item.get("pattern") or "")) for item in raw]
        run_service.set_shift_choices(db, run_id, pairs)
        return JSONResponse({"ok": True})
    except PayrollRunError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/admin/payroll/runs/{run_id}/recalculate")
async def payroll_recalculate(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    try:
        run = run_service.get_run(db, run_id)
        if not _can_mutate_run(user, run):
            return _redirect(f"/admin/payroll/runs/{run_id}", error=_MUTATE_DENIED)
    except PayrollRunError as exc:
        return _redirect("/admin/payroll", error=str(exc))
    return _redirect(f"/admin/payroll/runs/{run_id}?calc=1")


@router.post("/admin/payroll/runs/{run_id}/delete")
async def payroll_delete(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not has_permission(db, user, "manage_payroll"):
        return _redirect("/admin/payroll", error="حذف لیست حقوق مجاز نیست")
    try:
        run = run_service.get_run(db, run_id)
        if not _can_mutate_run(user, run):
            return _redirect("/admin/payroll", error=_MUTATE_DENIED)
        run_service.delete_run(db, run_id)
        return _redirect("/admin/payroll", success="لیست حقوق حذف شد")
    except PayrollRunError as exc:
        return _redirect("/admin/payroll", error=str(exc))


@router.post("/admin/payroll/runs/{run_id}/approve")
async def payroll_approve(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_approve(db, user):
        return _deny()
    try:
        run_service.approve_run(db, run_id, user.user_id)
        return _redirect(f"/admin/payroll/runs/{run_id}", success="تأیید شد")
    except PayrollRunError as exc:
        return _redirect(f"/admin/payroll/runs/{run_id}", error=str(exc))


@router.post("/admin/payroll/runs/{run_id}/publish")
async def payroll_publish(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    try:
        run_service.publish_run(db, run_id, user.user_id)
        return _redirect(f"/admin/payroll/runs/{run_id}", success="منتشر شد")
    except PayrollRunError as exc:
        return _redirect(f"/admin/payroll/runs/{run_id}", error=str(exc))


@router.post("/admin/payroll/runs/{run_id}/manual")
async def payroll_manual(
    run_id: int,
    user_id: str = Form(...),
    amount: str = Form("0"),
    component_code: str = Form("SHIFT"),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user):
        return _deny()
    try:
        run_service.set_manual_entry(
            db,
            run_id,
            user_id.strip(),
            _dec(amount),
            component_code=component_code.strip() or "SHIFT",
            note=note.strip() or None,
        )
        return _redirect(f"/admin/payroll/runs/{run_id}?calc=1")
    except (PayrollRunError, PayrollPolicyError) as exc:
        return _redirect(f"/admin/payroll/runs/{run_id}", error=str(exc))


@router.get("/admin/payroll/payslip/{result_id}", response_class=HTMLResponse)
async def admin_payslip(
    result_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_view(db, user):
        return _deny()
    try:
        result = run_service.get_result(db, result_id)
    except PayrollRunError as exc:
        return _redirect("/admin/payroll", error=str(exc))
    period = result.run.period
    return templates.TemplateResponse(
        request,
        "payroll/payslip_detail.html",
        {
            "user": user,
            "is_admin": True,
            "result": result,
            "items": sorted(result.items, key=lambda i: i.sort_order),
            "period_label": f"{period.year_j}/{period.month_j:02d}",
            "profile": load_payslip_profile(db, result),
            "pdf_url": f"/admin/payroll/payslip/{result_id}/pdf",
            "back_url": f"/admin/payroll/runs/{result.run_id}",
        },
    )


@router.get("/admin/payroll/payslip/{result_id}/pdf")
async def admin_payslip_pdf(
    result_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_view(db, user):
        return _deny()
    result = run_service.get_result(db, result_id)
    period = result.run.period
    label = f"{period.year_j}/{period.month_j:02d}"
    data = build_payslip_pdf(
        result,
        result.items,
        label,
        profile=load_payslip_profile(db, result),
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip_{result_id}.pdf"'},
    )


# ---------- Policy ----------

@router.get("/admin/policies/payroll", response_class=HTMLResponse)
async def payroll_policy_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    memberships = (
        db.query(MembershipType)
        .filter(MembershipType.is_active.is_(True))
        .order_by(MembershipType.sort_order, MembershipType.code)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/policy_payroll.html",
        {
            "user": user,
            "is_admin": True,
            "is_super_admin": user.role == "super_admin",
            "payroll_run_membership_codes": policy_service.payroll_membership_selection_codes(db),
            "components": policy_service.list_components(db),
            "annual_laws": policy_service.list_annual_laws(db),
            "rates": policy_service.get_rate_settings(db),
            "assignments": policy_service.list_assignments(db),
            "memberships": memberships,
            "calc_mode_labels": CALC_MODE_LABELS,
            "child_policies": policy_service.list_child_policies(db),
            "minimum_wages": policy_service.list_minimum_wages(db),
            "overtime_policies": policy_service.list_overtime_policies(db),
            "deficit_policies": policy_service.list_deficit_policies(db),
            "shift_policies": policy_service.list_shift_policies(db),
            "night_policies": policy_service.list_night_policies(db),
            "night_exclude_options": [
                (code, label) for code, label in SHIFT_OPTIONS if code != PATTERN_NONE
            ],
            "night_pattern_labels": PATTERN_LABELS,
            "error": request.query_params.get("error"),
            "success": request.query_params.get("success"),
        },
    )


@router.post("/admin/policies/payroll/components/{component_id}/update")
async def payroll_component_update(
    component_id: int,
    name: str = Form(...),
    subject_to_insurance: Optional[str] = Form(None),
    subject_to_tax: Optional[str] = Form(None),
    sort_order: int = Form(100),
    is_active: Optional[str] = Form(None),
    calc_mode: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.update_component(
            db,
            component_id,
            name=name,
            subject_to_insurance=subject_to_insurance == "on",
            subject_to_tax=subject_to_tax == "on",
            sort_order=sort_order,
            is_active=is_active == "on",
            calc_mode=calc_mode.strip() or None,
        )
        return _redirect("/admin/policies/payroll", success="آیتم به‌روز شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/components/add")
async def payroll_component_add(
    code: str = Form(...),
    name: str = Form(...),
    kind: str = Form("earning"),
    calc_mode: str = Form("manual"),
    subject_to_insurance: Optional[str] = Form(None),
    subject_to_tax: Optional[str] = Form(None),
    sort_order: int = Form(100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.create_component(
            db,
            code=code,
            name=name,
            kind=kind,
            calc_mode=calc_mode,
            subject_to_insurance=subject_to_insurance == "on",
            subject_to_tax=subject_to_tax == "on",
            sort_order=sort_order,
        )
        return _redirect("/admin/policies/payroll", success="آیتم افزوده شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/components/{component_id}/delete")
async def payroll_component_delete(
    component_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.soft_delete_component(db, component_id)
        return _redirect("/admin/policies/payroll", success="آیتم حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/rates")
async def payroll_rates_save(
    insurance_employee_pct: str = Form("7"),
    tax_pct: str = Form("0"),
    friday_coefficient: str = Form("1.96"),
    eidi_payment_month: int = Form(12),
    bonus_payment_month: int = Form(12),
    eidi_day_factor: str = Form("60"),
    bonus_day_factor: str = Form("0"),
    hours_per_day: str = Form("7.3333"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.update_rate_settings(
            db,
            insurance_employee_pct=_dec(insurance_employee_pct, "درصد بیمه"),
            tax_pct=_dec(tax_pct, "درصد مالیات"),
            friday_coefficient=_dec(friday_coefficient, "ضریب جمعه"),
            eidi_payment_month=eidi_payment_month,
            bonus_payment_month=bonus_payment_month,
            eidi_day_factor=_dec(eidi_day_factor, "ضریب عیدی"),
            bonus_day_factor=_dec(bonus_day_factor, "ضریب پاداش"),
            hours_per_day=_dec(hours_per_day, "ساعت روزانه"),
        )
        return _redirect("/admin/policies/payroll", success="نرخ‌ها ذخیره شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/annual-laws/seed-official")
async def payroll_annual_laws_seed_official(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    from web.services.payroll.seed import ensure_official_seniority_laws

    ensure_official_seniority_laws(db, overwrite=True)
    return _redirect("/admin/policies/payroll", success="قوانین رسمی پایه سنوات بارگذاری شد")


@router.post("/admin/policies/payroll/annual-laws")
async def payroll_annual_law_save(
    year_j: int = Form(...),
    new_seniority_daily: str = Form(...),
    wage_increase_factor: str = Form("1"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    version: str = Form("1"),
    source_reference: str = Form(""),
    law_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        et = _parse_date(effective_to) if effective_to.strip() else None
        policy_service.upsert_annual_law(
            db,
            year_j=year_j,
            new_seniority_daily=_dec(new_seniority_daily, "پایه سنوات جدید"),
            wage_increase_factor=_dec(wage_increase_factor, "ضریب افزایش"),
            effective_from=_parse_date(effective_from),
            effective_to=et,
            version=version.strip() or "1",
            source_reference=source_reference.strip() or None,
            law_id=int(law_id) if law_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll", success="قانون سالانه ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/annual-laws/{law_id}/delete")
async def payroll_annual_law_delete(
    law_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_annual_law(db, law_id)
        return _redirect("/admin/policies/payroll", success="حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/assignments")
async def payroll_assignment_add(
    component_id: int = Form(...),
    scope: str = Form("membership"),
    membership_type_code: str = Form(""),
    user_id: str = Form(""),
    amount: str = Form(...),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        et = _parse_date(effective_to) if effective_to.strip() else None
        policy_service.create_assignment(
            db,
            component_id=component_id,
            amount=_dec(amount),
            effective_from=_parse_date(effective_from),
            membership_type_code=membership_type_code.strip() or None
            if scope == "membership"
            else None,
            user_id=user_id.strip() or None if scope == "user" else None,
            effective_to=et,
            notes=notes.strip() or None,
        )
        return _redirect("/admin/policies/payroll", success="تخصیص افزوده شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


@router.post("/admin/policies/payroll/assignments/{assignment_id}/delete")
async def payroll_assignment_delete(
    assignment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_assignment(db, assignment_id)
        return _redirect("/admin/policies/payroll", success="تخصیص حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll", error=str(exc))


def _flag(value: Optional[str]) -> bool:
    return value in ("on", "true", "1")


@router.post("/admin/policies/payroll/minimum-wages")
async def payroll_minimum_wage_save(
    year_j: int = Form(...),
    daily_amount: str = Form(...),
    effective_from: str = Form(...),
    source_reference: str = Form(""),
    membership_type_code: str = Form(""),
    wage_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.upsert_minimum_wage(
            db,
            year_j=year_j,
            daily_amount=_dec(daily_amount, "حداقل مزد"),
            effective_from=_parse_date(effective_from),
            source_reference=source_reference.strip() or None,
            membership_type_code=membership_type_code.strip() or None,
            wage_id=int(wage_id) if wage_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=child", success="حداقل مزد ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=child", error=str(exc))


@router.post("/admin/policies/payroll/minimum-wages/{wage_id}/delete")
async def payroll_minimum_wage_delete(
    wage_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_minimum_wage(db, wage_id)
        return _redirect("/admin/policies/payroll?tab=child", success="حداقل مزد حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=child", error=str(exc))


@router.post("/admin/policies/payroll/child-allowance")
async def payroll_child_policy_save(
    membership_type_code: str = Form(...),
    age_limit_years: int = Form(18),
    wage_day_multiplier: str = Form("3"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    policy_id: str = Form(""),
    applies_to_female: Optional[str] = Form(None),
    require_study_above_age: Optional[str] = Form(None),
    count_only_verified: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        et = _parse_date(effective_to) if effective_to.strip() else None
        policy_service.upsert_child_policy(
            db,
            membership_type_code=membership_type_code.strip(),
            applies_to_female=_flag(applies_to_female),
            age_limit_years=age_limit_years,
            require_study_above_age=_flag(require_study_above_age),
            wage_day_multiplier=_dec(wage_day_multiplier, "ضریب"),
            count_only_verified=_flag(count_only_verified),
            effective_from=_parse_date(effective_from),
            effective_to=et,
            notes=notes.strip() or None,
            policy_id=int(policy_id) if policy_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=child", success="سیاست حق اولاد ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=child", error=str(exc))


@router.post("/admin/policies/payroll/child-allowance/{policy_id}/delete")
async def payroll_child_policy_delete(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_child_policy(db, policy_id)
        return _redirect("/admin/policies/payroll?tab=child", success="سیاست حق اولاد حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=child", error=str(exc))


@router.post("/admin/policies/payroll/overtime")
async def payroll_overtime_policy_save(
    request: Request,
    membership_type_code: str = Form(...),
    method: str = Form("monthly_div"),
    divisor: str = Form("157"),
    premium_factor: str = Form("1.4"),
    ordinary_month_hours: str = Form("220"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    policy_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        form = await request.form()
        codes = [str(item) for item in form.getlist("basis_codes")]
        policy_service.upsert_overtime_policy(
            db,
            membership_type_code=membership_type_code.strip(),
            method=method.strip(),
            basis_codes=codes,
            divisor=_dec(divisor, "عدد ثابت"),
            premium_factor=_dec(premium_factor, "ضریب"),
            ordinary_month_hours=_dec(ordinary_month_hours, "ساعت عادی ماه"),
            effective_from=_parse_date(effective_from),
            effective_to=_parse_date(effective_to) if effective_to.strip() else None,
            notes=notes.strip() or None,
            policy_id=int(policy_id) if policy_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=overtime", success="سیاست اضافه‌کار ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=overtime", error=str(exc))


@router.post("/admin/policies/payroll/overtime/{policy_id}/delete")
async def payroll_overtime_policy_delete(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_overtime_policy(db, policy_id)
        return _redirect("/admin/policies/payroll?tab=overtime", success="سیاست اضافه‌کار حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=overtime", error=str(exc))


@router.post("/admin/policies/payroll/deficit")
async def payroll_deficit_policy_save(
    request: Request,
    membership_type_code: str = Form(...),
    ordinary_month_hours: str = Form("220"),
    basis_days: str = Form("30"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    policy_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        form = await request.form()
        codes = [str(item) for item in form.getlist("basis_codes")]
        policy_service.upsert_deficit_policy(
            db,
            membership_type_code=membership_type_code.strip(),
            basis_codes=codes,
            ordinary_month_hours=_dec(ordinary_month_hours, "ساعت عادی ماه"),
            basis_days=_dec(basis_days, "روز مبنا"),
            effective_from=_parse_date(effective_from),
            effective_to=_parse_date(effective_to) if effective_to.strip() else None,
            notes=notes.strip() or None,
            policy_id=int(policy_id) if policy_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=deficit", success="سیاست کسر کار ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=deficit", error=str(exc))


@router.post("/admin/policies/payroll/deficit/{policy_id}/delete")
async def payroll_deficit_policy_delete(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_deficit_policy(db, policy_id)
        return _redirect("/admin/policies/payroll?tab=deficit", success="سیاست کسر کار حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=deficit", error=str(exc))


@router.post("/admin/policies/payroll/shift")
async def payroll_shift_policy_save(
    request: Request,
    membership_type_code: str = Form(...),
    pct_morning_evening: str = Form("10"),
    pct_morning_evening_night: str = Form("15"),
    pct_morning_night: str = Form("22.5"),
    pct_evening_night: str = Form("22.5"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    policy_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        form = await request.form()
        codes = [str(item) for item in form.getlist("basis_codes")]
        policy_service.upsert_shift_policy(
            db,
            membership_type_code=membership_type_code.strip(),
            basis_codes=codes,
            pct_morning_evening=_dec(pct_morning_evening, "درصد صبح و عصر"),
            pct_morning_evening_night=_dec(pct_morning_evening_night, "درصد صبح عصر شب"),
            pct_morning_night=_dec(pct_morning_night, "درصد صبح و شب"),
            pct_evening_night=_dec(pct_evening_night, "درصد عصر و شب"),
            effective_from=_parse_date(effective_from),
            effective_to=_parse_date(effective_to) if effective_to.strip() else None,
            notes=notes.strip() or None,
            policy_id=int(policy_id) if policy_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=shift", success="سیاست نوبت‌کاری ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=shift", error=str(exc))


@router.post("/admin/policies/payroll/shift/{policy_id}/delete")
async def payroll_shift_policy_delete(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_shift_policy(db, policy_id)
        return _redirect("/admin/policies/payroll?tab=shift", success="سیاست نوبت‌کاری حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=shift", error=str(exc))


@router.post("/admin/policies/payroll/night")
async def payroll_night_policy_save(
    request: Request,
    membership_type_code: str = Form(...),
    premium_percent: str = Form("35"),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    notes: str = Form(""),
    policy_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        form = await request.form()
        patterns = [str(item) for item in form.getlist("excluded_patterns")]
        policy_service.upsert_night_policy(
            db,
            membership_type_code=membership_type_code.strip(),
            premium_percent=_dec(premium_percent, "درصد شب‌کاری"),
            excluded_patterns=patterns,
            effective_from=_parse_date(effective_from),
            effective_to=_parse_date(effective_to) if effective_to.strip() else None,
            notes=notes.strip() or None,
            policy_id=int(policy_id) if policy_id.strip() else None,
        )
        return _redirect("/admin/policies/payroll?tab=night", success="سیاست شب‌کاری ذخیره شد")
    except (PayrollPolicyError, ValueError) as exc:
        return _redirect("/admin/policies/payroll?tab=night", error=str(exc))


@router.post("/admin/policies/payroll/night/{policy_id}/delete")
async def payroll_night_policy_delete(
    policy_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        policy_service.delete_night_policy(db, policy_id)
        return _redirect("/admin/policies/payroll?tab=night", success="سیاست شب‌کاری حذف شد")
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=night", error=str(exc))


@router.post("/admin/policies/payroll/run-memberships")
async def payroll_run_memberships_save(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(db, user) and not has_permission(db, user, "manage_users"):
        return _deny()
    try:
        form = await request.form()
        codes = [str(item) for item in form.getlist("membership_codes")]
        policy_service.save_payroll_enabled_memberships(db, codes)
        return _redirect(
            "/admin/policies/payroll?tab=run_memberships",
            success="عضویت‌های مجاز برای ایجاد حقوق ذخیره شد",
        )
    except PayrollPolicyError as exc:
        return _redirect("/admin/policies/payroll?tab=run_memberships", error=str(exc))
