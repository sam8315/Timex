"""پنل مدیریت"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_admin, require_super_admin
from models.user import User
from models.leave_request import LeaveRequest
from datetime import timedelta, date, date as date_type
from sqlalchemy import and_, func
import time
import json
import subprocess
import sys
import threading
from typing import Optional
from fastapi import Query
from fastapi import UploadFile, File
from pathlib import Path
import os
from web.routes.attendance import calculate_work_hours, STATUS_NIGHT_SHIFT
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy import and_, or_, func, nulls_last
from datetime import timedelta  # اگر نیست
from models.employee_phone import EmployeePhone
from web.routes.attendance import (
    format_hours_hhmm, STATUS_LEAVE
)
from web.routes.attendance import (
    analyze_day_status,
    calculate_work_hours,
    format_hours_hhmm, STATUS_LEAVE,
    STATUS_COMPLETE, STATUS_NIGHT_SHIFT, STATUS_MISSING_EXIT,
    STATUS_MISSING_ENTER, STATUS_SEQUENCE_ERROR, STATUS_IMBALANCE,
    STATUS_NO_ATTENDANCE
)
from web.services.attendance_policy_service import compute_required_minutes_for_range
from web.services.hourly_leave_service import (
    get_approved_hl_minutes,
    get_approved_hl_minutes_on_date,
    format_hl_display,
)
from models.daily_status import DailyStatus
from web.permissions import has_permission, get_effective_permissions, enforce_permission
from models.employee_region import EmployeeRegion
from models.policy import PolicyAuditLog

def build_redirect_url(referer: str, key: str, value: str) -> str:
    """ساخت URL بازگشت با رعایت query string موجود"""
    separator = '&' if '?' in referer else '?'
    return f"{referer}{separator}{key}={value}"
def add_query_param(url: str, key: str, value: str) -> str:
    """افزودن پارامتر به URL با رعایت query string موجود"""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    query_params[key] = [value]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', new_query, ''))


def day_bounds(day) -> tuple:
    """بازه [نیمه‌شب, نیمه‌شب بعد) برای یک روز — معادل date(timestamp) == day
    ولی با استفاده از ایندکس (پرهیز از full scan)."""
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def read_test_status() -> Optional[dict]:
    """خواندن نتیجه آخرین اجرای تست‌های خودکار (برای بنر داشبورد)"""
    try:
        path = Path(__file__).resolve().parent.parent.parent / "log" / "test_status.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_test_error(root: Path, message: str) -> None:
    """ثبت خطای اجرای تست‌ها به‌صورت قابل نمایش در بنر داشبورد"""
    try:
        status_path = root / "log" / "test_status.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps({
                "ran_at": "", "ran_at_j": "-",
                "duration_s": 0, "total": 0, "passed": 0,
                "failed": 0, "errors": 1, "skipped": 0,
                "success": False,
                "failed_tests": [message[:500]],
                "args": ["tests"],
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _finalize_test_run(root: Path, proc) -> None:
    """پس از پایان ساب‌پروسس pytest: اگر هوک نتیجه را ثبت نکرده بود، خطا ثبت کن.

    هوک tests/conftest.py در پایان هر اجرای موفق، test_status.json را
    می‌نویسد و مارکر را پاک می‌کند؛ باقی ماندن مارکر یعنی اجرا ناقص مانده
    (مثلاً pytest نصب نیست یا دیتابیس تست در دسترس نیست).
    """
    marker = root / "log" / "test_status.running"
    try:
        still_running = marker.exists()
    except OSError:
        still_running = False
    if not still_running:
        return  # هوک نتیجه واقعی را ثبت کرده است
    detail = ""
    if proc is not None:
        output = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "")
                  or "").strip().splitlines()
        detail = output[-1].strip() if output else ""
        detail = f"pytest exit={getattr(proc, 'returncode', '?')}: {detail}"
    _write_test_error(root, detail or "pytest did not complete")
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass

# 🆕 import تابع تحلیل وضعیت از صفحه کاربر عادی
from web.routes.attendance import (
    analyze_day_status,
    STATUS_COMPLETE, STATUS_NIGHT_SHIFT, STATUS_MISSING_EXIT,
    STATUS_MISSING_ENTER, STATUS_SEQUENCE_ERROR, STATUS_IMBALANCE,
    STATUS_NO_ATTENDANCE
)
from models.attendance import Attendance
from models.employee import Employee
from models.holiday import Holiday

"""
داشبورد مدیریت
"""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, distinct
import jdatetime

from web.dependencies import get_db, require_admin
from models.user import User
from models.employee import Employee
from models.leave_balance import LeaveBalance
from models.leave_request import LeaveRequest
from models.attendance import Attendance
from models.daily_status import DailyStatus
from models.contract import Contract
from models.leave_carry_forward_request import LeaveCarryForwardRequest
from models.bale_user import BaleUser  # 🆕 ربات بله

router = APIRouter(tags=["Admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# نام انواع مرخصی
LEAVE_TYPE_NAMES = {
    'AL': 'استحقاقی',
    'SL': 'استعلاجی',
    'RL': 'تشویقی',
    'UL': 'بدون حقوق',
    'CW': 'ذخیره سال قبل'
}

STATUS_NAMES = {
    'P': 'در انتظار',
    'A': 'تایید شده',
    'R': 'رد شده'
}


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """داشبورد مدیریت"""
    # 🆕 بررسی دسترسی فردی
    if not has_permission(db, user, 'view_dashboard'):
        return RedirectResponse(url="/attendance?error=no_permission", status_code=302)
    today_j = jdatetime.date.today()
    today_g = today_j.togregorian()
    yesterday_g = today_g - timedelta(days=1)  # 🆕 دیروز

    # ============================================
    # 📊 کارت‌های KPI
    # ============================================

    # ۱. کل کارمندان فعال
    total_employees = db.query(Employee).filter(
        Employee.is_active == True
    ).count()

    # 🆕 تفکیک کارمندان فعال بر اساس نوع قرارداد
    DEPT_NAMES = {
        '1': 'رسمی', '2': 'وظیفه', '3': 'خریدخدمت',
        '4': 'قراردادی', '5': 'پزشک'
    }
    dept_counts_raw = db.query(
        Employee.department,
        func.count(Employee.id)
    ).filter(
        Employee.is_active == True
    ).group_by(Employee.department).all()

    employee_breakdown = []
    for dept_code, count in dept_counts_raw:
        employee_breakdown.append({
            'code': dept_code,
            'name': DEPT_NAMES.get(dept_code, dept_code or 'نامشخص'),
            'count': count
        })

    # 🆕 ۲. حاضرین امروز (از Attendance زنده)
    today_start, today_end = day_bounds(today_g)
    present_user_ids = set(u[0] for u in db.query(Attendance.user_id).filter(
        and_(
            Attendance.timestamp >= today_start,
            Attendance.timestamp < today_end,
            Attendance.punch == 0,
            Attendance.is_deleted == False
        )
    ).distinct().all())
    present_today = len(present_user_ids)

    # 🆕 بدون تردد دیروز (به جای غایبین)
    # 3-کاربرانی که دیروز تردد داشتند
    yesterday_start, yesterday_end = day_bounds(yesterday_g)
    yesterday_attendance_users = set(u[0] for u in db.query(Attendance.user_id).filter(
        and_(
            Attendance.timestamp >= yesterday_start,
            Attendance.timestamp < yesterday_end,
            Attendance.is_deleted == False
        )
    ).distinct().all())

    # همه کاربران فعال
    all_active_user_ids = set(u[0] for u in db.query(Employee.user_id).filter(
        Employee.is_active == True
    ).all())

    # کاربرانی که دیروز وضعیت مرخصی/ماموریت/غیبت داشتند
    yesterday_statuses = db.query(DailyStatus).filter(
        and_(
            DailyStatus.status_date == yesterday_g,
            DailyStatus.status_code.in_(['AL', 'SL', 'RL', 'UL', 'M', 'A'])
        )
    ).all()
    yesterday_status_users = {ds.user_id for ds in yesterday_statuses}

    # بدون تردد دیروز = فعال‌ها - تردددارها - وضعیت‌دارها
    no_attendance_user_ids = all_active_user_ids - yesterday_attendance_users - yesterday_status_users
    no_attendance_yesterday = len(no_attendance_user_ids)

    # 🆕 ۴. مرخصی‌های امروز (از LeaveRequest تایید شده)
    on_leave_today = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.status == 'A',
            LeaveRequest.from_date <= today_g,
            LeaveRequest.to_date >= today_g
        )
    ).count()

    # ۵. درخواست‌های در انتظار
    pending_leave_requests = db.query(LeaveRequest).filter(
        LeaveRequest.status == 'P'
    ).count()

    # ۶. کاربران ربات بله
    total_bale_users = db.query(BaleUser).count()
    active_bale_users = db.query(BaleUser).filter(
        BaleUser.is_active == True
    ).count()

    # ============================================
    # ⚠️ هشدارهای فوری
    # ============================================

    # قراردادهای رو به انقضا
    expiration_warning_date = today_g + timedelta(days=30)
    expiring_contracts_count = db.query(Contract).filter(
        and_(
            Contract.end_date != None,
            Contract.end_date <= expiration_warning_date,
            Contract.end_date >= today_g
        )
    ).count()

    # مانده‌های منفی
    negative_balances_count = db.query(LeaveBalance).filter(
        and_(
            LeaveBalance.year == today_j.year,
            LeaveBalance.balance < 0
        )
    ).count()

    # انتقال مرخصی‌های معلق
    pending_carry_forward_count = db.query(LeaveCarryForwardRequest).filter(
        LeaveCarryForwardRequest.status == 'P'
    ).count()

    # 🆕 ترددهای ناقص هفته جاری (از شنبه تا دیروز) - با شناسایی شیفت شب
    today_weekday = today_g.weekday()
    days_since_saturday = (today_weekday + 2) % 7
    week_start_g = today_g - timedelta(days=days_since_saturday)

    week_incomplete_user_days = {}  # {user_id: [تاریخ‌های ناقص]}
    current_day = week_start_g
    while current_day < today_g:  # تا دیروز
        # کاربران با ورود در این روز
        day_start, day_end = day_bounds(current_day)
        day_enters = set(u[0] for u in db.query(Attendance.user_id).filter(
            and_(
                Attendance.timestamp >= day_start,
                Attendance.timestamp < day_end,
                Attendance.punch == 0,
                Attendance.is_deleted == False
            )
        ).distinct().all())

        # کاربران با خروج در این روز
        day_exits = set(u[0] for u in db.query(Attendance.user_id).filter(
            and_(
                Attendance.timestamp >= day_start,
                Attendance.timestamp < day_end,
                Attendance.punch == 1,
                Attendance.is_deleted == False
            )
        ).distinct().all())

        # 🆕 کاربران با ورود بدون خروج (احتمالاً ناقص یا شیفت شب)
        potential_incomplete = day_enters - day_exits

        # 🆕 بررسی شیفت شب: آیا اولین رکورد روز بعد خروج است؟
        next_day = current_day + timedelta(days=1)
        for uid in list(potential_incomplete):
            next_start, next_end = day_bounds(next_day)
            first_next_record = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == uid,
                    Attendance.timestamp >= next_start,
                    Attendance.timestamp < next_end,
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp.asc()).first()

            # اگر اولین رکورد روز بعد خروج بود → شیفت شب → ناقص نیست
            if first_next_record and first_next_record.punch == 1:
                potential_incomplete.discard(uid)

        # 🆕 کاربران با خروج بدون ورود (احتمالاً شیفت شب از روز قبل)
        potential_missing_enter = day_exits - day_enters
        prev_day = current_day - timedelta(days=1)
        for uid in list(potential_missing_enter):
            prev_start, prev_end = day_bounds(prev_day)
            last_prev_record = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == uid,
                    Attendance.timestamp >= prev_start,
                    Attendance.timestamp < prev_end,
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp.desc()).first()

            # اگر آخرین رکورد روز قبل ورود بود → شیفت شب → ناقص نیست
            if last_prev_record and last_prev_record.punch == 0:
                potential_missing_enter.discard(uid)

        # 🆕 ترکیب ترددهای واقعاً ناقص (ورود بدون خروج + خروج بدون ورود)
        real_incomplete = potential_incomplete | potential_missing_enter

        # ثبت در دیکشنری
        for uid in real_incomplete:
            if uid not in week_incomplete_user_days:
                week_incomplete_user_days[uid] = []
            week_incomplete_user_days[uid].append(current_day)

        current_day += timedelta(days=1)

    week_incomplete_count = len(week_incomplete_user_days)
    # ============================================
    # 📋 لیست حاضرین امروز (از Attendance)
    # ============================================
    present_list = []
    for uid in present_user_ids:
        employee = db.query(Employee).filter(
            Employee.user_id == uid
        ).first()

        # اولین و آخرین ورود امروز
        first_enter = db.query(Attendance).filter(
            and_(
                Attendance.user_id == uid,
                Attendance.timestamp >= today_start,
                Attendance.timestamp < today_end,
                Attendance.punch == 0,
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).first()

        present_list.append({
            'user_id': uid,
            'full_name': employee.full_name if employee else uid,
            'department': employee.department if employee else '-',
            'enter_time': first_enter.timestamp.strftime('%H:%M') if first_enter else '-',
        })

    present_list.sort(key=lambda x: x['full_name'])

    # ============================================
    # 🆕 ساخت لیست بدون تردها
    # ============================================
    no_attendance_list = []
    for uid in no_attendance_user_ids:
        employee = db.query(Employee).filter(Employee.user_id == uid).first()
        no_attendance_list.append({
            'user_id': uid,
            'full_name': employee.full_name if employee else uid,
            'department': employee.department if employee else '-',
        })
    no_attendance_list.sort(key=lambda x: x['full_name'])

    # ============================================
    # 📋 لیست درخواست‌های در انتظار
    # ============================================
    pending_list = []
    pending_requests = db.query(LeaveRequest).filter(
        LeaveRequest.status == 'P'
    ).order_by(LeaveRequest.created_at.desc()).limit(10).all()

    for req in pending_requests:
        employee = db.query(Employee).filter(
            Employee.user_id == req.user_id
        ).first()
        j_from = jdatetime.date.fromgregorian(date=req.from_date)
        j_to = jdatetime.date.fromgregorian(date=req.to_date)

        pending_list.append({
            'id': req.id,
            'user_id': req.user_id,
            'full_name': employee.full_name if employee else req.user_id,
            'leave_type': req.leave_type,
            'leave_type_name': LEAVE_TYPE_NAMES.get(req.leave_type, req.leave_type),
            'from_date_j': j_from.strftime('%Y/%m/%d'),
            'to_date_j': j_to.strftime('%Y/%m/%d'),
            'days_count': req.days_count,
        })

    # ============================================
    # 🤖 آخرین کاربران ربات بله
    # ============================================
    recent_bale_users = []
    bale_users = db.query(BaleUser).order_by(
        BaleUser.registered_at.desc()
    ).limit(10).all()

    for bu in bale_users:
        employee = db.query(Employee).filter(
            Employee.user_id == bu.user_id
        ).first()
        reg_j = jdatetime.datetime.fromgregorian(datetime=bu.registered_at) if bu.registered_at else None

        recent_bale_users.append({
            'chat_id': bu.chat_id,
            'user_id': bu.user_id,
            'full_name': employee.full_name if employee else bu.user_id,
            'phone_number': bu.phone_number or '-',
            'is_active': bu.is_active,
            'registered_at_j': reg_j.strftime('%Y/%m/%d') if reg_j else '-',
        })

    # ============================================
    # 🆕 ساخت لیست ترددهای ناقص هفته
    # ============================================

    week_incomplete_list = []
    for uid, dates in week_incomplete_user_days.items():
        employee = db.query(Employee).filter(Employee.user_id == uid).first()
        week_incomplete_list.append({
            'user_id': uid,
            'full_name': employee.full_name if employee else uid,
            'days_count': len(dates),
            'last_incomplete_j': jdatetime.date.fromgregorian(date=max(dates)).strftime('%Y/%m/%d'),
        })
    week_incomplete_list.sort(key=lambda x: x['days_count'], reverse=True)

    # ============================================
    # 🆕 محاسبه درصد حضور دیروز (از Attendance زنده)
    # ============================================
    attendance_rate = 0
    if total_employees > 0:
        # کاربران حاضر دیروز از Attendance (نه DailyStatus)
        yesterday_present_users = set(u[0] for u in db.query(Attendance.user_id).filter(
            and_(
                Attendance.timestamp >= yesterday_start,
                Attendance.timestamp < yesterday_end,
                Attendance.punch == 0,
                Attendance.is_deleted == False
            )
        ).distinct().all())

        # کسر کاربران مرخصی/ماموریت دیروز از مخرج (اختیاری)
        # تا درصد دقیق‌تر باشد
        attendance_rate = round((len(yesterday_present_users) / total_employees) * 100, 1)

    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "user": user,
        "today_j": today_j,

        # 📊 KPI
        "total_employees": total_employees,
        "employee_breakdown": employee_breakdown,  # 🆕
        "present_today": present_today,
        "no_attendance_yesterday": no_attendance_yesterday,  # 🆕 (جایگزین غایبین)
        "on_leave_today": on_leave_today,
        "pending_leave_requests": pending_leave_requests,
        "total_bale_users": total_bale_users,
        "active_bale_users": active_bale_users,
        "attendance_rate": attendance_rate,

        # ⚠️ هشدارها
        "expiring_contracts_count": expiring_contracts_count,
        "negative_balances_count": negative_balances_count,
        "pending_carry_forward_count": pending_carry_forward_count,
        "week_incomplete_count": week_incomplete_count,  # 🆕 (جایگزین تردد ناقص امروز)

        # 📋 لیست‌ها
        "present_list": present_list,
        "no_attendance_list": no_attendance_list,  # 🆕 (جایگزین غایبین)
        "pending_list": pending_list,
        "recent_bale_users": recent_bale_users,
        "week_incomplete_list": week_incomplete_list,  # 🆕 (جایگزین ترددهای ناقص)
        "week_start_j": jdatetime.date.fromgregorian(date=week_start_g).strftime('%Y/%m/%d'),  # 🆕

        "is_admin": True,
        "test_status": read_test_status(),  # 🆕 وضعیت تست‌های خودکار
    })


@router.post("/admin/tests/run")
async def admin_run_tests(
    request: Request,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """اجرای تست‌های خودکار پنل وب در پس‌زمینه (فقط مدیر ارشد)"""
    if not has_permission(db, user, 'manage_users'):
        return RedirectResponse(url="/admin/", status_code=302)

    root = Path(__file__).resolve().parent.parent.parent
    marker = root / "log" / "test_status.running"

    # جلوگیری از اجرای همزمان
    if marker.exists():
        try:
            age = time.time() - marker.stat().st_mtime
        except OSError:
            age = 0
        if age < 900:
            referer = request.headers.get("referer", "/admin")
            return RedirectResponse(
                url=build_redirect_url(referer, "error", "tests-running"),
                status_code=302
            )
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("running", encoding="utf-8")
    except OSError:
        pass

    def _run():
        proc = None
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "tests", "-q",
                 "-p", "no:cacheprovider"],
                cwd=str(root),
                timeout=600,
                capture_output=True,
                text=True,
            )
        except Exception as e:
            _write_test_error(root, f"test-runner: {e}")
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            _finalize_test_run(root, proc)

    threading.Thread(target=_run, daemon=True).start()
    referer = request.headers.get("referer", "/admin")
    return RedirectResponse(
        url=build_redirect_url(referer, "success", "tests-started"),
        status_code=302
    )


from sqlalchemy import or_


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    web_status: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """مدیریت کاربران با فیلتر و جستجو"""
    enforce_permission(db, user, 'view_dashboard')
    has_filter = any([search, department, role, status, web_status, show_all])

    user_details = []
    total_count = 0

    if has_filter:
        query = db.query(User)

        # 🆕 بررسی اینکه آیا نیاز به join با Employee داریم
        needs_employee_join = any([search, department, status])
        if needs_employee_join:
            query = query.outerjoin(Employee, User.user_id == Employee.user_id)

        # 🔍 جستجو (بدون join مجدد)
        if search and search.strip():
            search_term = search.strip()
            query = query.filter(
                or_(
                    User.user_id.ilike(f"%{search_term}%"),
                    User.name.ilike(f"%{search_term}%"),
                    Employee.first_name.ilike(f"%{search_term}%"),
                    Employee.last_name.ilike(f"%{search_term}%"),
                    Employee.national_code.ilike(f"%{search_term}%")
                )
            )

        # 🏢 فیلتر دپارتمان (بدون join مجدد)
        if department:
            query = query.filter(Employee.department == department)

        # 🎭 فیلتر نقش
        if role:
            query = query.filter(User.role == role)

        # ✅ فیلتر وضعیت فعال/غیرفعال (بدون join مجدد)
        if status == 'active':
            query = query.filter(Employee.is_active == True)
        elif status == 'inactive':
            query = query.filter(Employee.is_active == False)

        # 🌐 فیلتر وضعیت وب
        if web_status == 'enabled':
            query = query.filter(User.web_enabled == True)
        elif web_status == 'disabled':
            query = query.filter(User.web_enabled == False)

        users = query.order_by(User.user_id).all()

        # ساخت لیست نتایج
        for wu in users:
            emp = db.query(Employee).filter(Employee.user_id == wu.user_id).first()

            last_login_display = None
            if wu.last_login:
                try:
                    last_login_j = jdatetime.datetime.fromgregorian(datetime=wu.last_login)
                    last_login_display = last_login_j.strftime('%Y/%m/%d - %H:%M')
                except Exception:
                    last_login_display = wu.last_login.strftime('%Y/%m/%d - %H:%M')

            user_details.append({
                'web_user': wu,
                'employee': emp,
                'last_login_display': last_login_display,
            })

        total_count = len(user_details)

    return templates.TemplateResponse(request, "admin/users.html", {
        "user": user,
        "users": user_details,
        "is_admin": True,
        "is_super_admin": user.is_super_admin,
        "total_count": total_count,
        "has_filter": has_filter,
        "show_all": show_all,
        "search": search or "",
        "department": department or "",
        "role": role or "",
        "status": status or "",
        "web_status": web_status or "",
    })

@router.get("/admin/attendance", response_class=HTMLResponse)
async def admin_attendance(
    request: Request,
    date_str: Optional[str] = None,
    department: Optional[str] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمای روزانه تردد همه کارمندان"""
    enforce_permission(db, user, 'view_all_attendance')
    # تاریخ هدف
    if date_str:
        try:
            j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
            target_date = j_date.togregorian()
        except Exception:
            target_date = jdatetime.date.today().togregorian()
    else:
        target_date = jdatetime.date.today().togregorian()

    target_j = jdatetime.date.fromgregorian(date=target_date)

    # دریافت کارمندان فعال
    query = db.query(Employee).filter(Employee.is_active == True)
    if department:
        query = query.filter(Employee.department == department)

    # 🆕 مرتب‌سازی بر اساس عضویت، تاریخ استخدام، نام
    employees = query.order_by(
        Employee.department,  # ۱. عضویت
        nulls_last(Employee.hire_date),  # ۲. تاریخ استخدام (خالی‌ها آخر)
        Employee.first_name  # ۳. نام
    ).all()

    # دریافت تردهای همه در این روز
    attendances = db.query(Attendance).filter(
        and_(
            func.date(Attendance.timestamp) == target_date,
            Attendance.is_deleted == False
        )
    ).all()

    # گروه‌بندی بر اساس user_id
    att_by_user = {}
    for att in attendances:
        if att.user_id not in att_by_user:
            att_by_user[att.user_id] = []
        att_by_user[att.user_id].append(att)

    # دریافت وضعیت‌های روزانه (مرخصی، ماموریت و...)
    from models.daily_status import DailyStatus
    daily_statuses = db.query(DailyStatus).filter(
        DailyStatus.status_date == target_date
    ).all()
    status_by_user = {ds.user_id: ds.status_code for ds in daily_statuses}

    # 🆕 دریافت مرخصی‌های تایید شده که شامل تاریخ هدف هستند
    # ✅ HL جدا: HL نباید به‌عنوان مرخصی کامل روزانه دیده شود (فقط بج جداگانه نمایش داده می‌شود)
    approved_leaves = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.status == 'A',
            LeaveRequest.leave_type != 'HL',  # ✅ HL در leave_by_user نباشد
            LeaveRequest.from_date <= target_date,
            LeaveRequest.to_date >= target_date
        )
    ).all()
    leave_by_user = {lv.user_id: lv.leave_type for lv in approved_leaves}

    # بررسی تعطیل بودن روز
    is_friday = target_date.weekday() == 4
    holiday = db.query(Holiday).filter(
        Holiday.holiday_date == target_date
    ).first()

    # ساخت لیست نتایج
    results = []
    for emp in employees:
        user_atts = att_by_user.get(emp.user_id, [])
        enters = [a for a in user_atts if a.punch == 0]
        exits = [a for a in user_atts if a.punch == 1]

        first_enter = min(enters, key=lambda x: x.timestamp).timestamp if enters else None
        last_exit = max(exits, key=lambda x: x.timestamp).timestamp if exits else None

        # تعیین وضعیت
        daily_status = status_by_user.get(emp.user_id)
        leave_type = leave_by_user.get(emp.user_id)

        # 🕐 دقایق مرخصی ساعتی تایید شده در این روز (فقط نمایش)
        hl_minutes = get_approved_hl_minutes_on_date(db, emp, target_date)

        LEAVE_TYPE_NAMES_LOCAL = {
            'AL': 'استحقاقی',
            'SL': 'استعلاجی',
            'RL': 'تشویقی',
            'UL': 'بدون حقوق',
            'CW': 'ذخیره',
        }

        # ✅ اولویت ۱: تعطیل رسمی یا جمعه
        if is_friday or holiday:
            if is_friday:
                status_label = '🟡 جمعه'
                status_color = 'warning'
            else:
                status_label = f'🔴 تعطیل: {holiday.title}'
                status_color = 'danger'
        # ✅ اولویت ۲: DailyStatus (وضعیت دستی ثبت شده)
        elif daily_status:
            if daily_status in ('AL', 'SL', 'RL', 'UL'):
                type_name = LEAVE_TYPE_NAMES_LOCAL.get(daily_status, '')
                status_label = f'🌴 مرخصی {type_name}'
                status_color = 'info'
            elif daily_status == 'M':
                status_label = '💼 ماموریت'
                status_color = 'primary'
            elif daily_status == 'A':
                status_label = '❌ غیبت'
                status_color = 'danger'
            else:
                status_label = '📋 ' + daily_status
                status_color = 'secondary'
        # ✅ اولویت ۳: مرخصی تایید شده (فقط روز کاری)
        elif leave_type:
            type_name = LEAVE_TYPE_NAMES_LOCAL.get(leave_type, '')
            status_label = f'🌴 مرخصی {type_name}'
            status_color = 'info'
        # ✅ اولویت ۴: تحلیل تردد
        elif not user_atts:
            status_label = '⚪ بدون تردد'
            status_color = 'secondary'
        elif enters and exits and len(enters) == len(exits):
            status_label = '✅ کامل'
            status_color = 'success'
        elif len(enters) > len(exits):
            status_label = '⬅️ ورود بدون خروج'
            status_color = 'warning'
        elif len(exits) > len(enters):
            status_label = '➡️ خروج بدون ورود'
            status_color = 'warning'
        else:
            status_label = '⚠️ ناقص'
            status_color = 'danger'

        results.append({
            'user_id': emp.user_id,
            'full_name': emp.full_name,
            'department': emp.department,
            # 🆕 تاریخ استخدام (شمسی)
            'hire_date_j': jdatetime.date.fromgregorian(date=emp.hire_date).strftime('%Y/%m/%d') if emp.hire_date else '-',
            'first_enter': first_enter,
            'last_exit': last_exit,
            'total_punches': len(user_atts),
            'enter_count': len(enters),
            'exit_count': len(exits),
            'status_label': status_label,
            'status_color': status_color,
            'has_detail': len(user_atts) > 0,
            # 🕐 HL تایید شده برای نمایش (بج جداگانه، بدون تغییر وضعیت اصلی)
            'hourly_leave_minutes': hl_minutes,
            'hourly_leave_display': format_hl_display(hl_minutes),
        })

    # آمار
    present_count = sum(1 for r in results if '✅' in r['status_label'] or '⬅️' in r['status_label'] or '➡️' in r['status_label'])
    absent_count = sum(1 for r in results if '❌' in r['status_label'])
    leave_count = sum(1 for r in results if '🌴' in r['status_label'])
    no_attendance_count = sum(1 for r in results if '⚪' in r['status_label'])
    # 🆕 ناوبری بین روزها
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)
    prev_date_j = jdatetime.date.fromgregorian(date=prev_date)
    next_date_j = jdatetime.date.fromgregorian(date=next_date)
    today_g = jdatetime.date.today().togregorian()
    is_today = (target_date == today_g)

    return templates.TemplateResponse(request, "admin/attendance.html", {
        "user": user,
        "target_j": target_j,
        "date_str_input": target_j.strftime('%Y/%m/%d'),
        "results": results,
        "department": department,
        "is_friday": is_friday,
        "is_holiday": holiday is not None,
        "holiday_title": holiday.title if holiday else None,
        "total_employees": len(results),
        "present_count": present_count,
        "absent_count": absent_count,
        "leave_count": leave_count,
        "no_attendance_count": no_attendance_count,
        "is_admin": True,
        # 🆕 متغیرهای ناوبری
        "prev_date_str": prev_date_j.strftime('%Y/%m/%d'),
        "next_date_str": next_date_j.strftime('%Y/%m/%d'),
        "is_today": is_today,
    })


