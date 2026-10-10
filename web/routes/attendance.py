"""صفحه رکوردهای تردد با تحلیل وضعیت"""
from datetime import timedelta
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_
import jdatetime
from typing import Optional

from models.employee import Employee
from web.dependencies import get_db, check_password_change
from models.user import User
from models.attendance import Attendance
from models.holiday import Holiday
from models.leave_request import LeaveRequest  # 🆕
from models.daily_status import DailyStatus
from web.services.attendance_policy_service import (
    compute_required_minutes_for_range,
    resolve_policy,
    compute_late_early_for_day,
)
from web.services.hourly_leave_service import (
    get_approved_hl_minutes,
    get_approved_hl_intervals,
    format_hl_display,
)
from web.services.hourly_mission_service import (
    get_approved_hourly_mission_minutes,
    get_approved_hourly_missions_for_display,
    format_hm_display,
)
from web.services.travel_leave_service import build_leave_days_by_date

router = APIRouter(tags=["Attendance"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

MONTH_NAMES = {
    1: 'فروردین', 2: 'اردیبهشت', 3: 'خرداد', 4: 'تیر',
    5: 'مرداد', 6: 'شهریور', 7: 'مهر', 8: 'آبان',
    9: 'آذر', 10: 'دی', 11: 'بهمن', 12: 'اسفند'
}

DAY_NAMES_FA = {
    0: 'دوشنبه', 1: 'سه‌شنبه', 2: 'چهارشنبه',
    3: 'پنج‌شنبه', 4: 'جمعه', 5: 'شنبه', 6: 'یکشنبه'
}

# ============================================
# Central Attendance Engine (منبع واحد حقیقت)
# منطق محاسبه تردد از `core/attendance_calculator.py` وارد می‌شود.
# نام‌ها برای سازگاری با مصرف‌کننده‌های موجود (admin.py, policy service)
# دوباره export می‌شوند — رفتار محاسباتی بدون تغییر است.
# ============================================
from core.attendance_calculator import (
    # وضعیت‌های اصلی
    STATUS_COMPLETE,
    STATUS_NIGHT_SHIFT,
    STATUS_MISSING_EXIT,
    STATUS_MISSING_ENTER,
    STATUS_SEQUENCE_ERROR,
    STATUS_IMBALANCE,
    STATUS_NO_ATTENDANCE,
    STATUS_LEAVE,
    # هشدارهای ترکیبی
    WARN_ABNORMAL_GAP,
    WARN_DUPLICATE,
    WARN_ABNORMAL_TIME,
    WARN_TOO_MANY,
    WARN_FRIDAY_WORK,
    WARN_HOLIDAY_WORK,
    # منطق محاسبه
    analyze_day_status,
    calculate_work_hours,
    # موتور مرکزی (Phase 3): یک‌جا status + work_hours
    compute_day_attendance,
)


# ============================================
# 🆕 توابع کمکی موظفی
# ============================================

def format_hours_hhmm(hours: float) -> str:
    """تبدیل ساعت اعشاری به فرمت H:MM"""
    if hours is None:
        return '-'
    total_minutes = int(round(hours * 60))
    sign = '-' if total_minutes < 0 else ''
    total_minutes = abs(total_minutes)
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{sign}{h}:{m:02d}"


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="filter"),
    user: User = Depends(check_password_change),
    db: Session = Depends(get_db)
):
    today_j = jdatetime.date.today()
    if not year:
        year = today_j.year
    if not month:
        month = today_j.month

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
            Attendance.user_id == user.user_id,
            Attendance.timestamp >= month_start_g - timedelta(days=1),
            Attendance.timestamp <= month_end_g + timedelta(days=2),
            Attendance.is_deleted == False
        )
    ).order_by(Attendance.timestamp).all()

    # 🆕 دریافت گروه کاربر (بر اساس دپارتمان) - FIXED: use employee instance
    from web.services.membership_resolve import membership_code_for
    emp = db.query(Employee).filter(Employee.user_id == user.user_id).first()
    user_group = membership_code_for(db, emp, month_start_g) if emp else None

    # 🆕 دریافت مرخصی‌های تایید شده برای بازه ماه (فقط مرخصی‌های روزانه، HL جداگانه پردازش می‌شود)
    approved_leaves = db.query(LeaveRequest).filter(
        and_(
            LeaveRequest.user_id == user.user_id,
            LeaveRequest.status == 'A',
            LeaveRequest.leave_type != 'HL',  # ✅ HL 제외: HL باید در leaves_by_date نباشد
            LeaveRequest.from_date <= month_end_g,
            LeaveRequest.to_date >= month_start_g
        )
    ).all()

    # دریافت تعطیلات: نه فقط ماه جاری، بلکه کل بازه مرخصی‌های مورد نیاز
    holiday_start = month_start_g
    holiday_end = month_end_g

    if approved_leaves:
        holiday_start = min(
            holiday_start,
            min(leave.from_date for leave in approved_leaves)
        )
        holiday_end = max(
            holiday_end,
            max(leave.to_date for leave in approved_leaves)
        )
    holiday_query = db.query(Holiday).filter(
        and_(
            Holiday.holiday_date >= holiday_start,
            Holiday.holiday_date <= holiday_end
        )
    )
    if user_group:
        # ملی یا گروه کاربر
        holiday_query = holiday_query.filter(
            or_(Holiday.group_id == None, Holiday.group_id == user_group)
        )
    else:
        # فقط ملی
        holiday_query = holiday_query.filter(Holiday.group_id == None)

    holidays = holiday_query.all()
    holiday_dates = {h.holiday_date: h.title for h in holidays}


    # 🆕 ساخت دیکشنری مرخصی‌ها بر اساس تاریخ (فقط full-day leaves: AL, SL, RL, CW, ...)
    # Travel Leave (TL) روزها در build_leave_days_by_date مرکزی محاسبه می‌شوند
    LEAVE_TYPE_NAMES_LOCAL = {
        'AL': 'استحقاقی',
        'SL': 'استعلاجی',
        'RL': 'تشویقی',
        'CW': 'ذخیره',
        'TL': 'توراهی',
    }
    leaves_by_date = build_leave_days_by_date(
        approved_leaves, holiday_dates, month_start_g, month_end_g
    )

    # Phase 7: Fetch approved hourly leave minutes by date
    hourly_leave_minutes_by_date = get_approved_hl_minutes(
        db=db, employee=emp,
        start_date=month_start_g, end_date=month_end_g
    )
    hl_intervals_by_date = get_approved_hl_intervals(
        db=db, employee=emp,
        start_date=month_start_g, end_date=month_end_g
    )

    # Phase 5: Fetch approved hourly mission minutes by date
    hourly_mission_minutes_by_date = get_approved_hourly_mission_minutes(
        db=db, employee=emp,
        start_date=month_start_g, end_date=month_end_g
    )

    # Phase 6A: Approved HM missions for display (independent of deduct policy)
    hourly_missions_by_date = get_approved_hourly_missions_for_display(
        db=db, employee=emp,
        start_date=month_start_g, end_date=month_end_g
    )

    # 🆕 دریافت وضعیت‌های روزانه (مأموریت و استراحت)
    daily_statuses = db.query(DailyStatus).filter(
        and_(
            DailyStatus.user_id == user.user_id,
            DailyStatus.status_date >= month_start_g,
            DailyStatus.status_date <= month_end_g,
        )
    ).all()
    rest_dates = {ds.status_date for ds in daily_statuses if ds.status_code == 'R'}
    mission_dates = {ds.status_date for ds in daily_statuses if ds.status_code == 'M'}

    # گروه‌بندی بر اساس روز
    days_dict = {}
    for record in records:
        day = record.timestamp.date()
        if day not in days_dict:
            days_dict[day] = []
        days_dict[day].append(record)

    # ساخت لیست روزها
    days_list = []
    current = month_start_g
    while current <= month_end_g:
        j_day = jdatetime.date.fromgregorian(date=current)
        day_records = days_dict.get(current, [])
        prev_day_records = days_dict.get(current - timedelta(days=1), [])
        next_day_records = days_dict.get(current + timedelta(days=1), [])

        is_friday = current.weekday() == 4
        holiday_title = holiday_dates.get(current)

        # تحلیل وضعیت + کارکرد از موتور مرکزی (Phase 3)
        day_result = compute_day_attendance(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title
        )
        status_info = day_result.attendance_status_dict
        # 🆕 بررسی مرخصی تایید شده
        # ⚠️ فقط اگر روز تعطیل یا جمعه نباشد (تعطیلات اولویت دارند)
        # (در لایه route می‌ماند — سیاست/موظفی از Policy است)
        leave_type = leaves_by_date.get(current)
        if leave_type and not is_friday and holiday_title is None:
            type_name = LEAVE_TYPE_NAMES_LOCAL.get(leave_type, '')
            status_info['main_status'] = STATUS_LEAVE
            status_info['main_label'] = f'🌴 مرخصی {type_name}'
            status_info['main_color'] = 'info'

        # 🆕 محاسبه کارکرد با در نظر گرفتن شیفت شب
        is_night_shift = status_info['main_status'] == STATUS_NIGHT_SHIFT
        if is_night_shift == day_result.is_night_shift:
            # وضعیت دست‌نخورده → نتیجه آماده موتور مرکزی
            work_hours = day_result.work_hours
            first_enter = day_result.first_enter
            last_exit = day_result.last_exit
        else:
            # اورراید مرخصی شب/غیرشب را عوض کرده → محاسبه مجدد (رفتار قبلی)
            work_hours, first_enter, last_exit = calculate_work_hours(
                day_records,
                is_night_shift=is_night_shift
            )

        resolved = resolve_policy(db, emp, current)
        late_early = compute_late_early_for_day(
            resolved=resolved,
            target_date=current,
            first_enter=first_enter,
            last_exit=last_exit,
            skip=(
                status_info['main_status'] == STATUS_LEAVE
                or current in rest_dates
            ),
            hl_intervals=hl_intervals_by_date.get(current),
        )

        days_list.append({
            'date': current,
            'jalali_date': j_day.strftime('%Y/%m/%d'),
            'day_name': DAY_NAMES_FA.get(current.weekday(), ''),
            'records': day_records,
            'first_enter': first_enter,
            'last_exit': last_exit,
            'work_hours': work_hours,
            'work_hours_display': format_hours_hhmm(work_hours),  # ✅ این خط اضافه شد
            'is_friday': is_friday,
            'is_holiday': holiday_title is not None,
            'holiday_title': holiday_title,
             'status': status_info,
             'is_night_shift': status_info['main_status'] == STATUS_NIGHT_SHIFT,
             'is_mission': current in mission_dates,
             'is_rest': current in rest_dates,
            # 🕐 HL تایید شده برای نمایش (بدون تاثیر روی وضعیت اصلی/محاسبات)
            'hourly_leave_minutes': hourly_leave_minutes_by_date.get(current, 0),
            'hourly_leave_display': format_hl_display(hourly_leave_minutes_by_date.get(current, 0)),
            # 🚗 HM تأییدشده برای نمایش (بدون تاثیر روی وضعیت اصلی/محاسبات)
            'hourly_mission_display': format_hm_display(hourly_missions_by_date.get(current)),
            # تأخیر / تعجیل
            'late_minutes': late_early['late_minutes'],
            'late_violation_minutes': late_early['late_violation_minutes'],
            'is_late': late_early['is_late'],
            'early_leave_minutes': late_early['early_leave_minutes'],
            'early_leave_violation_minutes': late_early['early_leave_violation_minutes'],
            'is_early_leave': late_early['is_early_leave'],
        })
        current += timedelta(days=1)
    # کارکرد کل ماه — قبل از فیلتر وضعیت (کارت‌های خلاصه همیشه روی ماه کامل‌اند)
    total_work_hours_month = sum(d['work_hours'] for d in days_list)
    summary_days = days_list

    # فیلتر وضعیت فقط جدول را محدود می‌کند؛ روی کارت‌های خلاصه اثر ندارد
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
    elif status_filter == 'leave':  # 🆕
        days_list = [d for d in days_list if d['status']['main_status'] == STATUS_LEAVE]
    # 'all' یا None → بدون فیلتر

    # ---------- ۱. موظفی ماهانه ----------
    work_days_in_month = 0  # روزهای کاری (غیر تعطیل و غیر جمعه)
    leave_days_in_month = 0  # روزهای مرخصی در روز کاری
    rest_days_in_month = 0  # روزهای استراحت در روز کاری
    mission_days_in_month = 0  # روزهای مأموریت در روز کاری

    current = month_start_g
    while current <= month_end_g:
        is_friday = current.weekday() == 4
        is_holiday = current in holiday_dates
        is_day_off = is_friday or is_holiday

        if not is_day_off:
            work_days_in_month += 1
            if current in leaves_by_date:
                leave_days_in_month += 1
            elif current in rest_dates:
                rest_days_in_month += 1
            elif current in mission_dates:
                mission_days_in_month += 1
        current += timedelta(days=1)

    # محاسبه موظفی ماهانه بر اساس Policy (نه ضرب ساده)
    monthly_required_minutes = compute_required_minutes_for_range(
        db=db, employee=emp,
        start_date=month_start_g, end_date=month_end_g,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
        mission_dates=mission_dates,
        hourly_mission_minutes_by_date=hourly_mission_minutes_by_date,
    )
    monthly_duty_hours = monthly_required_minutes / 60

    # روزهای موظفی = روزهای کاری - مرخصی - استراحت - مأموریت
    duty_days_month = work_days_in_month - leave_days_in_month - rest_days_in_month - mission_days_in_month

    # ---------- ۲. موظفی لحظه‌ای ----------
    today_g = today_j.togregorian()

    # تعیین تاریخ مرجع (امروز یا دیروز) — از لیست کامل ماه، نه جدول فیلترشده
    if today_g < month_start_g:
        # ماه آینده: هیچ روزی سپری نشده
        reference_date = month_start_g - timedelta(days=1)
    elif today_g > month_end_g:
        # ماه گذشته: همه روزها سپری شده
        reference_date = month_end_g
    else:
        # ماه جاری: بررسی تردد کامل امروز
        is_today_complete = False
        for day in summary_days:
            if day['date'] == today_g:
                main_status = day['status']['main_status']
                # اگر وضعیت مشخصی دارد (کامل، مرخصی، تعطیل، استراحت)
                if main_status in [STATUS_COMPLETE, STATUS_LEAVE] or day['is_holiday'] or day['is_friday']:
                    is_today_complete = True
                break
        reference_date = today_g if is_today_complete else today_g - timedelta(days=1)

    # محاسبه موظفی و کارکرد تا تاریخ مرجع (همیشه روی ماه کامل)
    duty_days_until_ref = 0
    work_hours_until_ref = 0.0

    for day in summary_days:
        if day['date'] <= reference_date:
            is_day_off = day['is_friday'] or day['is_holiday']
            is_leave = day['status']['main_status'] == STATUS_LEAVE
            is_rest = day['date'] in rest_dates
            is_mission = day['date'] in mission_dates

            if not is_day_off and not is_leave and not is_rest and not is_mission:
                duty_days_until_ref += 1

            work_hours_until_ref += day['work_hours']

    # محاسبه موظفی لحظه‌ای بر اساس Policy (جمع دقایق روزهای سپری‌شده)
    instant_required_minutes = compute_required_minutes_for_range(
        db=db, employee=emp,
        start_date=month_start_g, end_date=reference_date,
        rest_dates=rest_dates, holiday_dates=holiday_dates,
        leaves_by_date=leaves_by_date,
        hourly_leave_minutes_by_date=hourly_leave_minutes_by_date,
        mission_dates=mission_dates,
        hourly_mission_minutes_by_date=hourly_mission_minutes_by_date,
    )
    instant_duty_hours = instant_required_minutes / 60

    # ---------- ۳ و ۴. اضافه/کسر کار ----------
    # total_work_hours_month از قبل از فیلتر وضعیت حفظ شده است
    progress_percent = 0
    if monthly_duty_hours > 0:
        progress_percent = min(100, round((total_work_hours_month / monthly_duty_hours) * 100, 1))

    # تخلف تأخیر/تعجیل (بعد از Grace) از بالانس کم می‌شود
    month_late_early_m = sum(
        int(d.get('late_violation_minutes') or 0)
        + int(d.get('early_leave_violation_minutes') or 0)
        for d in summary_days
    )
    instant_late_early_m = sum(
        int(d.get('late_violation_minutes') or 0)
        + int(d.get('early_leave_violation_minutes') or 0)
        for d in summary_days
        if d['date'] <= reference_date
    )
    month_late_early_h = month_late_early_m / 60.0
    instant_late_early_h = instant_late_early_m / 60.0

    # اضافه/کسر کار ماهانه
    monthly_balance = total_work_hours_month - monthly_duty_hours - month_late_early_h

    # اضافه/کسر کار لحظه‌ای
    instant_balance = work_hours_until_ref - instant_duty_hours - instant_late_early_h

    # تاریخ مرجع به شمسی برای نمایش
    reference_date_j = jdatetime.date.fromgregorian(date=reference_date)
    reference_date_display = reference_date_j.strftime('%Y/%m/%d')

    # آمار
    total_records = sum(len(d['records']) for d in days_list)
    # جمع کارکرد فقط روزهای جدول (بعد از فیلتر وضعیت) — جدا از کارت‌های ماه
    displayed_work_hours = sum(d['work_hours'] for d in days_list)
    # 🆕 محاسبه ماه قبل و بعد
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # 🆕 لیست سال‌های قابل انتخاب (6 سال اخیر)
    today_j = jdatetime.date.today()
    available_years = list(range(today_j.year, today_j.year - 6, -1))

    # 🆕 لیست ماه‌ها
    months_list = [
        {'num': 1, 'name': 'فروردین'}, {'num': 2, 'name': 'اردیبهشت'},
        {'num': 3, 'name': 'خرداد'}, {'num': 4, 'name': 'تیر'},
        {'num': 5, 'name': 'مرداد'}, {'num': 6, 'name': 'شهریور'},
        {'num': 7, 'name': 'مهر'}, {'num': 8, 'name': 'آبان'},
        {'num': 9, 'name': 'آذر'}, {'num': 10, 'name': 'دی'},
        {'num': 11, 'name': 'بهمن'}, {'num': 12, 'name': 'اسفند'},
    ]

    # بررسی آیا ماه جاری است
    is_current_month = (year == today_j.year and month == today_j.month)

    return templates.TemplateResponse(request, "attendance.html", {
        "user": user,
        "year": year,
        "month": month,
        "month_name": MONTH_NAMES.get(month, ""),
        "days": days_list,
        "total_records": total_records,
        "is_admin": user.is_admin,
        "status_filter": status_filter or 'all',
        # 🆕 متغیرهای ناوبری
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "available_years": available_years,
        "months_list": months_list,
        "is_current_month": is_current_month,
        "today_j": today_j,
        # 🆕 موظفی و اضافه/کسر کار
        "monthly_duty_display": format_hours_hhmm(monthly_duty_hours),
        "duty_days_month": duty_days_month,
        "mission_days_month": mission_days_in_month,
        "rest_days_month": rest_days_in_month,
        "leave_days_month": leave_days_in_month,
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
        "total_work_hours_display": format_hours_hhmm(total_work_hours_month),  # 🆕
        "progress_percent": progress_percent,
        "displayed_work_hours": displayed_work_hours,
        "displayed_work_hours_display": format_hours_hhmm(displayed_work_hours),

    })