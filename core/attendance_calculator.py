"""
ماژول مرکزی محاسبه تردد (Central Attendance Calculation Engine)

منبع واحد حقیقت (ONE SOURCE OF TRUTH) برای محاسبه «تردد واقعی» (Actual Attendance):

    status / night shift / sequence error / warnings
    work hours / first enter / last exit / entry-exit pairs

این ماژول از `web/routes/attendance.py` استخراج (Extract) شده و رفتار محاسباتی
آن‌ها عیناً حفظ شده است. هیچ آستانه (threshold)، قانون یا اولویت جدیدی اضافه نشده.

مرز معماری — این ماژول مسئول «کار واقعی انجام‌شده» است و مسئول نیست:

    ┌──────────────────────────────────────────────────────────────┐
    │ Central Attendance Engine (این ماژول)                       │
    │   → punch analysis / status / night shift / warnings /      │
    │     entry-exit pairing / work hours / first enter / last exit│
    ├──────────────────────────────────────────────────────────────┤
    │ Policy / Schedule Engine (web/services/attendance_policy_*)  │
    │   → required duty / leave / mission / rest / holiday /       │
    │     effective required minutes / برنامه کاری فرد یا گروه    │
    ├──────────────────────────────────────────────────────────────┤
    │ Report Layer                                                 │
    │   → surplus / deficit / weekly overtime / monthly summary    │
    └──────────────────────────────────────────────────────────────┘

هیچ ساعت کارکرد ثابتی (مثلاً ۷:۲۰) در این ماژول hard-code نشده است.
اگر لازم شد موتور اطلاعات برنامه کاری فرد/گروه را بداند، آن را از بیرون
(مثلاً از Policy Engine) به صورت `WorkScheduleContext` دریافت می‌کند؛
ولی محاسبه actual attendance صرفاً از punchها انجام می‌شود.

وابستگی: فقط standard library → هیچ وابستگی به FastAPI / Template / Route ندارد.
"""
from dataclasses import dataclass, field
from datetime import datetime, date as date_type
from typing import Dict, List, Mapping, Optional, Any

# ============================================
# وضعیت‌های اصلی
# ============================================
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

# کلیدهای خروجی analyze_day_status (برای حفظ رفتار قدیمی)
_STATUS_RESULT_KEYS = (
    'main_status',
    'main_label',
    'main_color',
    'warnings',
    'is_friday',
    'is_holiday',
    'holiday_title',
)


def analyze_day_status(
    day: date_type,
    day_records: List,
    prev_day_records: List,
    next_day_records: List,
    is_friday: bool,
    holiday_title: Optional[str]
) -> Dict:
    """تحلیل وضعیت تردد یک روز"""
    full = _analyze_day_status(
        day=day,
        day_records=day_records,
        prev_day_records=prev_day_records,
        next_day_records=next_day_records,
        is_friday=is_friday,
        holiday_title=holiday_title,
    )
    # خروجی عمومی: دقیقاً همان کلیدهای قبلی (بدون تغییر رفتار مصرف‌کننده‌ها)
    return {key: full[key] for key in _STATUS_RESULT_KEYS}


