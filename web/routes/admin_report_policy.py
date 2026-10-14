"""
سیاست گزارش — کارت مستقل در سیاست کلی (v1: اضافه‌کار قانونی).
فقط با مجوز manage_policies (الگوی سایر سیاست‌ها).
"""
from pathlib import Path

import jdatetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_db, require_permission
from web.permissions import has_permission
from web.services.report_policy_service import (
    LEGAL_OVERTIME_MONTHLY,
    REPORT_DEFINITIONS,
    ReportPolicyError,
    create_policy_version,
    list_versions,
    resolve_report_policy,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

_LEGAL_OT_URL = "/admin/policies/reports/legal-overtime"

# توضیح فارسی گزینه‌های قابل ویرایش
LEGAL_OT_FIELDS = (
    ("deficit_adjust_ordinary_overtime", "اضافه‌کار عادی در تعدیل کسر کار"),
    ("deficit_adjust_holiday_work", "تعطیل‌کاری در تعدیل کسر کار"),
    ("deficit_adjust_friday_work", "جمعه‌کاری در تعدیل کسر کار"),
)


def _j(d) -> str:
    return jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d") if d else ""


def _parse_jalali(value: str):
    try:
        y, m, d = (int(x) for x in value.strip().replace("-", "/").split("/"))
        return jdatetime.date(y, m, d).togregorian()
    except Exception:
        raise ReportPolicyError("تاریخ شروع نامعتبر است (قالب 1405/01/01)")


def _guard(db: Session, user: User):
    if not has_permission(db, user, "manage_users"):
        return RedirectResponse(url="/admin/", status_code=302)
    return None


@router.get("/admin/policies/reports", response_class=HTMLResponse)
async def admin_report_policies(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("manage_policies")),
):
    denied = _guard(db, user)
    if denied:
        return denied
    from datetime import date
    rows = []
    for key, definition in REPORT_DEFINITIONS.items():
        resolved = resolve_report_policy(db, key, date.today())
        rows.append({"key": key, "label": definition.label, "policy": resolved})
    return templates.TemplateResponse(request, "admin/policy_reports.html", {
        "user": user, "is_admin": True, "is_super_admin": True, "rows": rows,
    })


@router.get(_LEGAL_OT_URL, response_class=HTMLResponse)
async def admin_report_policy_legal_ot(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("manage_policies")),
):
    denied = _guard(db, user)
    if denied:
        return denied
    from datetime import date
    current = resolve_report_policy(db, LEGAL_OVERTIME_MONTHLY, date.today())
    versions = [
        {
            "id": v.id,
            "from": _j(v.effective_from_date),
            "to": _j(v.effective_to_date),
            "active": v.is_active,
            "settings": v.settings,
            "notes": v.notes or "",
            "created_by": v.created_by or "",
        }
        for v in list_versions(db, LEGAL_OVERTIME_MONTHLY)
    ]
    return templates.TemplateResponse(request, "admin/policy_report_legal_ot.html", {
        "user": user, "is_admin": True, "is_super_admin": True,
        "current": current, "versions": versions, "fields": LEGAL_OT_FIELDS,
        "error": request.query_params.get("error"),
    })


@router.post(_LEGAL_OT_URL + "/save")
async def admin_report_policy_legal_ot_save(
    request: Request,
    effective_from: str = Form(""),
    notes: str = Form(""),
    deficit_adjust_ordinary_overtime: str = Form(""),
    deficit_adjust_holiday_work: str = Form(""),
    deficit_adjust_friday_work: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("manage_policies")),
):
    denied = _guard(db, user)
    if denied:
        return denied
    try:
        from_date = _parse_jalali(effective_from)
        current = resolve_report_policy(db, LEGAL_OVERTIME_MONTHLY, from_date)
        # فقط گزینه‌های قابل ویرایش از فرم؛ بقیهٔ تنظیمات از نسخهٔ مؤثر حفظ می‌شود
        settings = dict(current.settings)
        settings.update({
            "deficit_adjust_ordinary_overtime": deficit_adjust_ordinary_overtime == "on",
            "deficit_adjust_holiday_work": deficit_adjust_holiday_work == "on",
            "deficit_adjust_friday_work": deficit_adjust_friday_work == "on",
        })
        create_policy_version(
            db, LEGAL_OVERTIME_MONTHLY, settings, from_date,
            changed_by=user.user_id, notes=notes.strip() or None,
        )
        db.commit()
    except ReportPolicyError as exc:
        db.rollback()
        from urllib.parse import quote
        return RedirectResponse(url=f"{_LEGAL_OT_URL}?error={quote(str(exc))}", status_code=302)
    return RedirectResponse(url=f"{_LEGAL_OT_URL}?success=saved", status_code=302)
