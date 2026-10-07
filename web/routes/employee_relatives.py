"""
مدیریت بستگان کارکنان — خودخدمتی کاربر + پنل ادمین (تأیید/رد)
"""
from datetime import date
from typing import Any, Dict, Optional
from urllib.parse import quote

import jdatetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_current_user, get_db, require_admin
from web.permissions import enforce_permission
from web.services.employee_relative_service import (
    EmployeeRelativeServiceError,
    create_relative,
    reject_relative,
    soft_delete_relative,
    update_relative,
    verify_relative,
)

router = APIRouter(tags=["Employee Relatives"])


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=302)


def _service_redirect(base: str, exc: Exception) -> RedirectResponse:
    if isinstance(exc, EmployeeRelativeServiceError):
        msg = str(exc)
    else:
        msg = f"خطا: {exc}"
    return _redirect(f"{base}?error={quote(msg)}")


def _opt(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: str) -> Optional[date]:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if "/" in text:
        try:
            return jdatetime.datetime.strptime(text, "%Y/%m/%d").date().togregorian()
        except ValueError as exc:
            raise EmployeeRelativeServiceError(
                "فرمت تاریخ نامعتبر است (مثال: 1405/06/30)"
            ) from exc
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise EmployeeRelativeServiceError(
            "فرمت تاریخ نامعتبر است (مثال: 1405/06/30)"
        ) from exc


def _parse_optional_tri_state(value: str) -> Optional[bool]:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    if text in ("unknown",):
        return None
    raise EmployeeRelativeServiceError("مقدار وضعیت نامعتبر است")


def _relative_kwargs_from_form(
    *,
    first_name: str,
    last_name: str,
    relationship_type: str,
    father_name: str = "",
    national_code: str = "",
    birth_date: str = "",
    gender: str = "",
    marital_status: str = "",
    marriage_date: str = "",
    divorce_date: str = "",
    death_date: str = "",
    is_studying: str = "",
    study_start_date: str = "",
    study_end_date: str = "",
    employment_status: str = "",
    insurance_status: str = "",
    is_disabled: str = "",
    disability_start_date: str = "",
    disability_end_date: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "first_name": first_name,
        "last_name": last_name,
        "relationship_type": relationship_type,
        "father_name": _opt(father_name),
        "national_code": _opt(national_code),
        "birth_date": _parse_date(birth_date),
        "gender": _opt(gender),
        "marital_status": _opt(marital_status),
        "marriage_date": _parse_date(marriage_date),
        "divorce_date": _parse_date(divorce_date),
        "death_date": _parse_date(death_date),
        "is_studying": _parse_optional_tri_state(is_studying),
        "study_start_date": _parse_date(study_start_date),
        "study_end_date": _parse_date(study_end_date),
        "employment_status": _opt(employment_status),
        "insurance_status": _opt(insurance_status),
        "is_disabled": _parse_optional_tri_state(is_disabled),
        "disability_start_date": _parse_date(disability_start_date),
        "disability_end_date": _parse_date(disability_end_date),
        "notes": _opt(notes),
    }


_FORM_FIELDS = (
    "first_name", "last_name", "relationship_type", "father_name",
    "national_code", "birth_date", "gender", "marital_status",
    "marriage_date", "divorce_date", "death_date", "is_studying",
    "study_start_date", "study_end_date", "employment_status",
    "insurance_status", "is_disabled", "disability_start_date",
    "disability_end_date", "notes",
)


# ---------------------------------------------------------------------------
# Self-service
# ---------------------------------------------------------------------------