def _analyze_day_status(
    day: date_type,
    day_records: List,
    prev_day_records: List,
    next_day_records: List,
    is_friday: bool,
    holiday_title: Optional[str]
) -> Dict:
    """تحلیل کامل وضعیت تردد (شامل اطلاعات anomaly برای DayAttendanceResult)"""
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
            'has_sequence_error': False,
            'sequence_error_detail': '',
        }

    enters = sorted([r for r in day_records if r.punch == 0], key=lambda x: x.timestamp)
    exits = sorted([r for r in day_records if r.punch == 1], key=lambda x: x.timestamp)

    # 🆕 بررسی شیفت شب با منطق دقیق‌تر
    has_night_shift = False

    # حالت ۰: خروج قبل از ورود در همان روز → شیفت شب ادغام‌شده
    if enters and exits:
        first_enter = min(enters, key=lambda x: x.timestamp)
        first_exit = min(exits, key=lambda x: x.timestamp)
        if first_exit.timestamp < first_enter.timestamp:
            # خروج صبح قبل از ورود شب → شیفت شب
            has_night_shift = True

    # 🆕 حالت ۱: ورود بدون خروج → بررسی اولین رکورد فردا
    if len(enters) > len(exits) and not has_night_shift:
        if next_day_records:
            # مرتب‌سازی بر اساس زمان
            next_sorted = sorted(next_day_records, key=lambda x: x.timestamp)
            first_next_record = next_sorted[0]

            # ✅ اولین رکورد فردا باید خروجی باشد
            if first_next_record.punch == 1:
                has_night_shift = True

    # 🆕 حالت ۲: خروج بدون ورود → بررسی آخرین رکورد دیروز
    if len(exits) > len(enters) and not has_night_shift:
        if prev_day_records:
            # مرتب‌سازی بر اساس زمان
            prev_sorted = sorted(prev_day_records, key=lambda x: x.timestamp)
            last_prev_record = prev_sorted[-1]

            # ✅ آخرین رکورد دیروز باید ورودی باشد
            if last_prev_record.punch == 0:
                has_night_shift = True


# ============================================
# 🆕 بررسی خطای ترتیب (تفکیک‌شده از ناقص)
# ============================================
    has_sequence_error = False
    sequence_error_detail = ""

    if day_records:
        sorted_records = sorted(day_records, key=lambda x: x.timestamp)

        # 🆕 بررسی ۱: دو رکورد هم‌نوع پشت سر هم = خطای ترتیب واقعی
        # مثال: (ورود، ورود) یا (خروج، خروج)
        for i in range(1, len(sorted_records)):
            if sorted_records[i].punch == sorted_records[i - 1].punch:
                has_sequence_error = True
                if sorted_records[i].punch == 0:
                    sequence_error_detail = "دو ورود پشت سر هم"
                else:
                    sequence_error_detail = "دو خروج پشت سر هم"
                break

        # 🆕 بررسی ۲: اولین رکورد خروج است (و شیفت شب نیست)
        # فقط اگر بیش از یک رکورد داشته باشیم، خطای ترتیب است
        # اگر فقط یک خروج تنها باشد → missing_enter است (نه خطای ترتیب)
        if not has_sequence_error and not has_night_shift:
            if sorted_records[0].punch == 1 and len(sorted_records) > 1:
                has_sequence_error = True
                sequence_error_detail = "خروج بدون ورود قبلی"

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
        'has_sequence_error': has_sequence_error,
        'sequence_error_detail': sequence_error_detail,
    }


def calculate_work_hours(
    day_records: list,
    is_night_shift: bool
) -> tuple:
    """
    🆕 محاسبه دقیق ساعات کاری با جمع زدن بازه‌های ورود و خروج
    - اگر بیش از ۲ تردد باشد، بازه هر جفت (ورود تا خروج) محاسبه و جمع می‌شود
    - ترددهای تکراری (دو ورود یا دو خروج پشت سر هم) نادیده گرفته می‌شوند
    - شیفت شب (ورود/خروج ضمنی) به درستی مدیریت می‌شود
    """
    work_hours, first_enter, last_exit, _pairs = _calculate_work_hours_detailed(
        day_records, is_night_shift
    )
    return work_hours, first_enter, last_exit


def _get_naive_ts(rec):
    """حذف timezone برای مرتب‌سازی/محاسبه (رفتار قبلی)"""
    return rec.timestamp.replace(tzinfo=None) if rec.timestamp.tzinfo else rec.timestamp