@router.get("/admin/attendance/user/{target_user_id}", response_class=HTMLResponse)
async def admin_user_attendance(
    request: Request,
    target_user_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="filter"),
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمای ماهانه تردد یک کاربر خاص (برای مدیر) - مشابه صفحه کاربر عادی"""
    enforce_permission(db, user, 'view_user_attendance')
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year
    if not month:
        month = today_j.month

    # اطلاعات کاربر هدف
    target_employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/attendance", status_code=302)

    # بازه ماه
    month_start_j = jdatetime.date(year, month, 1)
    if month == 12:
        month_end_j = jdatetime.date(year, 12, 29)
    else:
        month_end_j = jdatetime.date(year, month + 1, 1) - timedelta(days=1)
    month_start_g = month_start_j.togregorian()
    month_end_g = month_end_j.togregorian()

    # 🆕 فیلتر بازه تاریخ (در صورت اعمال) + محاسبات فقط بر پایه رکوردهای داخل بازه
    filter_from_g = None
    filter_to_g = None
    filter_error = None
    filter_applied = bool(from_date or to_date)
    from_date_display = ""
    to_date_display = ""

    if filter_applied:
        try:
            if from_date and from_date.strip():
                j_from = jdatetime.datetime.strptime(from_date.strip(), "%Y/%m/%d").date()
                filter_from_g = j_from.togregorian()
                from_date_display = j_from.strftime('%Y/%m/%d')
            if to_date and to_date.strip():
                j_to = jdatetime.datetime.strptime(to_date.strip(), "%Y/%m/%d").date()
                filter_to_g = j_to.togregorian()
                to_date_display = j_to.strftime('%Y/%m/%d')
            if filter_from_g and filter_to_g and filter_from_g > filter_to_g:
                filter_error = "تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد"
        except Exception:
            filter_error = filter_error or "فرمت تاریخ نامعتبر است (مثلاً 1404/06/10)"

    # دریافت ترددها: اگر فیلتر دارای خطا است، هیچ رکورد (یا حفظ رفتار قبلی) — در اینجا بدون فیلتر برای خطا
    if filter_applied and not filter_error:
        # برای to_date کامل روز (تا انتهای روز)، از < روز بعد 00:00 استفاده می‌کنیم
        if filter_to_g:
            to_day_end = filter_to_g + timedelta(days=1)
            records = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == target_user_id,
                    Attendance.timestamp >= (filter_from_g if filter_from_g else month_start_g - timedelta(days=1)),
                    Attendance.timestamp < to_day_end,
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp).all()
        elif filter_from_g:
            records = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == target_user_id,
                    Attendance.timestamp >= filter_from_g,
                    Attendance.timestamp <= month_end_g + timedelta(days=2),
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp).all()
        else:
            # فقط to_date بدون from
            to_day_end = filter_to_g + timedelta(days=1)
            records = db.query(Attendance).filter(
                and_(
                    Attendance.user_id == target_user_id,
                    Attendance.timestamp >= month_start_g - timedelta(days=1),
                    Attendance.timestamp < to_day_end,
                    Attendance.is_deleted == False
                )
            ).order_by(Attendance.timestamp).all()
    else:
        # دریافت ترددها با حاشیه 1 روز (برای شیفت شب) — رفتار قبلی
        records = db.query(Attendance).filter(
            and_(
                Attendance.user_id == target_user_id,
                Attendance.timestamp >= month_start_g - timedelta(days=1),
                Attendance.timestamp <= month_end_g + timedelta(days=2),
                Attendance.is_deleted == False
            )
        ).order_by(Attendance.timestamp).all()

    # اگر فیلتر اعمال شده و خطا ندارد، محدود کردن days_list به بازه فیلتر برای نمایش
    # (مانند status_filter که days_list را بعد از ساخت محدود می‌کند)

    # دریافت گروه کاربر (بر اساس دپارتمان)
    user_group = target_employee.department if target_employee else None

    # دریافت تعطیلات: ملی + گروه کاربر
    holiday_query = db.query(Holiday).filter(
        and_(
            Holiday.holiday_date >= month_start_g,
            Holiday.holiday_date <= month_end_g
        )
    )
    if user_group:
        holiday_query = holiday_query.filter(
            or_(Holiday.group_id == None, Holiday.group_id == user_group)
        )
    else:
        holiday_query = holiday_query.filter(Holiday.group_id == None)
    holidays = holiday_query.all()
    holiday_dates = {h.holiday_date: h.title for h in holidays}

    # دریافت مرخصی‌های تایید شده کاربر هدف برای بازه ماه (فقط مرخصی‌های روزانه، HL جداگانه پردازش می‌شود)
    approved_leaves = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == target_user_id,
            LeaveRequest.status == 'A',
            LeaveRequest.leave_type != 'HL',  # ✅ HL در leaves_by_date نباشد
            LeaveRequest.from_date <= month_end_g,
            LeaveRequest.to_date >= month_start_g
        )
    ).all()

    # ساخت دیکشنری مرخصی‌ها بر اساس تاریخ (فقط full-day leaves)
    LEAVE_TYPE_NAMES_LOCAL = {
        'AL': 'استحقاقی',
        'SL': 'استعلاجی',
        'RL': 'تشویقی',
        'CW': 'ذخیره',
    }
    leaves_by_date = {}
    for leave in approved_leaves:
        current_leave = leave.from_date
        while current_leave <= leave.to_date:
            if month_start_g <= current_leave <= month_end_g:
                leaves_by_date[current_leave] = leave.leave_type
            current_leave += timedelta(days=1)

    # Phase 7: Fetch approved hourly leave minutes by date
    hourly_leave_minutes_by_date = get_approved_hl_minutes(
        db=db, employee=target_employee,
        start_date=month_start_g, end_date=month_end_g
    )

    # گروه‌بندی بر اساس روز
    days_dict = {}
    for record in records:
        day = record.timestamp.date()
        if day not in days_dict:
            days_dict[day] = []
        days_dict[day].append(record)

    DAY_NAMES_FA = {
        0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
        3: 'پنج‌شنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه'
    }

    # ساخت لیست روزها با تحلیل وضعیت
    days_list = []
    current = month_start_g
    while current <= month_end_g:
        j_day = jdatetime.date.fromgregorian(date=current)
        day_records = days_dict.get(current, [])
        prev_day_records = days_dict.get(current - timedelta(days=1), [])
        next_day_records = days_dict.get(current + timedelta(days=1), [])
        is_friday = current.weekday() == 4
        holiday_title = holiday_dates.get(current)

        # تحلیل وضعیت با تابع مشترک
        status_info = analyze_day_status(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title
        )

        # بررسی مرخصی تایید شده (فقط در روزهای کاری - تعطیلات اولویت دارند)
        leave_type = leaves_by_date.get(current)
        if leave_type and not is_friday and holiday_title is None:
            type_name = LEAVE_TYPE_NAMES_LOCAL.get(leave_type, '')
            status_info['main_status'] = STATUS_LEAVE
            status_info['main_label'] = f'🌴 مرخصی {type_name}'
            status_info['main_color'] = 'info'

        # محاسبه کارکرد با در نظر گرفتن شیفت شب
        work_hours, first_enter, last_exit = calculate_work_hours(
            day_records,
            is_night_shift=status_info['main_status'] == STATUS_NIGHT_SHIFT
        )

        days_list.append({
            'date': current,
            'jalali_date': j_day.strftime('%Y/%m/%d'),
            'day_name': DAY_NAMES_FA.get(current.weekday(), ''),
            'records': day_records,
            'first_enter': first_enter,
            'last_exit': last_exit,
            'work_hours': work_hours,
            'work_hours_display': format_hours_hhmm(work_hours),
            'is_friday': is_friday,
            'is_holiday': holiday_title is not None,
            'holiday_title': holiday_title,
            'status': status_info,
            # 🕐 HL تایید شده برای نمایش (بدون تاثیر روی وضعیت اصلی/محاسبات)
            'hourly_leave_minutes': hourly_leave_minutes_by_date.get(current, 0),
            'hourly_leave_display': format_hl_display(hourly_leave_minutes_by_date.get(current, 0)),
        })
        current += timedelta(days=1)

    # محاسبه کارکرد کل ماه قبل از اعمال فیلتر
    total_work_hours_month = sum(d['work_hours'] for d in days_list)

    # اعمال فیلتر وضعیت
    if status_filter == 'complete':
        days_list = [d for d in days_list if d['status']['main_status'] == STATUS_COMPLETE]
    elif status_filter == 'night_shift':
        days_list = [d for d in days_list if d['status']['main_status'] == STATUS_NIGHT_SHIFT]
    elif status_filter == 'issues':
        issue_statuses = [STATUS_MISSING_EXIT, STATUS_MISSING_ENTER, STATUS_SEQUENCE_ERROR, STATUS_IMBALANCE]
        days_list = [d for d in days_list if d['status']['main_status'] in issue_statuses]
    elif status_filter == 'friday_holiday':
        days_list = [d for d in days_list if d['status']['is_friday'] or d['status']['is_holiday']]
    elif status_filter == 'no_attendance':
        days_list = [d for d in days_list if d['status']['main_status'] == STATUS_NO_ATTENDANCE]
    elif status_filter == 'leave':
        days_list = [d for d in days_list if d['status']['main_status'] == STATUS_LEAVE]

    # 🆕 محدود کردن نمایش/محاسبات به بازه تاریخ در صورت اعمال فیلتر
    if filter_applied and not filter_error:
        range_start = filter_from_g if filter_from_g else month_start_g
        range_end = filter_to_g if filter_to_g else month_end_g
        # فقط روزهای داخل بازه (برای جدول و محاسبات)
        days_list = [d for d in days_list if range_start <= d['date'] <= range_end]
        # محاسبات بر اساس همین لیست فیلتر شده
        total_work_hours_month = sum(d['work_hours'] for d in days_list)
        total_records = sum(len(d['records']) for d in days_list)
    else:
        total_work_hours_month = sum(d['work_hours'] for d in days_list)
        total_records = sum(len(d['records']) for d in days_list)

    MONTH_NAMES = {
        1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر',
        5: 'مرداد', 6: 'شهریور', 7: 'مهر', 8: 'آبان',
        9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
    }
    total_records = sum(len(d['records']) for d in days_list)

    # ============================================
    # 🆕 محاسبات موظفی و اضافه/کسر کار
    # ============================================
    # دریافت روزهای استراحت از DailyStatus
    daily_statuses = db.query(DailyStatus).filter(
        and_(
            DailyStatus.user_id == target_user_id,
            DailyStatus.status_date >= month_start_g,
            DailyStatus.status_date <= month_end_g,
            DailyStatus.status_code == 'R'
        )
    ).all()
    rest_dates = {ds.status_date for ds in daily_statuses}

    # ---------- ۱. موظفی ماهانه ----------
    work_days_in_month = 0
    leave_days_in_month = 0
    rest_days_in_month = 0
    current_calc = month_start_g
    while current_calc <= month_end_g:
        is_friday = current_calc.weekday() == 4
        is_holiday = current_calc in holiday_dates
        is_day_off = is_friday or is_holiday
        if not is_day_off:
            work_days_in_month += 1
            if current_calc in leaves_by_date:
                leave_days_in_month += 1
            elif current_calc in rest_dates:
                rest_days_in_month += 1
        current_calc += timedelta(days=1)

    duty_days_month = work_days_in_month - leave_days_in_month - rest_days_in_month
    monthly_required_minutes = compute_required_minutes_for_range(
        db=db, employee=target_employee,
        start_date=month_start_g, end_date=month_end_g,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
    )
    monthly_duty_hours = monthly_required_minutes / 60

    # ---------- ۲. موظفی لحظه‌ای ----------
    today_g = today_j.togregorian()
    if today_g < month_start_g:
        reference_date = month_start_g - timedelta(days=1)
    elif today_g > month_end_g:
        reference_date = month_end_g
    else:
        is_today_complete = False
        for day in days_list:
            if day['date'] == today_g:
                main_status = day['status']['main_status']
                if main_status in [STATUS_COMPLETE, STATUS_LEAVE] or day['is_holiday'] or day['is_friday']:
                    is_today_complete = True
                break
        reference_date = today_g if is_today_complete else today_g - timedelta(days=1)

    duty_days_until_ref = 0
    work_hours_until_ref = 0.0
    for day in days_list:
        if day['date'] <= reference_date:
            is_day_off = day['is_friday'] or day['is_holiday']
            is_leave = day['status']['main_status'] == STATUS_LEAVE
            is_rest = day['date'] in rest_dates
            if not is_day_off and not is_leave and not is_rest:
                duty_days_until_ref += 1
            work_hours_until_ref += day['work_hours']

    instant_required_minutes = compute_required_minutes_for_range(
        db=db, employee=target_employee,
        start_date=month_start_g, end_date=reference_date,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
    )
    instant_duty_hours = instant_required_minutes / 60

    # ---------- ۳ و ۴. اضافه/کسر کار ----------
    progress_percent = 0
    if monthly_duty_hours > 0:
        progress_percent = min(100, round((total_work_hours_month / monthly_duty_hours) * 100, 1))

    monthly_balance = total_work_hours_month - monthly_duty_hours
    instant_balance = work_hours_until_ref - instant_duty_hours

    reference_date_j = jdatetime.date.fromgregorian(date=reference_date)
    reference_date_display = reference_date_j.strftime('%Y/%m/%d')

    # ============================================
    # 🆕 تعیین شرایط نمایش کارت‌های هفتگی
    # ============================================
    is_current_month = (year == today_j.year and month == today_j.month)
    is_past_month = (year < today_j.year) or (year == today_j.year and month < today_j.month)

    # محاسبه شروع و پایان هفته‌ها (شنبه تا جمعه)
    today_weekday = today_g.weekday()
    days_since_saturday = (today_weekday + 2) % 7
    this_week_start_g = today_g - timedelta(days=days_since_saturday)
    this_week_end_g = this_week_start_g + timedelta(days=6)  # جمعه
    prev_week_start_g = this_week_start_g - timedelta(days=7)
    prev_week_end_g = this_week_start_g - timedelta(days=1)

    # 🆕 شرط ۱: کارت کارکرد این هفته فقط در ماه جاری
    show_this_week_card = is_current_month

    # 🆕 شرط ۲: کارت کارکرد هفته قبل فقط اگر کل هفته در ماه جاری باشد
    show_prev_week_card = False
    if is_current_month:
        prev_week_fully_in_month = (prev_week_start_g >= month_start_g and prev_week_end_g <= month_end_g)
        show_prev_week_card = prev_week_fully_in_month

    # 🆕 شرط ۳: کارت‌های اضافه/کسر هفتگی فقط در ماه‌های گذشته
    show_weekly_balance_cards = is_past_month

    # ---------- کارکرد این هفته (کل هفته، فقط روزهای درون ماه انتخاب‌شده) ----------
    this_week_hours = 0.0
    this_week_days = 0
    this_week_work_days = 0

    for day in days_list:
        # فقط روزهای این هفته که در ماه انتخاب‌شده هستند
        if this_week_start_g <= day['date'] <= this_week_end_g:
            # 🆕 کارکرد همه روزها (شامل جمعه و تعطیل)
            this_week_hours += day['work_hours']
            if day['work_hours'] > 0:
                this_week_days += 1  # روزهایی که کارکرد دارند (شامل جمعه‌کاری)

            # روزهای موظفی (فقط روزهای کاری غیر جمعه و غیر تعطیل)
            if not day['is_friday'] and not day['is_holiday']:
                is_leave = day['status']['main_status'] == STATUS_LEAVE
                is_rest = day['date'] in rest_dates
                if not is_leave and not is_rest:
                    this_week_work_days += 1

    this_week_required = compute_required_minutes_for_range(
        db=db, employee=target_employee,
        start_date=this_week_start_g, end_date=this_week_end_g,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
    )
    this_week_duty_hours = this_week_required / 60
    this_week_progress = min(100, round((this_week_hours / this_week_duty_hours) * 100,
                                        1)) if this_week_duty_hours > 0 else 0

    # ---------- کارکرد هفته قبل (کل هفته، فقط روزهای درون ماه انتخاب‌شده) ----------
    prev_week_hours = 0.0
    prev_week_days = 0
    prev_week_work_days = 0

    for day in days_list:
        # فقط روزهای هفته قبل که در ماه انتخاب‌شده هستند
        if prev_week_start_g <= day['date'] <= prev_week_end_g:
            # 🆕 کارکرد همه روزها (شامل جمعه و تعطیل)
            prev_week_hours += day['work_hours']
            if day['work_hours'] > 0:
                prev_week_days += 1  # روزهایی که کارکرد دارند (شامل جمعه‌کاری)

            # روزهای موظفی (فصل روزهای کاری غیر جمعه و غیر تعطیل)
            if not day['is_friday'] and not day['is_holiday']:
                is_leave = day['status']['main_status'] == STATUS_LEAVE
                is_rest = day['date'] in rest_dates
                if not is_leave and not is_rest:
                    prev_week_work_days += 1

    prev_week_required = compute_required_minutes_for_range(
        db=db, employee=target_employee,
        start_date=prev_week_start_g, end_date=prev_week_end_g,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
    )
    prev_week_duty_hours = prev_week_required / 60
    prev_week_progress = min(100, round((prev_week_hours / prev_week_duty_hours) * 100,
                                        1)) if prev_week_duty_hours > 0 else 0

    # ---------- میانگین کارکرد روزانه ----------
    # 🆕 همه روزهایی که کارکرد دارند (شامل جمعه‌کاری و تعطیل‌کاری)
    days_with_work = [d for d in days_list if d['work_hours'] > 0]
    daily_avg_hours = total_work_hours_month / len(days_with_work) if days_with_work else 0
    daily_avg_days = len(days_with_work)
    # ============================================
    # 🆕 محاسبه اضافه/کسر کار هفتگی (برای ماه‌های گذشته)
    # ============================================
    weekly_overtime_total = 0.0
    weekly_deficit_total = 0.0
    weeks_count = 0

    if show_weekly_balance_cards:
        # پیدا کردن اولین شنبه ماه
        first_day = month_start_g
        first_day_weekday = first_day.weekday()
        days_since_first_saturday = (first_day_weekday + 2) % 7
        first_saturday = first_day - timedelta(days=days_since_first_saturday)

        current_week_start = first_saturday
        while current_week_start <= month_end_g:
            current_week_end = current_week_start + timedelta(days=6)  # جمعه

            # محاسبه کارکرد و موظفی این هفته (فقط روزهای درون ماه)
            week_hours = 0.0
            week_duty_days = 0

            for day in days_list:
                if current_week_start <= day['date'] <= current_week_end:
                    # 🆕 کارکرد همه روزها (شامل جمعه و تعطیل)
                    week_hours += day['work_hours']

                    # روزهای موظفی (فقط روزهای کاری غیر جمعه و غیر تعطیل)
                    if not day['is_friday'] and not day['is_holiday']:
                        is_leave = day['status']['main_status'] == STATUS_LEAVE
                        is_rest = day['date'] in rest_dates
                        if not is_leave and not is_rest:
                            week_duty_days += 1

            week_required = compute_required_minutes_for_range(
                db=db, employee=target_employee,
                start_date=current_week_start, end_date=current_week_end,
                rest_dates=rest_dates, holiday_dates=holiday_dates,
                leaves_by_date=leaves_by_date,
                hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
            )
            week_duty_hours = week_required / 60
            week_balance = week_hours - week_duty_hours

            if week_duty_days > 0:  # فقط هفته‌هایی که روز کاری دارند
                weeks_count += 1
                if week_balance >= 0:
                    weekly_overtime_total += week_balance
                else:
                    weekly_deficit_total += abs(week_balance)

            current_week_start += timedelta(days=7)
    # ============================================
    # 🆕 ناوبری بین ماه‌ها
    # ============================================
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    available_years = list(range(today_j.year, today_j.year - 6, -1))
    months_list = [
        {'num': 1, 'name': 'فروردین'}, {'num': 2, 'name': 'اردیبهشت'},
        {'num': 3, 'name': 'خرداد'}, {'num': 4, 'name': 'تیر'},
        {'num': 5, 'name': 'مرداد'}, {'num': 6, 'name': 'شهریور'},
        {'num': 7, 'name': 'مهر'}, {'num': 8, 'name': 'آبان'},
        {'num': 9, 'name': 'آذر'}, {'num': 10, 'name': 'دی'},
        {'num': 11, 'name': 'بهمن'}, {'num': 12, 'name': 'اسفند'},
    ]

    return templates.TemplateResponse(request, "admin/user_attendance.html", {
        "user": user,
        "target_user_id": target_user_id,
        "target_employee": target_employee,
        "target_user": target_user,
        "year": year,
        "month": month,
        "month_name": MONTH_NAMES.get(month, ""),
        "days": days_list,
        "total_records": total_records,
        "is_admin": True,
        "is_super_admin": user.is_super_admin,
        "status_filter": status_filter or 'all',

        # ناوبری
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "available_years": available_years,
        "months_list": months_list,
        "is_current_month": is_current_month,

        # موظفی و اضافه/کسر کار
        "monthly_duty_display": format_hours_hhmm(monthly_duty_hours),
        "duty_days_month": duty_days_month,
        "instant_duty_display": format_hours_hhmm(instant_duty_hours),
        "duty_days_until_ref": duty_days_until_ref,
        "reference_date_display": reference_date_display,
        "monthly_balance": monthly_balance,
        "monthly_balance_display": format_hours_hhmm(monthly_balance),
        "monthly_is_overtime": monthly_balance >= 0,
        "instant_balance": instant_balance,
        "instant_balance_display": format_hours_hhmm(instant_balance),
        "instant_is_overtime": instant_balance >= 0,
        "total_work_hours_month": total_work_hours_month,
        "total_work_hours_display": format_hours_hhmm(total_work_hours_month),
        "progress_percent": progress_percent,

        # 🆕 کارکرد هفتگی (با شرط‌های نمایش)
        "show_this_week_card": show_this_week_card,
        "show_prev_week_card": show_prev_week_card,
        "show_weekly_balance_cards": show_weekly_balance_cards,
        "this_week_hours_display": format_hours_hhmm(this_week_hours),
        "this_week_days": this_week_days,
        "this_week_duty_display": format_hours_hhmm(this_week_duty_hours),
        "this_week_progress": this_week_progress,
        "prev_week_hours_display": format_hours_hhmm(prev_week_hours),
        "prev_week_days": prev_week_days,
        "prev_week_duty_display": format_hours_hhmm(prev_week_duty_hours),
        "prev_week_progress": prev_week_progress,

        # 🆕 میانگین کارکرد روزانه
        "daily_avg_hours_display": format_hours_hhmm(daily_avg_hours),
        "daily_avg_days": daily_avg_days,

        # 🆕 اضافه/کسر هفتگی (برای ماه‌های گذشته)
        "weekly_overtime_total_display": format_hours_hhmm(weekly_overtime_total),
        "weekly_deficit_total_display": format_hours_hhmm(weekly_deficit_total),
        "weeks_count": weeks_count,

        # 🆕 فیلتر بازه تاریخ
        "from_date": from_date or "",
        "to_date": to_date or "",
        "filter_applied": filter_applied,
        "filter_error": filter_error or "",
        "from_date_display": from_date_display,
        "to_date_display": to_date_display,
    })

from datetime import timedelta, date as date_type
from sqlalchemy import and_, func
import jdatetime
from typing import Optional
from fastapi import Query, Form
from fastapi.responses import RedirectResponse

from web.dependencies import require_super_admin
from web.security import hash_password
from models.employee import Employee
from models.user import User


@router.get("/admin/profile/{target_user_id}", response_class=HTMLResponse)
async def admin_view_profile(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """مشاهده پروفایل یک کاربر توسط مدیر"""
    enforce_permission(db, user, 'view_user_attendance')
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/", status_code=302)

    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    today_j = jdatetime.date.today()

    # محاسبات
    age = None
    birth_j_display = None
    if employee and employee.birth_date:
        today = date.today()
        age = today.year - employee.birth_date.year
        if (today.month, today.day) < (employee.birth_date.month, employee.birth_date.day):
            age -= 1
        birth_j_display = jdatetime.date.fromgregorian(date=employee.birth_date).strftime('%Y/%m/%d')

    service = None
    hire_j_display = None
    if employee and employee.hire_date:
        today = date.today()
        years = today.year - employee.hire_date.year
        months = today.month - employee.hire_date.month
        if today.day < employee.hire_date.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        service = {'years': years, 'months': months}
        hire_j_display = jdatetime.date.fromgregorian(date=employee.hire_date).strftime('%Y/%m/%d')

    termination_j_display = None
    if employee and employee.termination_date:
        termination_j_display = jdatetime.date.fromgregorian(date=employee.termination_date).strftime('%Y/%m/%d')

    # آواتار
    avatar_initials = ""
    avatar_color = "primary"
    if employee:
        avatar_initials = f"{employee.first_name[0] if employee.first_name else ''}{employee.last_name[0] if employee.last_name else ''}"
        name_hash = sum(ord(c) for c in employee.full_name)
        colors = ['primary', 'success', 'info', 'warning', 'danger', 'secondary', 'dark']
        avatar_color = colors[name_hash % len(colors)]

    # 🆕 دریافت شماره‌های تلفن کاربر مورد نظر
    target_phones = db.query(EmployeePhone).filter(
        EmployeePhone.user_id == target_user_id
    ).order_by(EmployeePhone.is_default.desc(), EmployeePhone.created_at).all()

    return templates.TemplateResponse(request, "admin/user_profile.html", {
        "user": user,
        "target_user": target_user,
        "employee": employee,
        "today_j": today_j,
        "age": age,
        "birth_j_display": birth_j_display,
        "service": service,
        "hire_j_display": hire_j_display,
        "termination_j_display": termination_j_display,
        "avatar_initials": avatar_initials,
        "avatar_color": avatar_color,
        "is_admin": True,
        "is_super_admin": user.is_super_admin,
        "target_phones": target_phones,
    })


@router.get("/admin/profile/{target_user_id}/edit", response_class=HTMLResponse)
async def admin_edit_profile_page(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """صفحه ویرایش پروفایل (مدیر ارشد یا مدیر دارای دسترسی edit_profile)"""
    enforce_permission(db, user, 'edit_profile')
    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    if not employee:
        return RedirectResponse(url=f"/admin/profile/{target_user_id}", status_code=302)

    # تبدیل تاریخ‌ها به شمسی برای فرم
    birth_j_value = ""
    if employee.birth_date:
        birth_j_value = jdatetime.date.fromgregorian(date=employee.birth_date).strftime('%Y/%m/%d')

    hire_j_value = ""
    if employee.hire_date:
        hire_j_value = jdatetime.date.fromgregorian(date=employee.hire_date).strftime('%Y/%m/%d')

    term_j_value = ""
    if employee.termination_date:
        term_j_value = jdatetime.date.fromgregorian(date=employee.termination_date).strftime('%Y/%m/%d')

    return templates.TemplateResponse(request, "admin/edit_user.html", {
        "user": user,
        "employee": employee,
        "birth_j_value": birth_j_value,
        "hire_j_value": hire_j_value,
        "term_j_value": term_j_value,
        "is_admin": True,
        "is_super_admin": True,
    })


@router.post("/admin/profile/{target_user_id}/edit")
async def admin_edit_profile_submit(
    request: Request,
    target_user_id: str,
    first_name: str = Form(...),
    last_name: str = Form(...),
    father_name: str = Form(""),
    national_code: str = Form(""),
    birth_date_str: str = Form(""),
    gender: str = Form(""),
    marital_status: str = Form(""),
    email: str = Form(""),
    hire_date_str: str = Form(""),
    department: str = Form(""),
    position: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form(""),
    termination_date_str: str = Form(""),
    termination_reason: str = Form(""),
    region_code: str = Form("NORMAL"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """ذخیره ویرایش پروفایل"""
    enforce_permission(db, user, 'edit_profile')
    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    if not employee:
        return RedirectResponse(url="/admin/users", status_code=302)

    try:
        employee.first_name = first_name.strip()
        employee.last_name = last_name.strip()
        employee.father_name = father_name.strip() or None
        employee.national_code = national_code.strip() or None
        employee.gender = gender or None
        employee.marital_status = marital_status or None
        employee.email = email.strip() or None
        employee.department = department or None
        employee.position = position.strip() or None
        employee.notes = notes.strip() or None

        # تاریخ‌ها
        if birth_date_str.strip():
            employee.birth_date = jdatetime.datetime.strptime(birth_date_str.strip(), "%Y/%m/%d").date().togregorian()
        else:
            employee.birth_date = None

        if hire_date_str.strip():
            employee.hire_date = jdatetime.datetime.strptime(hire_date_str.strip(), "%Y/%m/%d").date().togregorian()
        else:
            employee.hire_date = None

        # وضعیت فعال/غیرفعال
        employee.is_active = (is_active == "on")

        # 🆕 ذخیره منطقه و ثبت در تاریخچه
        old_region = employee.region_code
        employee.region_code = region_code
        
        if old_region != region_code:
            region_history = EmployeeRegion(
                user_id=target_user_id,
                region_code=region_code,
                effective_from=date.today(),
                approved_by=user.user_id,
                reason=f"تغییر منطقه از {old_region} توسط مدیر ارشد"
            )
            db.add(region_history)
            
            audit_log = PolicyAuditLog(
                entity_type='employee_region',
                entity_id=target_user_id,
                action='CHANGE',
                old_value=old_region,
                new_value=region_code,
                changed_by=user.user_id,
                reason="تغییر منطقه توسط مدیر ارشد"
            )
            db.add(audit_log)

        if employee.is_active:
            # اگر فعال شد، اطلاعات ترک کار پاک شود
            employee.termination_date = None
            employee.termination_reason = None
        else:
            if termination_date_str.strip():
                employee.termination_date = jdatetime.datetime.strptime(termination_date_str.strip(), "%Y/%m/%d").date().togregorian()
            if termination_reason.strip():
                employee.termination_reason = termination_reason.strip()

        db.commit()
        return RedirectResponse(url=f"/admin/profile/{target_user_id}?saved=1", status_code=302)
    except Exception as e:
        db.rollback()
        return RedirectResponse(url=f"/admin/profile/{target_user_id}/edit?error={str(e)}", status_code=302)


@router.post("/admin/users/{target_user_id}/reset-password")
async def admin_reset_password(
        target_user_id: str,
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """ریست رمز عبور به کد ملی (نیازمند دسترسی reset_password)"""
    enforce_permission(db, user, 'reset_password')
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/users", status_code=302)

    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()

    # ✅ حالت 1: اصلاً پروفایل ندارد
    if not employee:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=no-profile",
            status_code=302
        )

    # ✅ حالت 2: کد ملی خالی است
    if not employee.national_code or not employee.national_code.strip():
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=no-national-code",
            status_code=302
        )

    target_user.password_hash = hash_password(employee.national_code)
    target_user.must_change_password = True
    db.commit()

    return RedirectResponse(url=f"/admin/profile/{target_user_id}?password_reset=1", status_code=302)


@router.post("/admin/users/{target_user_id}/change-role")
async def admin_change_role(
    target_user_id: str,
    new_role: str = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """تغییر نقش کاربر (نیازمند دسترسی change_role)"""
    enforce_permission(db, user, 'change_role')
    if new_role not in ('user', 'admin', 'super_admin'):
        return RedirectResponse(url="/admin/users?error=invalid-role", status_code=302)

    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/users", status_code=302)

    # جلوگیری از تغییر نقش خود
    if target_user.user_id == user.user_id:
        return RedirectResponse(url="/admin/users?error=self-role", status_code=302)

    target_user.role = new_role
    db.commit()

    return RedirectResponse(url=f"/admin/profile/{target_user_id}?role_changed=1", status_code=302)


@router.post("/admin/users/{target_user_id}/toggle-web")
async def admin_toggle_web(
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """فعال/غیرفعال کردن دسترسی وب (نیازمند دسترسی toggle_web)"""
    enforce_permission(db, user, 'toggle_web')
    target_user = db.query(User).filter(User.user_id == target_user_id).first()
    if not target_user:
        return RedirectResponse(url="/admin/users", status_code=302)

    # جلوگیری از غیرفعال کردن خود
    if target_user.user_id == user.user_id:
        return RedirectResponse(url="/admin/users?error=self-disable", status_code=302)

    target_user.web_enabled = not target_user.web_enabled
    db.commit()

    return RedirectResponse(url=f"/admin/profile/{target_user_id}?web_toggled=1", status_code=302)


# 🆕 تنظیمات آپلود عکس
UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads" / "avatars"
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 مگابایت


@router.post("/admin/profile/{target_user_id}/upload-photo")
async def admin_upload_photo(
    target_user_id: str,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """آپلود عکس پروفایل کاربر (توسط مدیر)"""
    enforce_permission(db, user, 'upload_photo')
    # اعتبارسنجی نوع فایل
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=نوع فایل مجاز نیست (فقط JPG/PNG/WEBP)",
            status_code=302
        )

    # بررسی اندازه فایل
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=حجم فایل بیش از 2 مگابایت است",
            status_code=302
        )

    # بررسی وجود کارمند
    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    if not employee:
        return RedirectResponse(url="/admin/users", status_code=302)

    try:
        # ساخت پوشه اگر وجود ندارد
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # حذف عکس قبلی
        if employee.photo_path:
            old_file = Path(__file__).parent.parent / "static" / employee.photo_path.replace("/static/", "").replace("\\", "/")
            if old_file.exists():
                old_file.unlink()

        # ذخیره فایل جدید با نام user_id
        filename = f"{target_user_id}_{int(time.time())}{ext}"
        file_path = UPLOAD_DIR / filename

        with open(file_path, 'wb') as f:
            f.write(content)

        # آپدیت دیتابیس
        employee.photo_path = f"/static/uploads/avatars/{filename}"
        db.commit()

        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?photo_uploaded=1",
            status_code=302
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/profile/{target_user_id}?error=خطا در آپلود: {str(e)}",
            status_code=302
        )


@router.post("/admin/profile/{target_user_id}/delete-photo")
async def admin_delete_photo(
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف عکس پروفایل کاربر"""
    enforce_permission(db, user, 'upload_photo')
    employee = db.query(Employee).filter(Employee.user_id == target_user_id).first()
    if not employee:
        return RedirectResponse(url="/admin/users", status_code=302)

    if employee.photo_path:
        # حذف فایل
        file_path = Path(__file__).parent.parent / "static" / employee.photo_path.replace("/static/", "").replace("\\", "/")
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass

        employee.photo_path = None
        db.commit()

    return RedirectResponse(
        url=f"/admin/profile/{target_user_id}?photo_deleted=1",
        status_code=302
    )


