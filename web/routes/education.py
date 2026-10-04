"""
روتر تحصیلات (بخش کاربر و ادمین)
"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime
from datetime import date

from web.dependencies import get_db, get_current_user, require_admin, check_password_change
from web.permissions import enforce_permission, has_permission
from models.user import User
from models.employee import Employee
from models.education import Education, EDUCATION_GROUPS, DEGREE_LEVELS, DEGREE_PRIORITY
from web.services.file_storage import FileStorageError
from web.services.storage_activation import (
    delete_media_file,
    resolve_media_disk,
    save_media_bytes,
)

router = APIRouter(tags=["Education"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 مگابایت


def _store_certificate(content: bytes, original_filename: str) -> str:
    """Save certificate into Unified Storage; return storage_key."""
    try:
        return save_media_bytes(
            "education",
            content,
            original_filename=original_filename,
        )
    except FileStorageError as exc:
        if exc.code == "invalid_extension":
            raise ValueError("نوع فایل مجاز نیست (فقط JPG/PNG/PDF)") from exc
        if exc.code == "file_too_large":
            raise ValueError("حجم فایل بیش از 5 مگابایت است") from exc
        if exc.code == "empty_file":
            raise ValueError("فایل خالی است") from exc
        raise ValueError(str(exc)) from exc


def _apply_certificate_bytes(edu: Education, content: bytes, original_filename: str):
    """Save new certificate and point ``edu`` at it without deleting the old file.

    Returns ``(old_path_or_none, new_storage_key)``. Caller must commit DB first,
    then delete ``old_path``; on failure, delete ``new_storage_key`` and rollback.
    """
    old_path = edu.certificate_path
    ext = Path(original_filename or "").suffix.lower()
    new_key = _store_certificate(content, original_filename)
    edu.certificate_type = "pdf" if ext == ".pdf" else "image"
    edu.certificate_path = new_key
    return old_path, new_key


def update_highest_degree(db: Session, user_id: str):
    """به‌روزرسانی بالاترین مدرک کاربر"""
    educations = db.query(Education).filter(Education.user_id == user_id).all()

    if not educations:
        return

    # پیدا کردن بالاترین مدرک بر اساس اولویت
    highest = max(educations, key=lambda e: DEGREE_PRIORITY.get(e.degree_level, 0))

    # ریست کردن همه
    for edu in educations:
        edu.is_highest = False

    # تنظیم بالاترین
    highest.is_highest = True


# ============================================
# بخش کاربر
# ============================================

@router.get("/education", response_class=HTMLResponse)
async def education_list(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """لیست مدارک تحصیلی کاربر"""
    educations = db.query(Education).filter(
        Education.user_id == user.user_id
    ).order_by(Education.graduation_date.desc()).all()

    # تبدیل تاریخ‌ها به شمسی
    education_list = []
    for edu in educations:
        j_date = jdatetime.date.fromgregorian(date=edu.graduation_date)
        education_list.append({
            'id': edu.id,
            'education_group_name': edu.education_group_name,
            'degree_level_name': edu.degree_level_name,
            'major': edu.major,
            'graduation_date_j': j_date.strftime('%Y/%m/%d'),
            'certificate_path': edu.certificate_path,
            'certificate_type': edu.certificate_type,
            'is_highest': edu.is_highest,
            'verified': edu.verified,
            'notes': edu.notes,
        })

    return templates.TemplateResponse(request, "education/list.html", {
        "user": user,
        "educations": education_list,
        "total_count": len(education_list),
        "is_admin": user.is_admin,
    })


@router.get("/education/{edu_id}/file")
async def education_certificate_file(
        edu_id: int,
        user: User = Depends(check_password_change),
        db: Session = Depends(get_db),
):
    """دانلود امن مدرک تحصیلی از Unified Storage (یا legacy سازگار)."""
    edu = db.query(Education).filter(Education.id == edu_id).first()
    if not edu or not edu.certificate_path:
        return RedirectResponse(url="/education?error=فایل مدرک یافت نشد", status_code=302)

    is_owner = edu.user_id == user.user_id
    is_admin_viewer = user.is_admin and has_permission(db, user, "view_dashboard")
    if not is_owner and not is_admin_viewer:
        return RedirectResponse(url="/education?error=دسترسی غیرمجاز", status_code=302)

    try:
        disk = resolve_media_disk(edu.certificate_path)
    except Exception:
        return RedirectResponse(url="/education?error=فایل مدرک یافت نشد", status_code=302)

    if not disk.is_file():
        return RedirectResponse(
            url="/education?error=فایل مدرک روی دیسک موجود نیست",
            status_code=302,
        )

    media = "application/pdf" if disk.suffix.lower() == ".pdf" else None
    return FileResponse(
        path=str(disk),
        filename=disk.name,
        media_type=media,
        content_disposition_type="inline",
    )


@router.get("/education/new", response_class=HTMLResponse)
async def education_new_form(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """فرم افزودن مدرک جدید"""
    return templates.TemplateResponse(request, "education/form.html", {
        "user": user,
        "education": None,
        "education_groups": EDUCATION_GROUPS,
        "degree_levels": DEGREE_LEVELS,
        "is_edit": False,
        "is_admin": user.is_admin,
    })


@router.post("/education")
async def education_create(
        request: Request,
        education_group: str = Form(...),
        degree_level: str = Form(...),
        major: str = Form(...),
        graduation_date_str: str = Form(...),
        notes: str = Form(""),
        certificate: UploadFile = File(None),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """ثبت مدرک جدید"""
    try:
        # اعتبارسنجی فیلدها
        if education_group not in EDUCATION_GROUPS:
            raise ValueError("گروه تحصیلی نامعتبر است")
        if degree_level not in DEGREE_LEVELS:
            raise ValueError("مقطع تحصیلی نامعتبر است")
        if not major.strip():
            raise ValueError("رشته تحصیلی الزامی است")

        # تبدیل تاریخ شمسی به میلادی
        j_date = jdatetime.datetime.strptime(graduation_date_str.strip(), "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        # ایجاد رکورد اولیه (برای دریافت id)
        new_edu = Education(
            user_id=user.user_id,
            education_group=education_group,
            degree_level=degree_level,
            major=major.strip(),
            graduation_date=g_date,
            notes=notes.strip() or None,
            verified=False,
        )
        db.add(new_edu)
        db.flush()  # 🆕 دریافت id بدون commit

        new_key = None
        try:
            if certificate and certificate.filename:
                ext = Path(certificate.filename).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    db.rollback()
                    return RedirectResponse(
                        url="/education/new?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                        status_code=302
                    )
                content = await certificate.read()
                if len(content) > MAX_FILE_SIZE:
                    db.rollback()
                    return RedirectResponse(
                        url="/education/new?error=حجم فایل بیش از 5 مگابایت است",
                        status_code=302
                    )
                _, new_key = _apply_certificate_bytes(new_edu, content, certificate.filename)

            db.commit()
        except Exception:
            db.rollback()
            if new_key:
                delete_media_file(new_key)
            raise

        # به‌روزرسانی بالاترین مدرک
        update_highest_degree(db, user.user_id)
        db.commit()

        return RedirectResponse(url="/education?success=مدرک با موفقیت ثبت شد", status_code=302)
    except ValueError as e:
        db.rollback()
        return RedirectResponse(url=f"/education/new?error={str(e)}", status_code=302)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/education/new?error=خطا: {str(e)}", status_code=302)

@router.get("/education/{edu_id}/edit", response_class=HTMLResponse)
async def education_edit_form(
        request: Request,
        edu_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """فرم ویرایش مدرک"""
    edu = db.query(Education).filter(
        and_(Education.id == edu_id, Education.user_id == user.user_id)
    ).first()

    if not edu:
        return RedirectResponse(url="/education?error=مدرک یافت نشد", status_code=302)

    # فقط مدارک تایید نشده قابل ویرایش هستند
    if edu.verified:
        return RedirectResponse(url="/education?error=مدارک تایید شده قابل ویرایش نیستند", status_code=302)

    j_date = jdatetime.date.fromgregorian(date=edu.graduation_date)

    return templates.TemplateResponse(request, "education/form.html", {
        "user": user,
        "education": edu,
        "graduation_date_j": j_date.strftime('%Y/%m/%d'),
        "education_groups": EDUCATION_GROUPS,
        "degree_levels": DEGREE_LEVELS,
        "is_edit": True,
        "is_admin": user.is_admin,
    })


@router.post("/education/{edu_id}")
async def education_update(
        request: Request,
        edu_id: int,
        education_group: str = Form(...),
        degree_level: str = Form(...),
        major: str = Form(...),
        graduation_date_str: str = Form(...),
        notes: str = Form(""),
        certificate: UploadFile = File(None),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """ویرایش مدرک"""
    try:
        edu = db.query(Education).filter(
            and_(Education.id == edu_id, Education.user_id == user.user_id)
        ).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        if edu.verified:
            raise ValueError("مدارک تایید شده قابل ویرایش نیستند")

        # اعتبارسنجی فیلدها
        if education_group not in EDUCATION_GROUPS:
            raise ValueError("گروه تحصیلی نامعتبر است")
        if degree_level not in DEGREE_LEVELS:
            raise ValueError("مقطع تحصیلی نامعتبر است")
        if not major.strip():
            raise ValueError("رشته تحصیلی الزامی است")

        # تبدیل تاریخ
        j_date = jdatetime.datetime.strptime(graduation_date_str.strip(), "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        # به‌روزرسانی فیلدها
        edu.education_group = education_group
        edu.degree_level = degree_level
        edu.major = major.strip()
        edu.graduation_date = g_date
        edu.notes = notes.strip() or None

        old_cert_path = None
        new_cert_key = None
        if certificate and certificate.filename:
            ext = Path(certificate.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                return RedirectResponse(
                    url=f"/education/{edu_id}/edit?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                    status_code=302
                )
            content = await certificate.read()
            if len(content) > MAX_FILE_SIZE:
                return RedirectResponse(
                    url=f"/education/{edu_id}/edit?error=حجم فایل بیش از 5 مگابایت است",
                    status_code=302
                )
            try:
                old_cert_path, new_cert_key = _apply_certificate_bytes(
                    edu, content, certificate.filename
                )
                db.commit()
            except Exception:
                db.rollback()
                if new_cert_key:
                    delete_media_file(new_cert_key)
                raise
            if old_cert_path and old_cert_path != new_cert_key:
                delete_media_file(old_cert_path)
        else:
            db.commit()

        # به‌روزرسانی بالاترین مدرک
        update_highest_degree(db, user.user_id)
        db.commit()

        return RedirectResponse(url="/education?success=مدرک با موفقیت ویرایش شد", status_code=302)
    except ValueError as e:
        return RedirectResponse(url=f"/education/{edu_id}/edit?error={str(e)}", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/education/{edu_id}/edit?error=خطا: {str(e)}", status_code=302)


@router.post("/education/{edu_id}/delete")
async def education_delete(
        request: Request,
        edu_id: int,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """حذف مدرک"""
    try:
        edu = db.query(Education).filter(
            and_(Education.id == edu_id, Education.user_id == user.user_id)
        ).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        if edu.verified:
            raise ValueError("مدارک تایید شده قابل حذف نیستند")

        if edu.certificate_path:
            delete_media_file(edu.certificate_path)

        db.delete(edu)
        db.commit()

        # به‌روزرسانی بالاترین مدرک
        update_highest_degree(db, user.user_id)
        db.commit()

        return RedirectResponse(url="/education?success=مدرک حذف شد", status_code=302)
    except ValueError as e:
        return RedirectResponse(url=f"/education?error={str(e)}", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/education?error=خطا: {str(e)}", status_code=302)

# ============================================
# بخش ادمین
# ============================================

@router.get("/admin/education", response_class=HTMLResponse)
async def admin_education_list(
        request: Request,
        verified_filter: str = None,
        search: str = None,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """لیست مدارک تحصیلی همه کاربران (پنل ادمین)"""
    enforce_permission(db, user, 'view_dashboard')
    query = db.query(Education).outerjoin(Employee, Education.user_id == Employee.user_id)

    if verified_filter == 'pending':
        query = query.filter(Education.verified == False)
    elif verified_filter == 'verified':
        query = query.filter(Education.verified == True)

    if search:
        query = query.filter(
            Employee.first_name.ilike(f"%{search}%") |
            Employee.last_name.ilike(f"%{search}%") |
            Education.major.ilike(f"%{search}%")
        )

    educations = query.order_by(Education.created_at.desc()).all()

    # ساخت لیست نتایج
    results = []
    for edu in educations:
        emp = db.query(Employee).filter(Employee.user_id == edu.user_id).first()
        j_date = jdatetime.date.fromgregorian(date=edu.graduation_date)
        results.append({
            'id': edu.id,
            'user_id': edu.user_id,
            'full_name': f"{emp.first_name} {emp.last_name}" if emp else edu.user_id,
            'education_group_name': edu.education_group_name,
            'degree_level_name': edu.degree_level_name,
            'major': edu.major,
            'graduation_date_j': j_date.strftime('%Y/%m/%d'),
            'certificate_path': edu.certificate_path,
            'certificate_type': edu.certificate_type,
            'verified': edu.verified,
            'verification_date_j': jdatetime.date.fromgregorian(date=edu.verification_date).strftime(
                '%Y/%m/%d') if edu.verification_date else None,
        })

    # آمار
    pending_count = db.query(Education).filter(Education.verified == False).count()

    return templates.TemplateResponse(request, "admin/education_list.html", {
        "user": user,
        "results": results,
        "total_count": len(results),
        "pending_count": pending_count,
        "verified_filter": verified_filter,
        "search": search,
        "is_admin": True,
    })


@router.post("/admin/education/{edu_id}/verify")
async def admin_verify_education(
        request: Request,
        edu_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تایید مدرک تحصیلی"""
    enforce_permission(db, user, 'view_dashboard')
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        edu.verified = True
        edu.verification_date = date.today()
        edu.verified_by = user.user_id

        db.commit()

        return RedirectResponse(url="/admin/education?success=مدرک تایید شد", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/admin/education?error=خطا: {str(e)}", status_code=302)


@router.post("/admin/education/{edu_id}/reject")
async def admin_reject_education(
        request: Request,
        edu_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """رد مدرک تحصیلی (حذف)"""
    enforce_permission(db, user, 'view_dashboard')
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        if edu.certificate_path:
            delete_media_file(edu.certificate_path)

        db.delete(edu)
        db.commit()

        return RedirectResponse(url="/admin/education?success=مدرک رد و حذف شد", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/admin/education?error=خطا: {str(e)}", status_code=302)


# ============================================
# 🆕 ویرایش و حذف توسط ادمین (حتی مدارک تایید شده)
# ============================================

@router.get("/admin/education/{edu_id}/edit", response_class=HTMLResponse)
async def admin_education_edit_form(
        request: Request,
        edu_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """فرم ویرایش مدرک توسط ادمین (حتی تایید شده)"""
    enforce_permission(db, user, 'view_dashboard')
    edu = db.query(Education).filter(Education.id == edu_id).first()

    if not edu:
        return RedirectResponse(url="/admin/education?error=مدرک یافت نشد", status_code=302)

    j_date = jdatetime.date.fromgregorian(date=edu.graduation_date)

    # دریافت نام کارمند برای نمایش
    emp = db.query(Employee).filter(Employee.user_id == edu.user_id).first()
    full_name = f"{emp.first_name} {emp.last_name}" if emp else edu.user_id

    return templates.TemplateResponse(request, "admin/education_form.html", {
        "user": user,
        "education": edu,
        "graduation_date_j": j_date.strftime('%Y/%m/%d'),
        "education_groups": EDUCATION_GROUPS,
        "degree_levels": DEGREE_LEVELS,
        "full_name": full_name,
        "is_edit": True,
        "is_admin": True,
    })


@router.post("/admin/education/{edu_id}")
async def admin_education_update(
        request: Request,
        edu_id: int,
        education_group: str = Form(...),
        degree_level: str = Form(...),
        major: str = Form(...),
        graduation_date_str: str = Form(...),
        notes: str = Form(""),
        verified: bool = Form(False),  # 🆕 ادمین می‌تواند وضعیت تایید را تغییر دهد
        certificate: UploadFile = File(None),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """ویرایش مدرک توسط ادمین (حتی تایید شده)"""
    enforce_permission(db, user, 'view_dashboard')
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        # اعتبارسنجی فیلدها
        if education_group not in EDUCATION_GROUPS:
            raise ValueError("گروه تحصیلی نامعتبر است")
        if degree_level not in DEGREE_LEVELS:
            raise ValueError("مقطع تحصیلی نامعتبر است")
        if not major.strip():
            raise ValueError("رشته تحصیلی الزامی است")

        # تبدیل تاریخ
        j_date = jdatetime.datetime.strptime(graduation_date_str.strip(), "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        # 🆕 تشخیص تغییر مقطع (برای به‌روزرسانی is_highest)
        degree_changed = edu.degree_level != degree_level

        # به‌روزرسانی فیلدها
        edu.education_group = education_group
        edu.degree_level = degree_level
        edu.major = major.strip()
        edu.graduation_date = g_date
        edu.notes = notes.strip() or None

        # 🆕 به‌روزرسانی وضعیت تایید توسط ادمین
        if verified and not edu.verified:
            # تایید جدید
            edu.verified = True
            edu.verification_date = date.today()
            edu.verified_by = user.user_id
        elif not verified and edu.verified:
            # لغو تایید
            edu.verified = False
            edu.verification_date = None
            edu.verified_by = None

        old_cert_path = None
        new_cert_key = None
        if certificate and certificate.filename:
            ext = Path(certificate.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                return RedirectResponse(
                    url=f"/admin/education/{edu_id}/edit?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                    status_code=302
                )
            content = await certificate.read()
            if len(content) > MAX_FILE_SIZE:
                return RedirectResponse(
                    url=f"/admin/education/{edu_id}/edit?error=حجم فایل بیش از 5 مگابایت است",
                    status_code=302
                )
            try:
                old_cert_path, new_cert_key = _apply_certificate_bytes(
                    edu, content, certificate.filename
                )
                db.commit()
            except Exception:
                db.rollback()
                if new_cert_key:
                    delete_media_file(new_cert_key)
                raise
            if old_cert_path and old_cert_path != new_cert_key:
                delete_media_file(old_cert_path)
        else:
            db.commit()

        # 🆕 به‌روزرسانی بالاترین مدرک (اگر مقطع تغییر کرد)
        if degree_changed:
            update_highest_degree(db, edu.user_id)
            db.commit()

        return RedirectResponse(url="/admin/education?success=مدرک با موفقیت ویرایش شد", status_code=302)
    except ValueError as e:
        return RedirectResponse(url=f"/admin/education/{edu_id}/edit?error={str(e)}", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/admin/education/{edu_id}/edit?error=خطا: {str(e)}", status_code=302)


@router.post("/admin/education/{edu_id}/delete")
async def admin_education_delete(
        request: Request,
        edu_id: int,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """حذف مدرک توسط ادمین (حتی تایید شده)"""
    enforce_permission(db, user, 'view_dashboard')
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        user_id = edu.user_id

        if edu.certificate_path:
            delete_media_file(edu.certificate_path)

        db.delete(edu)
        db.commit()

        # 🆕 به‌روزرسانی بالاترین مدرک
        update_highest_degree(db, user_id)
        db.commit()

        return RedirectResponse(url="/admin/education?success=مدرک حذف شد", status_code=302)
    except ValueError as e:
        return RedirectResponse(url=f"/admin/education?error={str(e)}", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/admin/education?error=خطا: {str(e)}", status_code=302)