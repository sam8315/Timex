"""پنل مدیریت"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_admin
from models.user import User
from models.leave_request import LeaveRequest
from datetime import timedelta, date, date as date_type
from sqlalchemy import and_, func
import jdatetime
from typing import Optional
from fastapi import Query
from fastapi import UploadFile, File
from pathlib import Path
import os
from web.routes.attendance import calculate_work_hours, STATUS_NIGHT_SHIFT

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

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    total_employees = db.query(Employee).filter(Employee.is_active == True).count()
    total_web_users = db.query(User).filter(User.web_enabled == True).count()
    pending_requests = db.query(LeaveRequest).filter(LeaveRequest.status == 'P').count()

    pending_list = db.query(LeaveRequest).filter(
        LeaveRequest.status == 'P'
    ).order_by(LeaveRequest.created_at.asc()).limit(10).all()

    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "user": user,
        "total_employees": total_employees,
        "total_web_users": total_web_users,
        "pending_requests": pending_requests,
        "pending_list": pending_list,
        "is_admin": True,
    })


from sqlalchemy import or_


@router.get("/users", response_class=HTMLResponse)
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

@router.get("/attendance", response_class=HTMLResponse)
async def admin_attendance(
    request: Request,
    date_str: Optional[str] = None,
    department: Optional[str] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمای روزانه تردد همه کارمندان"""
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
    employees = query.order_by(Employee.department, Employee.first_name).all()

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
        if daily_status:
            if daily_status in ('AL', 'SL', 'RL', 'UL'):
                status_label = '🌴 مرخصی'
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
        elif not user_atts:
            if is_friday or holiday:
                status_label = '🟡 تعطیل'
                status_color = 'warning'
            else:
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
            'first_enter': first_enter,
            'last_exit': last_exit,
            'total_punches': len(user_atts),
            'enter_count': len(enters),
            'exit_count': len(exits),
            'status_label': status_label,
            'status_color': status_color,
            'has_detail': len(user_atts) > 0,
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


@router.get("/attendance/user/{target_user_id}", response_class=HTMLResponse)
async def admin_user_attendance(
    request: Request,
    target_user_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="filter"),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """نمای ماهانه تردد یک کاربر خاص (برای مدیر) - مشابه صفحه کاربر عادی"""
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

    # 🆕 دریافت ترددها با حاشیه 1 روز (برای شیفت شب)
    records = db.query(Attendance).filter(
        and_(
            Attendance.user_id == target_user_id,
            Attendance.timestamp >= month_start_g - timedelta(days=1),
            Attendance.timestamp <= month_end_g + timedelta(days=2),
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    # 🆕 دریافت تعطیلات ماه
    holidays = db.query(Holiday).filter(
        and_(
            Holiday.holiday_date >= month_start_g,
            Holiday.holiday_date <= month_end_g,
            Holiday.is_national == True
        )
    ).all()
    holiday_dates = {h.holiday_date: h.title for h in holidays}

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

        # 🆕 تحلیل وضعیت با تابع مشترک
        status_info = analyze_day_status(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title
        )

        # 🆕 محاسبه کارکرد با در نظر گرفتن شیفت شب
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
            'is_friday': is_friday,
            'is_holiday': holiday_title is not None,
            'holiday_title': holiday_title,
            'status': status_info,
        })
        current += timedelta(days=1)

    # 🆕 اعمال فیلتر وضعیت
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

    MONTH_NAMES = {
        1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر',
        5: 'مرداد', 6: 'شهریور', 7: 'مهر', 8: 'آبان',
        9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
    }

    total_records = sum(len(d['records']) for d in days_list)
    # 🆕 ناوبری بین ماه‌ها
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # 🆕 لیست سال‌ها و ماه‌ها
    available_years = list(range(today_j.year, today_j.year - 6, -1))
    months_list = [
        {'num': 1, 'name': 'فروردین'}, {'num': 2, 'name': 'اردیبهشت'},
        {'num': 3, 'name': 'خرداد'}, {'num': 4, 'name': 'تیر'},
        {'num': 5, 'name': 'مرداد'}, {'num': 6, 'name': 'شهریور'},
        {'num': 7, 'name': 'مهر'}, {'num': 8, 'name': 'آبان'},
        {'num': 9, 'name': 'آذر'}, {'num': 10, 'name': 'دی'},
        {'num': 11, 'name': 'بهمن'}, {'num': 12, 'name': 'اسفند'},
    ]
    is_current_month = (year == today_j.year and month == today_j.month)


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
        "status_filter": status_filter or 'all',
        # 🆕 متغیرهای ناوبری
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "available_years": available_years,
        "months_list": months_list,
        "is_current_month": is_current_month,
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


