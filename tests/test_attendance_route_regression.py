"""
Phase 3 — Regression برای اتصال `/attendance` به Central Attendance Engine.

مرجع «Before» = کد route پیش از migration (commit 1d2146e):

    analyze_day_status(...)  →  leave override  →  calculate_work_hours(...)

این pipeline به صورت frozen در همین فایل نگه داشته شده تا بعد از migration
(استفاده از `compute_day_attendance(...)`) مقایسه قبل/بعد ممکن باشد:

    status / warnings / work_hours / first_enter / last_exit / is_night_shift
    monthly_work_hours / monthly_duty_hours / balance

سیاست (Policy) و ساعت موظفی از `compute_required_minutes_for_range` می‌آید —
هیچ مقدار ثابتی (7.20 / 7.33 / 440) در این تست به عنوان موظفی route فرض نمی‌شود.
"""
import json
import os
from datetime import date, datetime, time, timedelta

import jdatetime
import pytest

from .conftest import login_as
from core.attendance_calculator import (
    STATUS_LEAVE,
    analyze_day_status,
    calculate_work_hours,
)
from models.attendance import Attendance, AttendancePolicy, AttendancePolicyDay
from models.daily_status import DailyStatus
from models.employee import Employee
from models.holiday import Holiday
from models.leave_request import LeaveRequest
from web.services.attendance_policy_service import compute_required_minutes_for_range
from web.routes.attendance import format_hours_hhmm

# ماه ثابت آزمایشی: 1403/01 → 2024-03-20 .. 2024-04-19
J_YEAR, J_MONTH = 1403, 1
G_START = date(2024, 3, 20)
G_END = date(2024, 4, 19)

LEAVE_TYPE_NAMES_LOCAL = {
    'AL': 'استحقاقی', 'SL': 'استعلاجی', 'RL': 'تشویقی',
    'CW': 'ذخیره', 'TL': 'توراهی',
}