def _calculate_work_hours_detailed(
    day_records: list,
    is_night_shift: bool
) -> tuple:
    """
    همان state machine تابع calculate_work_hours، با ثبت pairهای واقعیِ همان بازه‌ها.

    ⚠️ الگوریتم محاسبه ساعت کارکرد تغییر نکرده است؛ صرفاً همان جفت‌هایی که
    در حین محاسبه باز می‌شوند/بسته می‌شوند در خروجی نگه داشته می‌شوند تا
    sum(pair['hours']) == work_hours همیشه برقرار باشد.

    خروجی: (work_hours, first_enter, last_exit, pairs)
    """
    if not day_records:
        return 0, None, None, []

    sorted_records = sorted(day_records, key=_get_naive_ts)

    total_seconds = 0
    open_enter = None
    pairs = []

    for rec in sorted_records:
        ts = _get_naive_ts(rec)

        if rec.punch == 0:  # ورود
            if open_enter is None:
                open_enter = ts
            # اگر open_enter از قبل ست شده باشد (دو ورود پشت سر هم)، ورود دوم نادیده گرفته می‌شود

        elif rec.punch == 1:  # خروج
            if open_enter is not None:
                # بستن بازه کاری
                diff = (ts - open_enter).total_seconds()
                if diff > 0:
                    total_seconds += diff
                    pairs.append({
                        'enter': open_enter,
                        'exit': ts,
                        'hours': diff / 3600.0,
                    })
                open_enter = None
            else:
                # خروج بدون ورود قبلی در همین روز
                if is_night_shift:
                    # این خروجِ صبحِ شیفت شب است → ورود ضمنی 00:00:00
                    day = ts.date()
                    implicit_enter = datetime(day.year, day.month, day.day, 0, 0, 0)
                    diff = (ts - implicit_enter).total_seconds()
                    if diff > 0:
                        total_seconds += diff
                        pairs.append({
                            'enter': implicit_enter,
                            'exit': ts,
                            'hours': diff / 3600.0,
                        })
                    # دیگر open_enter ست نمی‌شود تا ورودهای بعدی عادی پردازش شوند

    # اگر در پایان روز، ورودی بدون خروج مانده باشد
    if open_enter is not None:
        if is_night_shift:
            # شیفت شب → خروج ضمنی 23:59:59
            day = open_enter.date()
            implicit_exit = datetime(day.year, day.month, day.day, 23, 59, 59)
            diff = (implicit_exit - open_enter).total_seconds()
            if diff > 0:
                total_seconds += diff
                pairs.append({
                    'enter': open_enter,
                    'exit': implicit_exit,
                    'hours': diff / 3600.0,
                })
        else:
            # روز عادی و خروج فراموش شده → این بازه ناقص است و محاسبه نمی‌شود
            pass

    work_hours = total_seconds / 3600.0

    # تعیین اولین ورود و آخرین خروج برای نمایش در جدول
    enters = [r for r in day_records if r.punch == 0]
    exits = [r for r in day_records if r.punch == 1]

    first_enter = min(enters, key=_get_naive_ts).timestamp if enters else None
    last_exit = max(exits, key=_get_naive_ts).timestamp if exits else None

    if first_enter and first_enter.tzinfo:
        first_enter = first_enter.replace(tzinfo=None)
    if last_exit and last_exit.tzinfo:
        last_exit = last_exit.replace(tzinfo=None)

    # تنظیم زمان‌های ضمنی برای نمایش در شیفت شب
    if is_night_shift:
        if first_enter and not last_exit:
            day = first_enter.date()
            last_exit = datetime(day.year, day.month, day.day, 23, 59, 59)
        elif last_exit and not first_enter:
            day = last_exit.date()
            first_enter = datetime(day.year, day.month, day.day, 0, 0, 0)

    return work_hours, first_enter, last_exit, pairs


# ============================================
# Context برنامه کاری (از بیرون — Policy Engine)
# ============================================

