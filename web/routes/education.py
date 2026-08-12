"""
روتر تحصیلات (بخش کاربر و ادمین)
"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_
import jdatetime
from datetime import date
import time

from web.dependencies import get_db, get_current_user, require_admin
from models.user import User
from models.employee import Employee
from models.education import Education, EDUCATION_GROUPS, DEGREE_LEVELS, DEGREE_PRIORITY

router = APIRouter(tags=["Education"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# 🆕 مسیر و محدودیت‌های آپلود (مطابق الگوی عکس پروفایل)
UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads" / "certificates"
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 مگابایت


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

        # 🆕 آپلود فایل مدرک (مطابق الگوی عکس پروفایل)
        if certificate and certificate.filename:
            # اعتبارسنجی نوع فایل
            ext = Path(certificate.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                db.rollback()
                return RedirectResponse(
                    url="/education/new?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                    status_code=302
                )

            # بررسی اندازه فایل
            content = await certificate.read()
            if len(content) > MAX_FILE_SIZE:
                db.rollback()
                return RedirectResponse(
                    url="/education/new?error=حجم فایل بیش از 5 مگابایت است",
                    status_code=302
                )

            # ساخت پوشه اگر وجود ندارد
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            # ذخیره فایل با نام یکتا (user_id + timestamp + edu_id)
            filename = f"{user.user_id}_{new_edu.id}_{int(time.time())}{ext}"
            file_path = UPLOAD_DIR / filename

            with open(file_path, 'wb') as f:
                f.write(content)

            # تعیین نوع فایل و ذخیره مسیر
            new_edu.certificate_type = 'pdf' if ext == '.pdf' else 'image'
            new_edu.certificate_path = f"/static/uploads/certificates/{filename}"

        db.commit()

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

        # 🆕 آپلود فایل جدید (مطابق الگوی عکس پروفایل)
        if certificate and certificate.filename:
            # اعتبارسنجی نوع فایل
            ext = Path(certificate.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                return RedirectResponse(
                    url=f"/education/{edu_id}/edit?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                    status_code=302
                )

            # بررسی اندازه فایل
            content = await certificate.read()
            if len(content) > MAX_FILE_SIZE:
                return RedirectResponse(
                    url=f"/education/{edu_id}/edit?error=حجم فایل بیش از 5 مگابایت است",
                    status_code=302
                )

            # ساخت پوشه اگر وجود ندارد
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            # 🆕 حذف فایل قبلی
            if edu.certificate_path:
                old_file = Path(__file__).parent.parent / "static" / edu.certificate_path.replace("/static/",
                                                                                                  "").replace("\\", "/")
                if old_file.exists():
                    old_file.unlink()

            # ذخیره فایل جدید
            filename = f"{user.user_id}_{edu.id}_{int(time.time())}{ext}"
            file_path = UPLOAD_DIR / filename

            with open(file_path, 'wb') as f:
                f.write(content)

            # به‌روزرسانی نوع فایل و مسیر
            edu.certificate_type = 'pdf' if ext == '.pdf' else 'image'
            edu.certificate_path = f"/static/uploads/certificates/{filename}"

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

        # 🆕 حذف فایل (مطابق الگوی عکس پروفایل)
        if edu.certificate_path:
            old_file = Path(__file__).parent.parent / "static" / edu.certificate_path.replace("/static/", "").replace(
                "\\", "/")
            if old_file.exists():
                old_file.unlink()

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
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        # 🆕 حذف فایل
        if edu.certificate_path:
            old_file = Path(__file__).parent.parent / "static" / edu.certificate_path.replace("/static/", "").replace(
                "\\", "/")
            if old_file.exists():
                old_file.unlink()

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

        # آپلود فایل جدید (اختیاری)
        if certificate and certificate.filename:
            # اعتبارسنجی نوع فایل
            ext = Path(certificate.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                return RedirectResponse(
                    url=f"/admin/education/{edu_id}/edit?error=نوع فایل مجاز نیست (فقط JPG/PNG/PDF)",
                    status_code=302
                )

            # بررسی اندازه فایل
            content = await certificate.read()
            if len(content) > MAX_FILE_SIZE:
                return RedirectResponse(
                    url=f"/admin/education/{edu_id}/edit?error=حجم فایل بیش از 5 مگابایت است",
                    status_code=302
                )

            # ساخت پوشه اگر وجود ندارد
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            # حذف فایل قبلی
            if edu.certificate_path:
                old_file = Path(__file__).parent.parent / "static" / edu.certificate_path.replace("/static/",
                                                                                                  "").replace("\\", "/")
                if old_file.exists():
                    old_file.unlink()

            # ذخیره فایل جدید
            filename = f"{edu.user_id}_{edu.id}_{int(time.time())}{ext}"
            file_path = UPLOAD_DIR / filename

            with open(file_path, 'wb') as f:
                f.write(content)

            # به‌روزرسانی نوع فایل و مسیر
            edu.certificate_type = 'pdf' if ext == '.pdf' else 'image'
            edu.certificate_path = f"/static/uploads/certificates/{filename}"

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
    try:
        edu = db.query(Education).filter(Education.id == edu_id).first()

        if not edu:
            raise ValueError("مدرک یافت نشد")

        user_id = edu.user_id

        # حذف فایل
        if edu.certificate_path:
            old_file = Path(__file__).parent.parent / "static" / edu.certificate_path.replace("/static/", "").replace(
                "\\", "/")
            if old_file.exists():
                old_file.unlink()

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