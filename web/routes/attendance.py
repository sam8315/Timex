"""صفحه رکوردهای تردد با تحلیل وضعیت"""
from datetime import timedelta, date as date_type
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import jdatetime
from typing import Optional, List, Dict

from web.dependencies import get_db, check_password_change
from models.user import User
from models.attendance import Attendance
from models.holiday import Holiday

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

# وضعیت‌های اصلی
STATUS_COMPLETE = 'complete'
STATUS_NIGHT_SHIFT = 'night_shift'
STATUS_MISSING_EXIT = 'missing_exit'
STATUS_MISSING_ENTER = 'missing_enter'
STATUS_SEQUENCE_ERROR = 'sequence_error'
STATUS_IMBALANCE = 'imbalance'
STATUS_NO_ATTENDANCE = 'no_attendance'
STATUS_LEAVE = 'leave'

# هشدارهای ترکیبی
WARN_ABNORMAL_GAP = 'abnormal_gap'
WARN_DUPLICATE = 'duplicate'
WARN_ABNORMAL_TIME = 'abnormal_time'
WARN_TOO_MANY = 'too_many'
WARN_FRIDAY_WORK = 'friday_work'
WARN_HOLIDAY_WORK = 'holiday_work'


def analyze_day_status(
    day: date_type,
    day_records: List[Attendance],
    prev_day_records: List[Attendance],
    next_day_records: List[Attendance],
    is_friday: bool,
    holiday_title: Optional[str]
) -> Dict:
    """تحلیل وضعیت تردد یک روز"""
    warnings = []

    # بدون تردد
    if not day_records:
        return {
            'main_status': STATUS_NO_ATTENDANCE,
            'main_label': '⚪ بدون تردد',
            'main_color': 'secondary',
            'warnings': [],
            'is_friday': is_friday,
            'is_holiday': holiday_title is not None,
            'holiday_title': holiday_title,
        }

    enters = sorted([r for r in day_records if r.punch == 0], key=lambda x: x.timestamp)
    exits = sorted([r for r in day_records if r.punch == 1], key=lambda x: x.timestamp)

    # 🆕 بررسی شیفت شب با منطق ساده‌تر و قوی‌تر
    has_night_shift = False

    # حالت ۰: خروج قبل از ورود در همان روز → شیفت شب ادغام‌شده
    if enters and exits:
        first_enter = min(enters, key=lambda x: x.timestamp)
        first_exit = min(exits, key=lambda x: x.timestamp)
        if first_exit.timestamp < first_enter.timestamp:
            # خروج صبح قبل از ورود شب → شیفت شب
            has_night_shift = True

    # حالت ۱: ورود بدون خروج → بررسی هر خروجی در فردا
    if len(enters) > len(exits) and not has_night_shift:
        if next_day_records:
            next_exits = [r for r in next_day_records if r.punch == 1]
            if next_exits:
                has_night_shift = True

    # حالت ۲: خروج بدون ورود → بررسی هر ورودی در دیروز
    if len(exits) > len(enters) and not has_night_shift:
        if prev_day_records:
            prev_enters = [r for r in prev_day_records if r.punch == 0]
            if prev_enters:
                has_night_shift = True