@router.get("/profile/{target_user_id}", response_class=HTMLResponse)
async def admin_view_profile(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """مشاهده پروفایل یک کاربر توسط مدیر"""
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
    })


@router.get("/profile/{target_user_id}/edit", response_class=HTMLResponse)
async def admin_edit_profile_page(
    request: Request,
    target_user_id: str,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """صفحه ویرایش پروفایل (فقط مدیر ارشد)"""
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


@router.post("/profile/{target_user_id}/edit")
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
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """ذخیره ویرایش پروفایل"""
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


@router.post("/users/{target_user_id}/reset-password")
async def admin_reset_password(
        target_user_id: str,
        user: User = Depends(require_super_admin),
        db: Session = Depends(get_db)
):
    """ریست رمز عبور به کد ملی (فقط مدیر ارشد)"""
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


@router.post("/users/{target_user_id}/change-role")
async def admin_change_role(
    target_user_id: str,
    new_role: str = Form(...),
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """تغییر نقش کاربر (فقط مدیر ارشد)"""
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


@router.post("/users/{target_user_id}/toggle-web")
async def admin_toggle_web(
    target_user_id: str,
    user: User = Depends(require_super_admin),
    db: Session = Depends(get_db)
):
    """فعال/غیرفعال کردن دسترسی وب (فقط مدیر ارشد)"""
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


@router.post("/profile/{target_user_id}/upload-photo")
async def admin_upload_photo(
    target_user_id: str,
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """آپلود عکس پروفایل کاربر (توسط مدیر)"""
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
        filename = f"{target_user_id}{ext}"
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


@router.post("/profile/{target_user_id}/delete-photo")
async def admin_delete_photo(
    target_user_id: str,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """حذف عکس پروفایل کاربر"""
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


@router.post("/attendance/edit/change-punch")
async def admin_change_punch(
        request: Request,
        record_id: int = Form(...),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """تغییر وضعیت ورود/خروج"""
    record = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not record:
        return RedirectResponse(url="/admin/attendance?error=رکورد یافت نشد", status_code=302)

    # تغییر punch (0→1 یا 1→0)
    record.punch = 1 if record.punch == 0 else 0
    record.source = 'L'  # دستی
    db.commit()

    # بازگشت به صفحه قبل
    referer = request.headers.get("referer", "/admin/attendance")
    return RedirectResponse(url=f"{referer}?success=وضعیت تغییر کرد", status_code=302)


@router.post("/attendance/edit/delete")
async def admin_delete_record(
        request: Request,
        record_id: int = Form(...),
        user: User = Depends(require_admin),
        db: Session = Depends(get_db)
):
    """حذف رکورد تردد"""
    record = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not record:
        return RedirectResponse(url="/admin/attendance?error=رکورد یافت نشد", status_code=302)

    user_id = record.user_id
    record_date = record.timestamp.date()

    # حذف (soft delete)
    record.is_deleted = True
    db.commit()

    referer = request.headers.get("referer", "/admin/attendance")
    return RedirectResponse(url=f"{referer}?success=رکورد حذف شد", status_code=302)


@router.post("/attendance/edit/add")
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

        referer = request.headers.get("referer", "/admin/attendance")
        return RedirectResponse(url=f"{referer}?success=رکورد اضافه شد", status_code=302)
    except Exception as e:
        referer = request.headers.get("referer", "/admin/attendance")
        return RedirectResponse(url=f"{referer}?error={str(e)}", status_code=302)


@router.get("/incomplete", response_class=HTMLResponse)
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