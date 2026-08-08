"""پنل مدیریت"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from web.dependencies import get_db, require_admin
from models.user import User
from models.leave_request import LeaveRequest
from datetime import timedelta, date as date_type
from sqlalchemy import and_, func
import jdatetime
from typing import Optional
from fastapi import Query

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


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    users = db.query(User).order_by(User.user_id).all()

    user_details = []
    for u in users:
        emp = db.query(Employee).filter(Employee.user_id == u.user_id).first()
        user_details.append({'web_user': u, 'employee': emp})

    return templates.TemplateResponse(request, "admin/users.html", {
        "user": user,
        "users": user_details,
        "is_admin": True,
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

        enters = [r for r in day_records if r.punch == 0]
        exits = [r for r in day_records if r.punch == 1]

        work_hours = 0
        first_enter = min(enters, key=lambda x: x.timestamp).timestamp if enters else None
        last_exit = max(exits, key=lambda x: x.timestamp).timestamp if exits else None

        if first_enter and last_exit:
            diff = (last_exit - first_enter).total_seconds() / 3600
            work_hours = max(0, diff)

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