# ---------------------------------------------------------------------------
# داده‌های seed: (تاریخ، لیست (ساعت، دقیقه، ثانیه، punch))
# punch: 0=ورود, 1=خروج
# ---------------------------------------------------------------------------
SEED_PUNCHES = [
    # --- خارج از ماه (context مرزی) ---
    (date(2024, 3, 19), [(22, 0, 0, 0)]),
    (date(2024, 4, 20), [(6, 0, 0, 1)]),
    # --- روز اول ماه: ورودِ دیروز → night shift ---
    (date(2024, 3, 20), [(6, 0, 0, 1)]),
    (date(2024, 3, 21), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    # جمعه‌کاری
    (date(2024, 3, 22), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    # تعطیل‌کاری
    (date(2024, 3, 23), [(9, 0, 0, 0), (16, 0, 0, 1)]),
    # چند تردد
    (date(2024, 3, 24), [(8, 0, 0, 0), (12, 0, 0, 1), (13, 0, 0, 0), (17, 0, 0, 1)]),
    (date(2024, 3, 25), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    # خروج بدون ورود (روز قبل last punch=خروج → نباید شب شود)
    (date(2024, 3, 26), [(17, 0, 0, 1)]),
    # ورود بدون خروج (روز بعد اولین punch ورود است → نباید شب شود)
    (date(2024, 3, 27), [(8, 0, 0, 0)]),
    # خطای ترتیب: دو ورود پشت‌سرهم (۲۹ مارس خالی است)
    (date(2024, 3, 28), [(8, 0, 0, 0), (9, 0, 0, 0)]),
    # 2024-03-29 (جمعه): بدون تردد
    # تردد تکراری
    (date(2024, 3, 30), [(8, 0, 0, 0), (8, 0, 30, 1)]),
    # فاصله غیرعادی ۱۳ ساعته
    (date(2024, 3, 31), [(8, 0, 0, 0), (21, 0, 0, 1)]),
    # ۷ تردد
    (date(2024, 4, 1), [(8, 0, 0, 0), (9, 0, 0, 1), (10, 0, 0, 0), (11, 0, 0, 1),
                        (12, 0, 0, 0), (13, 0, 0, 1), (14, 0, 0, 0)]),
    # شب: خروجِ روز بعد
    (date(2024, 4, 2), [(22, 0, 0, 0)]),
    (date(2024, 4, 3), [(6, 0, 0, 1)]),
    # مأموریت / استراحت
    (date(2024, 4, 4), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    (date(2024, 4, 5), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    # مرخصی (عادی + الگوی شب)
    (date(2024, 4, 6), [(8, 0, 0, 0), (17, 0, 0, 1)]),
    (date(2024, 4, 7), [(6, 0, 0, 1), (22, 0, 0, 0)]),
    # ساعت غیرعادی
    (date(2024, 4, 8), [(23, 0, 0, 0), (23, 30, 0, 1)]),
    # آخرین روز ماه: خروجِ روز بعد (خارج از ماه)
    (date(2024, 4, 19), [(22, 0, 0, 0)]),
]

HOLIDAY_DATE = date(2024, 3, 23)
HOLIDAY_TITLE = 'تعطیل آزمایشی'
LEAVE_DATES = [date(2024, 4, 6), date(2024, 4, 7)]
MISSION_DATE = date(2024, 4, 4)
REST_DATE = date(2024, 4, 5)

EXPECTED_STATUS = {
    date(2024, 3, 20): 'night_shift',
    date(2024, 3, 21): 'complete',
    date(2024, 3, 22): 'complete',
    date(2024, 3, 23): 'complete',
    date(2024, 3, 24): 'complete',
    date(2024, 3, 25): 'complete',
    date(2024, 3, 26): 'missing_enter',
    date(2024, 3, 27): 'missing_exit',
    date(2024, 3, 28): 'sequence_error',
    date(2024, 3, 29): 'no_attendance',
    date(2024, 3, 30): 'complete',
    date(2024, 3, 31): 'complete',
    date(2024, 4, 1): 'missing_exit',
    date(2024, 4, 2): 'night_shift',
    date(2024, 4, 3): 'night_shift',
    date(2024, 4, 4): 'complete',
    date(2024, 4, 5): 'complete',
    date(2024, 4, 6): 'leave',
    date(2024, 4, 7): 'leave',
    date(2024, 4, 8): 'complete',
    date(2024, 4, 19): 'night_shift',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_punches(db, user_id):
    for d, punches in SEED_PUNCHES:
        for (h, m, s, punch) in punches:
            db.add(Attendance(
                user_id=user_id,
                timestamp=datetime(d.year, d.month, d.day, h, m, s),
                punch=punch,
                status=15,
                source='L',
            ))
    db.commit()


def _seed_holiday(db):
    db.query(Holiday).filter(Holiday.holiday_date == HOLIDAY_DATE).delete()
    db.add(Holiday(holiday_date=HOLIDAY_DATE, title=HOLIDAY_TITLE,
                   is_national=True, group_id=None))
    db.commit()


def _cleanup_holiday(db):
    db.query(Holiday).filter(Holiday.holiday_date == HOLIDAY_DATE).delete()
    db.commit()


def _seed_day_statuses(db, user_id):
    db.add(DailyStatus(user_id=user_id, status_date=MISSION_DATE, status_code='M'))
    db.add(DailyStatus(user_id=user_id, status_date=REST_DATE, status_code='R'))
    db.commit()


def _seed_leaves(db, user_id):
    for d in LEAVE_DATES:
        db.add(LeaveRequest(
            user_id=user_id, leave_type='AL',
            from_date=d, to_date=d, days_count=1, status='A',
        ))
    db.commit()


def _capture_context(client, monkeypatch, year=J_YEAR, month=J_MONTH,
                     extra_query=''):
    """GET /attendance و برگرداندن context واقعیِ template + HTML."""
    import web.routes.attendance as route_mod

    captured = {}
    original = route_mod.templates.TemplateResponse

    def spy(*args, **kwargs):
        if len(args) >= 3 and isinstance(args[2], dict):
            captured.clear()
            captured.update(args[2])
        elif isinstance(kwargs.get('context'), dict):
            captured.clear()
            captured.update(kwargs['context'])
        return original(*args, **kwargs)

    monkeypatch.setattr(route_mod.templates, 'TemplateResponse', spy)
    resp = client.get(f'/attendance?year={year}&month={month}{extra_query}')
    assert resp.status_code == 200, resp.status_code
    return dict(captured), resp.text


def _month_bounds():
    j_start = jdatetime.date(J_YEAR, J_MONTH, 1)
    j_end = jdatetime.date(J_YEAR, J_MONTH + 1, 1) - timedelta(days=1)
    return j_start.togregorian(), j_end.togregorian()


def _fetch_records_with_margin(db, user_id):
    """دقیقاً همان query ماه + حاشیه route (‎-1 / +2 روز)."""
    month_start_g, month_end_g = _month_bounds()
    return db.query(Attendance).filter(
        Attendance.user_id == user_id,
        Attendance.timestamp >= month_start_g - timedelta(days=1),
        Attendance.timestamp <= month_end_g + timedelta(days=2),
        Attendance.is_deleted == False,
    ).order_by(Attendance.timestamp).all()


def pre_migration_pipeline(records, holiday_dates, leaves_by_date):
    """
    کپی frozen منطق route قبل از Phase 3 (merge نشده با موتور مرکزی):

        analyze_day_status → leave override → calculate_work_hours
    """
    days_dict = {}
    for record in records:
        days_dict.setdefault(record.timestamp.date(), []).append(record)

    month_start_g, month_end_g = _month_bounds()
    out = []
    current = month_start_g
    while current <= month_end_g:
        day_records = days_dict.get(current, [])
        prev_day_records = days_dict.get(current - timedelta(days=1), [])
        next_day_records = days_dict.get(current + timedelta(days=1), [])
        is_friday = current.weekday() == 4
        holiday_title = holiday_dates.get(current)

        status_info = analyze_day_status(
            day=current,
            day_records=day_records,
            prev_day_records=prev_day_records,
            next_day_records=next_day_records,
            is_friday=is_friday,
            holiday_title=holiday_title,
        )
        leave_type = leaves_by_date.get(current)
        if leave_type and not is_friday and holiday_title is None:
            type_name = LEAVE_TYPE_NAMES_LOCAL.get(leave_type, '')
            status_info['main_status'] = STATUS_LEAVE
            status_info['main_label'] = f'🌴 مرخصی {type_name}'
            status_info['main_color'] = 'info'

        work_hours, first_enter, last_exit = calculate_work_hours(
            day_records,
            is_night_shift=status_info['main_status'] == 'night_shift',
        )
        out.append({
            'date': current,
            'status': status_info,
            'work_hours': work_hours,
            'first_enter': first_enter,
            'last_exit': last_exit,
            'is_night_shift': status_info['main_status'] == 'night_shift',
        })
        current += timedelta(days=1)
    return out


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'strftime'):          # jdatetime
        return value.strftime('%Y/%m/%d')
    if hasattr(value, '_sa_instance_state'):  # ORM object → skip
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _normalize_context(ctx):
    out = {}
    for key, value in ctx.items():
        if key == 'days':
            out['days'] = [
                {
                    'date': d['date'].isoformat(),
                    'work_hours': d['work_hours'],
                    'first_enter': _json_safe(d['first_enter']),
                    'last_exit': _json_safe(d['last_exit']),
                    'work_hours_display': d['work_hours_display'],
                    'is_night_shift': d['is_night_shift'],
                    'is_friday': d['is_friday'],
                    'is_holiday': d['is_holiday'],
                    'holiday_title': d['holiday_title'],
                    'is_mission': d['is_mission'],
                    'is_rest': d['is_rest'],
                    'status': _json_safe(d['status']),
                    'records': [(r.timestamp.isoformat(), r.punch)
                                for r in sorted(d['records'],
                                               key=lambda x: x.timestamp)],
                }
                for d in value
            ]
        elif hasattr(value, '_sa_instance_state'):
            continue
        else:
            out[key] = _json_safe(value)
    return out


# ---------------------------------------------------------------------------
# تست اصلی: قبل (pipeline منجمد) == بعد (route با موتور مرکزی)
# ---------------------------------------------------------------------------
class TestAttendanceRouteBeforeAfter:
    def test_route_matches_pre_migration_pipeline(self, db, client, make_user,
                                                  monkeypatch):
        creds = make_user(role='user', balance_al=30, department='4')
        uid = creds['user_id']
        _seed_punches(db, uid)
        _seed_holiday(db)
        _seed_day_statuses(db, uid)
        _seed_leaves(db, uid)

        try:
            login_as(client, creds['national_code'])
            ctx, html = _capture_context(client, monkeypatch)

            # ---- reference: منطق قبل از migration ----
            records = _fetch_records_with_margin(db, uid)
            holiday_dates = {HOLIDAY_DATE: HOLIDAY_TITLE}
            leaves_by_date = {d: 'AL' for d in LEAVE_DATES}
            expected_days = pre_migration_pipeline(
                records, holiday_dates, leaves_by_date)

            actual_days = ctx['days']
            assert len(actual_days) == len(expected_days)

            for exp, act in zip(expected_days, actual_days):
                assert act['date'] == exp['date']
                assert act['status'] == exp['status'], exp['date']
                assert act['work_hours'] == pytest.approx(exp['work_hours']), \
                    f"work_hours {exp['date']}"
                assert act['first_enter'] == exp['first_enter'], \
                    f"first_enter {exp['date']}"
                assert act['last_exit'] == exp['last_exit'], \
                    f"last_exit {exp['date']}"
                assert act['is_night_shift'] == exp['is_night_shift'], \
                    f"is_night_shift {exp['date']}"

            # ---- monthly work hours (actual) ----
            ref_total = sum(d['work_hours'] for d in expected_days)
            assert ctx['total_work_hours_month'] == pytest.approx(ref_total)
            assert ctx['total_work_hours_display'] == format_hours_hhmm(ref_total)

            # ---- monthly duty (Policy) + balance ----
            month_start_g, month_end_g = _month_bounds()
            emp = db.query(Employee).filter(Employee.user_id == uid).first()
            rest_dates = {REST_DATE}
            mission_dates = {MISSION_DATE}
            required_minutes = compute_required_minutes_for_range(
                db=db, employee=emp,
                start_date=month_start_g, end_date=month_end_g,
                rest_dates=rest_dates, holiday_dates=holiday_dates,
                leaves_by_date=leaves_by_date,
                hourly_leave_minutes_by_date={},
                mission_dates=mission_dates,
                hourly_mission_minutes_by_date={},
            )
            duty_hours = required_minutes / 60
            assert ctx['monthly_duty_display'] == format_hours_hhmm(duty_hours)
            assert ctx['monthly_balance'] == pytest.approx(ref_total - duty_hours)
            # ماه گذشته → reference_date = آخرین روز ⇒ instant == monthly
            assert ctx['instant_duty_display'] == ctx['monthly_duty_display']
            assert ctx['instant_balance'] == pytest.approx(ctx['monthly_balance'])

            # ---- dump اختیاری برای مقایسه before/after کل context ----
            dump_path = os.getenv('ATTENDANCE_CTX_DUMP')
            if dump_path:
                with open(dump_path, 'w', encoding='utf-8') as fh:
                    json.dump(_normalize_context(ctx), fh,
                              ensure_ascii=False, indent=2, sort_keys=True)

            # ---- sanity: UI بدون تغییر (status labelها در HTML هستند) ----
            assert '🌙 شیفت شب' in html
            assert '🌴 مرخصی استحقاقی' in html
            assert '✅ کامل' in html
        finally:
            _cleanup_holiday(db)

    def test_expected_status_matrix(self, db, client, make_user, monkeypatch):
        """وضعیت هر روز seedشده باید دقیقاً همان چیزی باشد که انتظار می‌رود."""
        creds = make_user(role='user', balance_al=30, department='4')
        uid = creds['user_id']
        _seed_punches(db, uid)
        _seed_holiday(db)
        _seed_day_statuses(db, uid)
        _seed_leaves(db, uid)

        try:
            login_as(client, creds['national_code'])
            ctx, _ = _capture_context(client, monkeypatch)
            by_date = {d['date']: d for d in ctx['days']}

            for d, expected in EXPECTED_STATUS.items():
                assert by_date[d]['status']['main_status'] == expected, d

            # شب‌های مرز ماه باید با حاشیه fetch تشخیص داده شوند
            assert by_date[G_START]['work_hours'] == pytest.approx(6.0)
            assert by_date[G_START]['first_enter'] == datetime(2024, 3, 20, 0, 0, 0)
            assert by_date[G_END]['work_hours'] == pytest.approx(7199 / 3600)

            # مرخصی با الگوی شب: وضعیت leave ولی کارکرد غیرشب (رفتار قبلی)
            assert by_date[date(2024, 4, 7)]['work_hours'] == 0.0
            assert by_date[date(2024, 4, 6)]['work_hours'] == pytest.approx(9.0)

            # flagهای Policy (موظفی) دست‌نخورده
            assert by_date[MISSION_DATE]['is_mission'] is True
            assert by_date[REST_DATE]['is_rest'] is True

            # هشدارها
            codes = {d: [w['code'] for w in d_status['warnings']]
                     for d, d_status in
                     ((k, v['status']) for k, v in by_date.items())}
            assert codes[date(2024, 3, 22)] == ['friday_work']
            assert codes[date(2024, 3, 23)] == ['holiday_work']
            assert codes[date(2024, 3, 30)] == ['duplicate']
            assert codes[date(2024, 3, 31)] == ['abnormal_gap']
            assert codes[date(2024, 4, 1)] == ['too_many']
            assert codes[date(2024, 4, 8)] == ['abnormal_time']
        finally:
            _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ساعت موظفی per-group: Actual یکسان، Required متفاوت (بدون hard-code)
# ---------------------------------------------------------------------------
def _seed_user_policy(db, user_id, department, start_t, end_t):
    policy = AttendancePolicy(
        employment_type_code=department,
        user_id=user_id,
        effective_from_date=date(2024, 3, 1),
        effective_to_date=date(2024, 4, 30),
        late_enabled=True, late_allowed_minutes=0,
        late_reference_mode='FIXED_TIME',
        early_leave_enabled=True, early_leave_allowed_minutes=0,
        early_leave_reference_mode='FIXED_TIME',
        is_active=True,
    )
    db.add(policy)
    db.flush()
    for wd in range(7):
        db.add(AttendancePolicyDay(
            policy_id=policy.id, weekday=wd,
            is_working_day=True, start_time=start_t, end_time=end_t,
        ))
    db.commit()


def test_group_schedule_changes_required_not_actual(db, client, make_user,
                                                    monkeypatch):
    """دو نفر با دو برنامه کاری متفاوت:
         Employee A → Schedule A → required = X
         Employee B → Schedule B → required = Y   (X != Y)
       در حالی که Actual Work هر دو یکسان است.
    """
    a = make_user(role='employee', balance_al=None, department='1')
    b = make_user(role='employee', balance_al=None, department='4')

    _seed_user_policy(db, a['user_id'], '1', time(7, 0), time(13, 0))   # 360
    _seed_user_policy(db, b['user_id'], '4', time(9, 0), time(17, 0))   # 480

    # کارکرد یکسان برای هر دو: ۴ روز کاری کامل (۹ ساعت)
    workdays = [date(2024, 3, 25), date(2024, 3, 26),
                date(2024, 3, 27), date(2024, 3, 28)]
    for uid in (a['user_id'], b['user_id']):
        for d in workdays:
            db.add(Attendance(user_id=uid,
                              timestamp=datetime(d.year, d.month, d.day, 8, 0),
                              punch=0, status=15, source='L'))
            db.add(Attendance(user_id=uid,
                              timestamp=datetime(d.year, d.month, d.day, 17, 0),
                              punch=1, status=15, source='L'))
        db.commit()

    results = {}
    for creds in (a, b):
        login_as(client, creds['national_code'])
        ctx, _ = _capture_context(client, monkeypatch)
        results[creds['user_id']] = {
            'actual': ctx['total_work_hours_month'],
            'duty': ctx['monthly_duty_display'],
            'balance': ctx['monthly_balance'],
        }

    ra, rb = results[a['user_id']], results[b['user_id']]

    # Actual Work یکسان (از موتور مرکزی)
    assert ra['actual'] == pytest.approx(rb['actual'])
    assert ra['actual'] == pytest.approx(4 * 9.0)

    # Required Work متفاوت (از Policy هر فرد — نه مقدار ثابت)
    assert ra['duty'] != rb['duty']
    # ۳۱ روز × ۳۶۰ دقیقه = ۱۸۶ ساعت  |  ۳۱ روز × ۴۸۰ دقیقه = ۲۴۸ ساعت
    assert ra['duty'] == format_hours_hhmm(31 * 360 / 60)
    assert rb['duty'] == format_hours_hhmm(31 * 480 / 60)
    assert ra['duty'] != format_hours_hhmm(31 * 440 / 60)  # نه fallback قدیمی

    # Balance = Actual − Required − late/early.
    # Punches 08:00–17:00 vs A policy 07:00–13:00 → 60m late × 4 days.
    assert ra['balance'] == pytest.approx(
        ra['actual'] - 31 * 360 / 60 - (4 * 60 / 60.0)
    )
    assert rb['balance'] == pytest.approx(rb['actual'] - 31 * 480 / 60)


# ---------------------------------------------------------------------------
# فیلتر وضعیت فقط جدول را محدود می‌کند؛ کارت‌های خلاصه ماه کامل می‌مانند
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('status_filter', [
    'complete', 'night_shift', 'issues', 'leave', 'no_attendance',
])
def test_status_filter_does_not_change_monthly_summary(
        db, client, make_user, monkeypatch, status_filter):
    creds = make_user(role='user', balance_al=30, department='4')
    uid = creds['user_id']
    _seed_punches(db, uid)
    _seed_holiday(db)
    _seed_day_statuses(db, uid)
    _seed_leaves(db, uid)

    try:
        login_as(client, creds['national_code'])
        ctx_all, _ = _capture_context(client, monkeypatch)
        ctx_f, _ = _capture_context(
            client, monkeypatch, extra_query=f'&filter={status_filter}')

        assert len(ctx_f['days']) <= len(ctx_all['days'])
        assert len(ctx_f['days']) < len(ctx_all['days']), (
            f'فیلتر {status_filter} باید حداقل یک روز را حذف کند')

        if status_filter == 'issues':
            allowed = {
                'missing_exit', 'missing_enter',
                'sequence_error', 'imbalance',
            }
            assert all(d['status']['main_status'] in allowed
                       for d in ctx_f['days'])
        else:
            assert all(
                d['status']['main_status'] == status_filter
                for d in ctx_f['days']
            )

        # کارت‌های خلاصه بدون تغییر نسبت به ماه کامل
        assert ctx_f['total_work_hours_month'] == pytest.approx(
            ctx_all['total_work_hours_month'])
        assert ctx_f['monthly_balance'] == pytest.approx(
            ctx_all['monthly_balance'])
        assert ctx_f['instant_balance'] == pytest.approx(
            ctx_all['instant_balance'])
        assert ctx_f['progress_percent'] == ctx_all['progress_percent']
        assert ctx_f['monthly_duty_display'] == ctx_all['monthly_duty_display']

        # جمع کارکرد روزهای نمایش‌داده‌شده = جمع جدول فیلترشده
        table_total = sum(d['work_hours'] for d in ctx_f['days'])
        assert ctx_f['displayed_work_hours'] == pytest.approx(table_total)
        assert abs(ctx_f['total_work_hours_month'] - table_total) > 1e-9
    finally:
        _cleanup_holiday(db)