@router.post("/profile/relatives/add")
async def self_add_relative(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_type: str = Form(...),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    marriage_date: str = Form(""),
    divorce_date: str = Form(""),
    death_date: str = Form(""),
    is_studying: str = Form(""),
    study_start_date: str = Form(""),
    study_end_date: str = Form(""),
    employment_status: str = Form(""),
    insurance_status: str = Form(""),
    is_disabled: str = Form(""),
    disability_start_date: str = Form(""),
    disability_end_date: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = "/profile"
    try:
        kwargs = _relative_kwargs_from_form(
            first_name=first_name, last_name=last_name,
            relationship_type=relationship_type, father_name=father_name,
            national_code=national_code, birth_date=birth_date, gender=gender,
            marital_status=marital_status, marriage_date=marriage_date,
            divorce_date=divorce_date, death_date=death_date,
            is_studying=is_studying, study_start_date=study_start_date,
            study_end_date=study_end_date, employment_status=employment_status,
            insurance_status=insurance_status, is_disabled=is_disabled,
            disability_start_date=disability_start_date,
            disability_end_date=disability_end_date, notes=notes,
        )
        create_relative(
            db,
            user_id=user.user_id,
            created_by=user.user_id,
            submitted_by=user.user_id,
            status="PENDING",
            **kwargs,
        )
        return _redirect(
            f"{base}?success={quote('فرد وابسته ثبت شد و در انتظار تأیید است')}"
        )
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/profile/relatives/{relative_id}/update")
async def self_update_relative(
    request: Request,
    relative_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_type: str = Form(...),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    marriage_date: str = Form(""),
    divorce_date: str = Form(""),
    death_date: str = Form(""),
    is_studying: str = Form(""),
    study_start_date: str = Form(""),
    study_end_date: str = Form(""),
    employment_status: str = Form(""),
    insurance_status: str = Form(""),
    is_disabled: str = Form(""),
    disability_start_date: str = Form(""),
    disability_end_date: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = "/profile"
    try:
        kwargs = _relative_kwargs_from_form(
            first_name=first_name, last_name=last_name,
            relationship_type=relationship_type, father_name=father_name,
            national_code=national_code, birth_date=birth_date, gender=gender,
            marital_status=marital_status, marriage_date=marriage_date,
            divorce_date=divorce_date, death_date=death_date,
            is_studying=is_studying, study_start_date=study_start_date,
            study_end_date=study_end_date, employment_status=employment_status,
            insurance_status=insurance_status, is_disabled=is_disabled,
            disability_start_date=disability_start_date,
            disability_end_date=disability_end_date, notes=notes,
        )
        update_relative(
            db,
            user_id=user.user_id,
            relative_id=relative_id,
            reset_verification=True,
            **kwargs,
        )
        return _redirect(
            f"{base}?success={quote('اطلاعات به‌روزرسانی شد (در انتظار تأیید مجدد)')}"
        )
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/profile/relatives/{relative_id}/delete")
async def self_delete_relative(
    request: Request,
    relative_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = "/profile"
    try:
        soft_delete_relative(
            db,
            user_id=user.user_id,
            relative_id=relative_id,
            deleted_by=user.user_id,
            allow_verified=False,
        )
        return _redirect(f"{base}?success={quote('فرد وابسته حذف شد')}")
    except Exception as exc:
        return _service_redirect(base, exc)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@router.post("/admin/profile/{target_user_id}/relatives/add")
async def admin_add_relative(
    request: Request,
    target_user_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_type: str = Form(...),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    marriage_date: str = Form(""),
    divorce_date: str = Form(""),
    death_date: str = Form(""),
    is_studying: str = Form(""),
    study_start_date: str = Form(""),
    study_end_date: str = Form(""),
    employment_status: str = Form(""),
    insurance_status: str = Form(""),
    is_disabled: str = Form(""),
    disability_start_date: str = Form(""),
    disability_end_date: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_relatives")
    base = f"/admin/profile/{target_user_id}"
    try:
        kwargs = _relative_kwargs_from_form(
            first_name=first_name, last_name=last_name,
            relationship_type=relationship_type, father_name=father_name,
            national_code=national_code, birth_date=birth_date, gender=gender,
            marital_status=marital_status, marriage_date=marriage_date,
            divorce_date=divorce_date, death_date=death_date,
            is_studying=is_studying, study_start_date=study_start_date,
            study_end_date=study_end_date, employment_status=employment_status,
            insurance_status=insurance_status, is_disabled=is_disabled,
            disability_start_date=disability_start_date,
            disability_end_date=disability_end_date, notes=notes,
        )
        create_relative(
            db,
            user_id=target_user_id,
            created_by=user.user_id,
            submitted_by=user.user_id,
            status="VERIFIED",
            **kwargs,
        )
        return _redirect(f"{base}?success={quote('فرد وابسته با موفقیت اضافه شد')}")
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/admin/profile/{target_user_id}/relatives/{relative_id}/update")
async def admin_update_relative(
    request: Request,
    target_user_id: str,
    relative_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    relationship_type: str = Form(...),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    marriage_date: str = Form(""),
    divorce_date: str = Form(""),
    death_date: str = Form(""),
    is_studying: str = Form(""),
    study_start_date: str = Form(""),
    study_end_date: str = Form(""),
    employment_status: str = Form(""),
    insurance_status: str = Form(""),
    is_disabled: str = Form(""),
    disability_start_date: str = Form(""),
    disability_end_date: str = Form(""),
    notes: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_relatives")
    base = f"/admin/profile/{target_user_id}"
    try:
        kwargs = _relative_kwargs_from_form(
            first_name=first_name, last_name=last_name,
            relationship_type=relationship_type, father_name=father_name,
            national_code=national_code, birth_date=birth_date, gender=gender,
            marital_status=marital_status, marriage_date=marriage_date,
            divorce_date=divorce_date, death_date=death_date,
            is_studying=is_studying, study_start_date=study_start_date,
            study_end_date=study_end_date, employment_status=employment_status,
            insurance_status=insurance_status, is_disabled=is_disabled,
            disability_start_date=disability_start_date,
            disability_end_date=disability_end_date, notes=notes,
        )
        update_relative(
            db,
            user_id=target_user_id,
            relative_id=relative_id,
            reset_verification=False,
            **kwargs,
        )
        return _redirect(f"{base}?success={quote('اطلاعات فرد وابسته به‌روزرسانی شد')}")
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/admin/profile/{target_user_id}/relatives/{relative_id}/delete")
async def admin_delete_relative(
    request: Request,
    target_user_id: str,
    relative_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "manage_employee_relatives")
    base = f"/admin/profile/{target_user_id}"
    try:
        soft_delete_relative(
            db,
            user_id=target_user_id,
            relative_id=relative_id,
            deleted_by=user.user_id,
            allow_verified=True,
        )
        return _redirect(
            f"{base}?success={quote('فرد وابسته از لیست فعال حذف شد')}"
        )
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/admin/profile/{target_user_id}/relatives/{relative_id}/verify")
async def admin_verify_relative(
    request: Request,
    target_user_id: str,
    relative_id: int,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_relatives")
    base = f"/admin/profile/{target_user_id}"
    try:
        verify_relative(
            db,
            user_id=target_user_id,
            relative_id=relative_id,
            verified_by=user.user_id,
        )
        return _redirect(f"{base}?success={quote('فرد وابسته تأیید شد')}")
    except Exception as exc:
        return _service_redirect(base, exc)


@router.post("/admin/profile/{target_user_id}/relatives/{relative_id}/reject")
async def admin_reject_relative(
    request: Request,
    target_user_id: str,
    relative_id: int,
    rejection_reason: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enforce_permission(db, user, "verify_employee_relatives")
    base = f"/admin/profile/{target_user_id}"
    try:
        reject_relative(
            db,
            user_id=target_user_id,
            relative_id=relative_id,
            rejected_by=user.user_id,
            reason=rejection_reason,
        )
        return _redirect(f"{base}?success={quote('فرد وابسته رد شد')}")
    except Exception as exc:
        return _service_redirect(base, exc)