@dataclass(frozen=True)
class WorkScheduleContext:
    """
    context مربوط به برنامه/مبنای ساعت کارکرد مؤثر فرد یا گروه.

    این ساختار صرفاً «اطلاعات» است: موتور مرکزی آن را دریافت و در خروجی
    نگه می‌دارد، اما هیچ‌وقت از آن برای محاسبه punch/actual work استفاده نمی‌کند
    تا Central Engine به هیچ ساعت ثابتی (مثل ۷:۲۰) قفل نشود.

    نمونه منبع اطلاعات در پروژه:
        web/services/attendance_policy_service.py
            resolve_policy / resolve_scheduled_times /
            compute_effective_required_minutes_for_day

    مصرف‌کننده‌ها (در Phaseهای بعد) می‌توانند این context را از Policy Engine
    بسازند و به موتور مرکزی بدهند.
    """
    effective_work_minutes: Optional[int] = None
    schedule_code: Optional[str] = None
    scheduled_start: Optional[Any] = None
    scheduled_end: Optional[Any] = None
    source: Optional[str] = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class DayAttendanceResult:
    """خروجی استاندارد موتور مرکزی برای یک روز"""
    day: Optional[date_type]
    # status
    main_status: str
    main_label: str
    main_color: str
    is_night_shift: bool
    # anomaly / sequence
    has_sequence_error: bool
    sequence_error_detail: str
    # warnings
    warnings: List[Dict]
    # flags
    is_friday: bool
    is_holiday: bool
    holiday_title: Optional[str]
    # actual work
    work_hours: float
    first_enter: Optional[datetime]
    last_exit: Optional[datetime]
    pairs: List[Dict]
    # counts
    enter_count: int
    exit_count: int
    # optional context (بدون اثر روی محاسبه)
    schedule_context: Optional[WorkScheduleContext] = None

    @property
    def status(self) -> str:
        """نام کوتاه وضعیت (معادل main_status)"""
        return self.main_status

    @property
    def warning_codes(self) -> List[str]:
        return [w.get('code') for w in self.warnings]

    @property
    def attendance_status_dict(self) -> Dict:
        """dict خروجی سازگر با analyze_day_status قدیمی"""
        return {
            'main_status': self.main_status,
            'main_label': self.main_label,
            'main_color': self.main_color,
            'warnings': self.warnings,
            'is_friday': self.is_friday,
            'is_holiday': self.is_holiday,
            'holiday_title': self.holiday_title,
        }


def compute_day_attendance(
    day: Optional[date_type] = None,
    day_records: Optional[List] = None,
    prev_day_records: Optional[List] = None,
    next_day_records: Optional[List] = None,
    is_friday: bool = False,
    holiday_title: Optional[str] = None,
    schedule_context: Optional[WorkScheduleContext] = None,
) -> DayAttendanceResult:
    """
    API اصلی موتور مرکزی: محاسبه کامل «تردد واقعی» یک روز.

    ترکیب همان دو تابع مرجع (بدون تغییر الگوریتم):
        analyze_day_status(...)  → status / night shift / warnings / sequence
        calculate_work_hours(...) → work hours / first enter / last exit (+pairs)

    context روز قبل/بعد (prev/next day records) لازم است چون تشخیص شیفت شب
    به آن‌ها وابسته است؛ مصرف‌کننده موظف است مانند رفتار فعلی attendance
    رکوردهای روزهای مجاور را در اختیار موتور بگذارد.
    """
    day_records = day_records or []
    prev_day_records = prev_day_records or []
    next_day_records = next_day_records or []

    full_status = _analyze_day_status(
        day=day,
        day_records=day_records,
        prev_day_records=prev_day_records,
        next_day_records=next_day_records,
        is_friday=is_friday,
        holiday_title=holiday_title,
    )
    is_night_shift = full_status['main_status'] == STATUS_NIGHT_SHIFT

    work_hours, first_enter, last_exit, pairs = _calculate_work_hours_detailed(
        day_records, is_night_shift
    )

    return DayAttendanceResult(
        day=day,
        main_status=full_status['main_status'],
        main_label=full_status['main_label'],
        main_color=full_status['main_color'],
        is_night_shift=is_night_shift,
        has_sequence_error=full_status['has_sequence_error'],
        sequence_error_detail=full_status['sequence_error_detail'],
        warnings=full_status['warnings'],
        is_friday=full_status['is_friday'],
        is_holiday=full_status['is_holiday'],
        holiday_title=full_status['holiday_title'],
        work_hours=work_hours,
        first_enter=first_enter,
        last_exit=last_exit,
        pairs=pairs,
        enter_count=len([r for r in day_records if getattr(r, 'punch', None) == 0]),
        exit_count=len([r for r in day_records if getattr(r, 'punch', None) == 1]),
        schedule_context=schedule_context,
    )