# 🆕 بررسی خطای ترتیب (بهبودیافته)
    has_sequence_error = False
    sequence_error_detail = ""

    if day_records:
        # مرتب‌سازی بر اساس زمان
        sorted_records = sorted(day_records, key=lambda x: x.timestamp)

        # بررسی 1: آیا ورود و خروج به صورت متناوب هستند؟
        expected_punch = 0  # باید با ورود شروع شود
        for rec in sorted_records:
            if rec.punch != expected_punch:
                has_sequence_error = True
                if rec.punch == 0 and expected_punch == 1:
                    sequence_error_detail = "ورود بدون خروج قبلی"
                elif rec.punch == 1 and expected_punch == 0:
                    sequence_error_detail = "خروج بدون ورود قبلی"
                break
            expected_punch = 1 - expected_punch  # تغییر بین 0 و 1

        # بررسی 2: آیا اولین رکورد خروج است؟
        if not has_sequence_error and sorted_records[0].punch == 1:
            # بررسی آیا دیروز ورود داشته (شیفت شب)
            prev_enters = [r for r in prev_day_records if r.punch == 0]
            if not prev_enters:
                has_sequence_error = True
                sequence_error_detail = "خروج بدون ورود"

    # 🆕 تعیین وضعیت اصلی - شیفت شب اولویت بالاتری دارد
    if has_night_shift:
        # شیفت شب تشخیص داده شد - خطای ترتیب نادیده گرفته شود
        main_status = STATUS_NIGHT_SHIFT
        main_label = '🌙 شیفت شب'
        main_color = 'info'
    elif has_sequence_error:
        main_status = STATUS_SEQUENCE_ERROR
        main_label = f'❌ {sequence_error_detail}' if sequence_error_detail else '❌ خطای ترتیب'
        main_color = 'danger'
    elif len(enters) == len(exits) and len(enters) > 0:
        main_status = STATUS_COMPLETE
        main_label = '✅ کامل'
        main_color = 'success'
    elif len(enters) > len(exits):
        main_status = STATUS_MISSING_EXIT
        main_label = '⬅️ ورود بدون خروج'
        main_color = 'warning'
    elif len(exits) > len(enters):
        main_status = STATUS_MISSING_ENTER
        main_label = '➡️ خروج بدون ورود'
        main_color = 'warning'
    else:
        main_status = STATUS_IMBALANCE
        main_label = '⚠️ عدم تعادل'
        main_color = 'warning'

    # ============================================
    # 🆕 هشدارهای ترکیبی - با در نظر گرفتن ورود/خروج ضمنی
    # ============================================

    # ساخت لیست‌های موثر (با ضمنی‌ها در صورت شیفت شب)
    effective_enters = enters.copy()
    effective_exits = exits.copy()

    # 🆕 تابع کمکی برای ساخت MockRecord با timezone
    def create_mock_record(timestamp_naive, punch):
        """ساخت رکورد موقت با timezone مشابه رکوردهای واقعی"""
        # اگر رکوردهای واقعی داریم، timezone آن‌ها را استفاده کن
        if enters:
            tz = enters[0].timestamp.tzinfo
            timestamp_aware = timestamp_naive.replace(tzinfo=tz)
        elif exits:
            tz = exits[0].timestamp.tzinfo
            timestamp_aware = timestamp_naive.replace(tzinfo=tz)
        else:
            # اگر هیچ رکورد واقعی نداریم، naive نگه دار
            timestamp_aware = timestamp_naive

        return type('MockRecord', (), {'timestamp': timestamp_aware, 'punch': punch})()

    if has_night_shift:
        # ورود بدون خروج → خروج ضمنی 23:59:59
        if len(enters) > len(exits) and enters:
            last_enter = max(enters, key=lambda x: x.timestamp)
            day = last_enter.timestamp.date()
            implicit_exit_ts = datetime(day.year, day.month, day.day, 23, 59, 59)
            implicit_exit = create_mock_record(implicit_exit_ts, 1)
            effective_exits.append(implicit_exit)

        # خروج بدون ورود → ورود ضمنی 00:00:00
        elif len(exits) > len(enters) and exits:
            first_exit = min(exits, key=lambda x: x.timestamp)
            day = first_exit.timestamp.date()
            implicit_enter_ts = datetime(day.year, day.month, day.day, 0, 0, 0)
            implicit_enter = create_mock_record(implicit_enter_ts, 0)
            effective_enters.append(implicit_enter)

    # 🆕 1. فاصله غیرعادی - بررسی هر جفت ورود-خروج (با ضمنی‌ها)
    if effective_enters and effective_exits:
        enters_sorted = sorted(effective_enters, key=lambda x: x.timestamp)
        exits_sorted = sorted(effective_exits, key=lambda x: x.timestamp)

        # جفت‌سازی: هر ورود با اولین خروج بعد از خودش
        pairs = []
        exit_idx = 0
        for enter_rec in enters_sorted:
            # پیدا کردن اولین خروج که بعد از این ورود باشد
            while exit_idx < len(exits_sorted) and exits_sorted[exit_idx].timestamp < enter_rec.timestamp:
                exit_idx += 1

            if exit_idx < len(exits_sorted):
                exit_rec = exits_sorted[exit_idx]
                gap_hours = (exit_rec.timestamp - enter_rec.timestamp).total_seconds() / 3600
                pairs.append({
                    'enter': enter_rec,
                    'exit': exit_rec,
                    'gap_hours': gap_hours
                })
                exit_idx += 1

        # بررسی جفت‌های غیرعادی (بیش از 12 ساعت برای یک جفت)
        MAX_PAIR_HOURS = 12
        abnormal_pairs = [p for p in pairs if p['gap_hours'] > MAX_PAIR_HOURS]

        if abnormal_pairs:
            max_gap = max(p['gap_hours'] for p in abnormal_pairs)
            worst_pair = max(abnormal_pairs, key=lambda x: x['gap_hours'])
            enter_time = worst_pair['enter'].timestamp.strftime('%H:%M')
            exit_time = worst_pair['exit'].timestamp.strftime('%H:%M')
            warnings.append({
                'code': WARN_ABNORMAL_GAP,
                'label': f'⏱️ فاصله {max_gap:.1f}h ({enter_time}-{exit_time})',
                'color': 'warning'
            })

    # 🆕 2. تردد تکراری (<2 دقیقه فاصله) - فقط رکوردهای واقعی
    all_sorted = sorted(day_records, key=lambda x: x.timestamp)
    for i in range(1, len(all_sorted)):
        gap = (all_sorted[i].timestamp - all_sorted[i - 1].timestamp).total_seconds()
        if gap < 120:  # 2 دقیقه
            warnings.append({
                'code': WARN_DUPLICATE,
                'label': '🔁 تردد تکراری',
                'color': 'warning'
            })
            break

    # 🆕 3. ساعت غیرعادی - فقط رکوردهای واقعی
    for e in enters:
        if e.timestamp.hour >= 22:
            warnings.append({
                'code': WARN_ABNORMAL_TIME,
                'label': '🕐 ورود دیروقت',
                'color': 'warning'
            })
            break
    for e in exits:
        if e.timestamp.hour < 5:
            warnings.append({
                'code': WARN_ABNORMAL_TIME,
                'label': '🕐 خروج زودهنگام',
                'color': 'warning'
            })
            break

    # 🆕 4. تعداد تردد بیش از حد (>6)
    if len(day_records) > 6:
        warnings.append({
            'code': WARN_TOO_MANY,
            'label': f'🔢 {len(day_records)} تردد',
            'color': 'warning'
        })

    # 🆕 5. تردد در جمعه
    if is_friday and day_records:
        warnings.append({
            'code': WARN_FRIDAY_WORK,
            'label': '🟡 جمعه‌کاری',
            'color': 'info'
        })

    # 🆕 6. تردد در تعطیل رسمی
    if holiday_title and day_records:
        warnings.append({
            'code': WARN_HOLIDAY_WORK,
            'label': f'🔴 تعطیل‌کاری ({holiday_title})',
            'color': 'danger'
        })

    return {
        'main_status': main_status,
        'main_label': main_label,
        'main_color': main_color,
        'warnings': warnings,
        'is_friday': is_friday,
        'is_holiday': holiday_title is not None,
        'holiday_title': holiday_title,
    }