from datetime import datetime
from models.attendance import Attendance


@router.post("/admin/attendance/edit/change-punch")
async def admin_change_punch(
    request: Request,
    record_id: int = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """تغییر وضعیت ورود/خروج"""
    enforce_permission(db, user, 'change_punch')
    record = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not record:
        return RedirectResponse(url="/admin/attendance?error=رکورد یافت نشد", status_code=302)

    record.punch = 1 if record.punch == 0 else 0
    db.commit()

    referer = request.headers.get("referer", "/admin/attendance")
    return RedirectResponse(url=build_redirect_url(referer, "success", "وضعیت تغییر کرد"), status_code=302)


@router.post("/admin/attendance/edit/delete")
async def admin_delete_record(
    request: Request,
    record_id: int = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف رکورد تردد"""
    enforce_permission(db, user, 'delete_attendance')
    record = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not record:
        return RedirectResponse(url="/admin/attendance?error=رکورد یافت نشد", status_code=302)

    # حذف (soft delete)
    record.is_deleted = True
    db.commit()

    # 🆕 بازگشت به صفحه قبل با پارامتر موفقیت
    referer = request.headers.get("referer", "/admin/attendance")
    redirect_url = add_query_param(referer, "success", "رکورد حذف شد")
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/admin/attendance/edit/add")
async def admin_add_record(
    request: Request,
    user_id: str = Form(...),
    date_str: str = Form(...),
    time_str: str = Form(...),
    punch: int = Form(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """افزودن رکورد تردد"""
    enforce_permission(db, user, 'add_attendance')
    try:
        # تبدیل تاریخ شمسی
        j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
        g_date = j_date.togregorian()

        # ترکیب تاریخ و ساعت
        hour, minute = map(int, time_str.split(':'))
        timestamp = datetime(g_date.year, g_date.month, g_date.day, hour, minute)

        # ساخت رکورد جدید
        record = Attendance(
            user_id=user_id,
            timestamp=timestamp,
            punch=punch,
            status=15,  # دستی
            source='L'  # دستی
        )
        db.add(record)
        db.commit()

        # 🆕 بازگشت به صفحه قبل با پارامتر موفقیت
        referer = request.headers.get("referer", "/admin/attendance")
        redirect_url = add_query_param(referer, "success", "رکورد اضافه شد")
        return RedirectResponse(url=redirect_url, status_code=302)
    except Exception as e:
        referer = request.headers.get("referer", "/admin/attendance")
        redirect_url = add_query_param(referer, "error", str(e))
        return RedirectResponse(url=redirect_url, status_code=302)

@router.get("/admin/incomplete", response_class=HTMLResponse)
async def admin_incomplete_attendance(
    request: Request,
    from_date_str: Optional[str] = Query(None),
    to_date_str: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    include_night_shift: Optional[str] = Query(None),
    show_all: Optional[str] = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمایش ترددهای ناقص با فیلترهای پیشرفته"""
    enforce_permission(db, user, 'view_incomplete')
    from core.attendance_analyzer import AttendanceAnalyzer
    from models.employee import Employee
    from models.attendance import Attendance
    from sqlalchemy import and_, func

    # 🆕 بررسی اینکه آیا فیلتری اعمال شده یا خیر
    has_filter = any([from_date_str, to_date_str, department, issue_type, show_all])

    filtered_incomplete = []
    stats = {'total': 0, 'missing_enter': 0, 'missing_exit': 0, 'imbalance': 0, 'sequence_error': 0}
    by_department = {}
    from_date_display = ""
    to_date_display = ""

    if has_filter:
        today_j = jdatetime.date.today()

        # تاریخ پیش‌فرض
        if from_date_str:
            try:
                j_from = jdatetime.datetime.strptime(from_date_str, "%Y/%m/%d").date()
                from_date = j_from.togregorian()
            except:
                from_date = date(today_j.year, today_j.month, 1)
        else:
            from_date = date(today_j.year, today_j.month, 1)

        if to_date_str:
            try:
                j_to = jdatetime.datetime.strptime(to_date_str, "%Y/%m/%d").date()
                to_date = j_to.togregorian()
            except:
                to_date = today_j.togregorian()
        else:
            to_date = today_j.togregorian()

        from_date_display = jdatetime.date.fromgregorian(date=from_date).strftime('%Y/%m/%d')
        to_date_display = jdatetime.date.fromgregorian(date=to_date).strftime('%Y/%m/%d')

        # تحلیلگر
        analyzer = AttendanceAnalyzer()
        try:
            incomplete_raw = analyzer.get_incomplete_attendances(from_date, to_date)

            # 🆕 بازطبقه‌بندی: تفکیک خطای ترتیب از ورود/خروج بدون خروج/ورود
            for item in incomplete_raw:
                # دریافت رکوردهای کامل روز
                day_attendances = analyzer.db.query(Attendance).filter(
                    and_(
                        Attendance.user_id == item['user_id'],
                        func.date(Attendance.timestamp) == item['date'],
                        Attendance.is_deleted == False
                    )
                ).order_by(Attendance.timestamp).all()

                sorted_records = sorted(day_attendances, key=lambda x: x.timestamp)

                if not sorted_records:
                    continue

                # بررسی ۱: دو رکورد هم‌نوع پشت سر هم = خطای ترتیب واقعی
                has_consecutive_error = False
                consecutive_detail = ""
                for i in range(1, len(sorted_records)):
                    if sorted_records[i].punch == sorted_records[i - 1].punch:
                        has_consecutive_error = True
                        if sorted_records[i].punch == 0:
                            consecutive_detail = "دو ورود پشت سر هم"
                        else:
                            consecutive_detail = "دو خروج پشت سر هم"
                        break

                if has_consecutive_error:
                    item['issue'] = 'sequence_error'
                    item['issue_detail'] = consecutive_detail
                    item['enter_count'] = len([a for a in sorted_records if a.punch == 0])
                    item['exit_count'] = len([a for a in sorted_records if a.punch == 1])
                else:
                    # بررسی ۲: اگر قبلاً sequence_error بوده ولی واقعاً ناقص است
                    enters = [a for a in sorted_records if a.punch == 0]
                    exits = [a for a in sorted_records if a.punch == 1]

                    if item['issue'] == 'sequence_error':
                        if len(enters) > len(exits):
                            item['issue'] = 'missing_exit'
                            item['issue_detail'] = ""
                        elif len(exits) > len(enters):
                            item['issue'] = 'missing_enter'
                            item['issue_detail'] = ""
                    else:
                        item['issue_detail'] = ""

            # 🆕 فیلتر شیفت شب - منطق ساده‌تر و دقیق‌تر
            for item in incomplete_raw:
                is_night_shift = False

                # حالت ۱: ورود بدون خروج → بررسی اولین تردد فردا
                if item['issue'] == 'missing_exit' and item['enter_count'] > 0 and item['exit_count'] == 0:
                    next_day = item['date'] + timedelta(days=1)
                    first_next_day_record = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == next_day,
                            Attendance.is_deleted == False
                        )
                    ).order_by(Attendance.timestamp.asc()).first()

                    # ✅ فقط بررسی کنیم اولین تردد فردا خروج باشد
                    if first_next_day_record and first_next_day_record.punch == 1:
                        is_night_shift = True

                # حالت ۲: خروج بدون ورود → بررسی آخرین تردد دیروز
                elif item['issue'] == 'missing_enter' and item['exit_count'] > 0 and item['enter_count'] == 0:
                    prev_day = item['date'] - timedelta(days=1)
                    last_prev_day_record = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == prev_day,
                            Attendance.is_deleted == False
                        )
                    ).order_by(Attendance.timestamp.desc()).first()

                    # ✅ فقط بررسی کنیم آخرین تردد دیروز ورود باشد
                    if last_prev_day_record and last_prev_day_record.punch == 0:
                        is_night_shift = True

                # حالت ۳: عدم تعادل
                elif item['issue'] == 'imbalance':
                    day_attendances = analyzer.db.query(Attendance).filter(
                        and_(
                            Attendance.user_id == item['user_id'],
                            func.date(Attendance.timestamp) == item['date'],
                            Attendance.is_deleted == False
                        )
                    ).order_by(Attendance.timestamp).all()
                    enters = [a for a in day_attendances if a.punch == 0]
                    exits = [a for a in day_attendances if a.punch == 1]

                    # خروج بیشتر از ورود → بررسی آخرین تردد دیروز
                    if len(exits) > len(enters):
                        prev_day = item['date'] - timedelta(days=1)
                        last_prev_day_record = analyzer.db.query(Attendance).filter(
                            and_(
                                Attendance.user_id == item['user_id'],
                                func.date(Attendance.timestamp) == prev_day,
                                Attendance.is_deleted == False
                            )
                        ).order_by(Attendance.timestamp.desc()).first()

                        # ✅ فقط بررسی کنیم آخرین تردد دیروز ورود باشد
                        if last_prev_day_record and last_prev_day_record.punch == 0:
                            # بررسی کنیم با حذف خروج‌های صبح زود، تعادل برقرار می‌شود
                            early_exits = [e for e in exits if e.timestamp.hour < 8]
                            if early_exits:
                                adjusted_exit_count = len(exits) - len(early_exits)
                                if len(enters) == adjusted_exit_count:
                                    is_night_shift = True

                    # ورود بیشتر از خروج → بررسی اولین تردد فردا
                    elif len(enters) > len(exits):
                        next_day = item['date'] + timedelta(days=1)
                        first_next_day_record = analyzer.db.query(Attendance).filter(
                            and_(
                                Attendance.user_id == item['user_id'],
                                func.date(Attendance.timestamp) == next_day,
                                Attendance.is_deleted == False
                            )
                        ).order_by(Attendance.timestamp.asc()).first()

                        # ✅ فقط بررسی کنیم اولین تردد فردا خروج باشد
                        if first_next_day_record and first_next_day_record.punch == 1:
                            late_enters = [e for e in enters if e.timestamp.hour >= 22]
                            if late_enters:
                                adjusted_enter_count = len(enters) - len(late_enters)
                                if adjusted_enter_count == len(exits):
                                    is_night_shift = True

                # اگر شیفت شب است و کاربر نخواسته نمایش دهد، رد کن
                if is_night_shift and include_night_shift != '1':
                    continue
                employee = analyzer.db.query(Employee).filter(Employee.user_id == item['user_id']).first()
                if employee:
                    item['full_name'] = employee.full_name
                    item['department'] = employee.department or 'بدون گروه'
                else:
                    item['full_name'] = f"کاربر {item['user_id']}"
                    item['department'] = 'بدون گروه'

                item['is_night_shift'] = is_night_shift

                # 🆕 تبدیل تاریخ به شمسی برای نمایش و لینک‌ها
                j_date = jdatetime.date.fromgregorian(date=item['date'])
                item['date_j'] = j_date.strftime('%Y/%m/%d')
                item['year_j'] = j_date.year
                item['month_j'] = j_date.month

                filtered_incomplete.append(item)

            # فیلتر دپارتمان
            if department:
                filtered_incomplete = [i for i in filtered_incomplete if i['department'] == department]

            # فیلتر نوع نقص
            if issue_type:
                filtered_incomplete = [i for i in filtered_incomplete if i['issue'] == issue_type]

            # آمار
            stats = {
                'total': len(filtered_incomplete),
                'missing_enter': sum(1 for i in filtered_incomplete if i['issue'] == 'missing_enter'),
                'missing_exit': sum(1 for i in filtered_incomplete if i['issue'] == 'missing_exit'),
                'imbalance': sum(1 for i in filtered_incomplete if i['issue'] == 'imbalance'),
                'sequence_error': sum(1 for i in filtered_incomplete if i['issue'] == 'sequence_error'),
            }

            # گروه‌بندی بر اساس دپارتمان
            for item in filtered_incomplete:
                dept = item['department']
                if dept not in by_department:
                    by_department[dept] = []
                by_department[dept].append(item)

        finally:
            analyzer.close()

    dept_names = {
        '1': 'رسمی', '2': 'وظیفه', '3': 'خریدخدمت',
        '4': 'قراردادی', '5': 'پزشک', 'بدون گروه': 'بدون گروه'
    }

    return templates.TemplateResponse(request, "admin/incomplete.html", {
        "user": user,
        "from_date_str": from_date_display,
        "to_date_str": to_date_display,
        "department": department or "",
        "issue_type": issue_type or "",
        "include_night_shift": include_night_shift or "0",
        "show_all": show_all,
        "has_filter": has_filter,
        "incomplete_list": filtered_incomplete,
        "stats": stats,
        "by_department": by_department,
        "dept_names": dept_names,
        "is_admin": True,
    })