from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def calculate_work_hours(
    day_records: list,
    is_night_shift: bool
) -> tuple:
    """
    محاسبه ساعات کاری با در نظر گرفتن شیفت شب
    - اگر ورود بدون خروج و شیفت شب → خروج ضمنی 23:59:59
    - اگر خروج بدون ورود و شیفت شب → ورود ضمنی 00:00:00
    - اگر خروج قبل از ورود در همان روز → شیفت شب ادغام‌شده
    """
    from datetime import datetime
    import logging
    logger = logging.getLogger(__name__)

    enters = [r for r in day_records if r.punch == 0]
    exits = [r for r in day_records if r.punch == 1]

    if not enters and not exits:
        return 0, None, None

    effective_enter = None
    effective_exit = None

    if enters:
        effective_enter = min(enters, key=lambda x: x.timestamp).timestamp
        if effective_enter.tzinfo is not None:
            effective_enter = effective_enter.replace(tzinfo=None)

    if exits:
        effective_exit = max(exits, key=lambda x: x.timestamp).timestamp
        if effective_exit.tzinfo is not None:
            effective_exit = effective_exit.replace(tzinfo=None)

    # 🆕 حالت ویژه: خروج قبل از ورود در همان روز (شیفت شب ادغام‌شده)
    # مثل: ورود 20:56 + خروج 06:57 در یک روز
    if effective_enter and effective_exit and effective_exit < effective_enter:
        logger.info(f"🌙 Night shift merged: exit {effective_exit} before enter {effective_enter}")
        # محاسبه دو بخش:
        # بخش 1: 00:00 تا خروج صبح
        # بخش 2: ورود شب تا 23:59
        day = effective_enter.date()
        midnight = datetime(day.year, day.month, day.day, 0, 0, 0)
        end_of_day = datetime(day.year, day.month, day.day, 23, 59, 59)

        hours_morning = (effective_exit - midnight).total_seconds() / 3600
        hours_night = (end_of_day - effective_enter).total_seconds() / 3600
        total_hours = max(0, hours_morning) + max(0, hours_night)

        # برای نمایش، از اولین ورود تا آخرین خروج استفاده کن
        return total_hours, effective_enter, effective_exit

    # 🆕 خروج ضمنی 23:59:59
    if is_night_shift and effective_enter and not effective_exit:
        day = effective_enter.date()
        effective_exit = datetime(day.year, day.month, day.day, 23, 59, 59)
        logger.info(f"🌙 Night shift: Implicit exit set to {effective_exit}")

    # 🆕 ورود ضمنی 00:00:00
    if is_night_shift and effective_exit and not effective_enter:
        day = effective_exit.date()
        effective_enter = datetime(day.year, day.month, day.day, 0, 0, 0)
        logger.info(f"🌙 Night shift: Implicit enter set to {effective_enter}")

    if effective_enter and effective_exit:
        try:
            diff = (effective_exit - effective_enter).total_seconds() / 3600
            work_hours = max(0, diff)
            logger.info(f"✅ Work hours calculated: {work_hours:.2f} hours")
            return work_hours, effective_enter, effective_exit
        except Exception as e:
            logger.error(f"❌ Error calculating diff: {e}")
            return 0, effective_enter, effective_exit

    return 0, effective_enter, effective_exit

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

        # تحلیل وضعیت
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
            'is_night_shift': status_info['main_status'] == STATUS_NIGHT_SHIFT,
        })
        current += timedelta(days=1)

    # 🆕 اعمال فیلتر
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
    # 'all' یا None → بدون فیلتر

    # آمار
    total_records = sum(len(d['records']) for d in days_list)
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
    })