"""
Phase 4 — Regression برای اتصال `/admin/attendance/user/{id}` به Central Engine.

مرجع «Before» = کد route پیش از migration (commit 8d73fff):

    analyze_day_status(...)  →  leave override  →  calculate_work_hours(...)

این pipeline منجمد از Phase 3 وارد می‌شود چون day-loop دو route پیش از
migration کاملاً یکسان بود؛ بعد از migration همه روزها + جمع‌ها +
محاسبات هفتگی قبل/بعد مقایسه می‌شوند:

    status / warnings / work_hours / first_enter / last_exit
    total_work_hours_month / monthly duty / balance / weekly values

سیاست (Policy) و ساعت موظفی از `compute_required_minutes_for_range` می‌آید —
هیچ مقدار ثابتی (7.20 / 7.33 / 440) در این تست به عنوان موظفی route فرض نمی‌شود.
"""
import inspect
import json
import os
from datetime import date, datetime, time, timedelta

import pytest

from .conftest import login_as
from core.attendance_calculator import (
    STATUS_COMPLETE, STATUS_LEAVE, STATUS_NIGHT_SHIFT,
)
from models.attendance import Attendance, AttendancePolicy
from models.employee import Employee
from web.services.attendance_policy_service import compute_required_minutes_for_range
from web.routes.attendance import format_hours_hhmm

from .test_attendance_route_regression import (
    J_YEAR, J_MONTH, G_START, G_END,
    HOLIDAY_DATE, HOLIDAY_TITLE, LEAVE_DATES, MISSION_DATE, REST_DATE,
    EXPECTED_STATUS,
    _seed_punches, _seed_holiday, _seed_day_statuses, _seed_leaves,
    _cleanup_holiday, _month_bounds, _fetch_records_with_margin,
    pre_migration_pipeline, _json_safe, _seed_user_policy,
)

# کلیدهای context که بین دو اجرای تست ثابت نیستند (هویت کاربران تست)
VOLATILE_CTX_KEYS = {'user', 'target_user', 'target_employee',
                     'target_user_id', 'employees_data'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _seed_target(db, make_user):
    """ادمین (بازدیدکننده) + کاربر هدف با seed کامل تردد/مرخصی/مأموریت/تعطیل."""
    admin = make_user(role='admin', department='9')
    target = make_user(role='user', department='4', balance_al=30)
    uid = target['user_id']
    _seed_punches(db, uid)
    _seed_holiday(db)
    _seed_day_statuses(db, uid)
    _seed_leaves(db, uid)
    return admin, target


def _capture_admin_context(client, monkeypatch, uid,
                           year=J_YEAR, month=J_MONTH, extra_query=''):
    """GET /admin/attendance/user/{uid} و برگرداندن context واقعیِ template + HTML."""
    import web.routes.admin as route_mod

    captured = {}
    original = route_mod.templates.TemplateResponse

    def spy(*args, **kwargs):
        ctx = None
        if len(args) >= 3 and isinstance(args[2], dict):
            ctx = args[2]
        elif isinstance(kwargs.get('context'), dict):
            ctx = kwargs['context']
        if ctx is not None:
            captured.clear()
            captured.update(ctx)
        return original(*args, **kwargs)

    monkeypatch.setattr(route_mod.templates, 'TemplateResponse', spy)
    url = f'/admin/attendance/user/{uid}?year={year}&month={month}{extra_query}'
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 200, resp.status_code
    assert captured, 'context گرفته نشد — route به template درست پاسخ نداد'
    return dict(captured), resp.text


def _cleanup_policy(db, *user_ids):
    db.query(AttendancePolicy).filter(
        AttendancePolicy.user_id.in_(list(user_ids))
    ).delete(synchronize_session=False)
    db.commit()


def _normalize_admin_ctx(ctx):
    """JSON-safe از context برای مقایسه before/after (بدون فیلدهای volatile)."""
    out = {}
    for key, value in ctx.items():
        if key in VOLATILE_CTX_KEYS:
            continue
        if key == 'days':
            out['days'] = [
                {
                    'date': d['date'].isoformat(),
                    'work_hours': d['work_hours'],
                    'first_enter': _json_safe(d['first_enter']),
                    'last_exit': _json_safe(d['last_exit']),
                    'work_hours_display': d['work_hours_display'],
                    'is_friday': d['is_friday'],
                    'is_holiday': d['is_holiday'],
                    'holiday_title': d['holiday_title'],
                    'is_mission': d['is_mission'],
                    'is_rest': d['is_rest'],
                    'hourly_leave_minutes': d['hourly_leave_minutes'],
                    'hourly_leave_display': d['hourly_leave_display'],
                    'hourly_mission_display': d['hourly_mission_display'],
                    'jalali_date': d['jalali_date'],
                    'day_name': d['day_name'],
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


def _reference_days(db, uid):
    """روزهای reference = pipeline منجمدِ پیش از migration + پرچم‌های ثابت."""
    records = _fetch_records_with_margin(db, uid)
    holiday_dates = {HOLIDAY_DATE: HOLIDAY_TITLE}
    leaves_by_date = {d: 'AL' for d in LEAVE_DATES}
    expected = pre_migration_pipeline(records, holiday_dates, leaves_by_date)
    for d in expected:
        d['is_friday'] = d['date'].weekday() == 4
        d['is_holiday'] = d['date'] == HOLIDAY_DATE
    return expected, holiday_dates, leaves_by_date


def _weekly_reference(db, emp, ref_days, holiday_dates, leaves_by_date):
    """
    همان الگوریتم کارت‌های هفتگی route (ماه‌های گذشته) روی روزهای reference —
    منطق دست‌نخورده است؛ ورودی فقط از pipeline قبل از migration می‌آید.
    """
    month_start_g, month_end_g = _month_bounds()
    rest_dates = {REST_DATE}
    mission_dates = {MISSION_DATE}

    first_day = month_start_g
    days_since_first_saturday = (first_day.weekday() + 2) % 7
    first_saturday = first_day - timedelta(days=days_since_first_saturday)

    overtime = 0.0
    deficit = 0.0
    weeks = 0
    current_week_start = first_saturday
    while current_week_start <= month_end_g:
        current_week_end = current_week_start + timedelta(days=6)
        week_hours = 0.0
        week_duty_days = 0
        for day in ref_days:
            if current_week_start <= day['date'] <= current_week_end:
                week_hours += day['work_hours']
                if not day['is_friday'] and not day['is_holiday']:
                    is_leave = day['status']['main_status'] == STATUS_LEAVE
                    is_rest = day['date'] in rest_dates
                    is_mission = day['date'] in mission_dates
                    if not is_leave and not is_rest and not is_mission:
                        week_duty_days += 1
        required = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=current_week_start, end_date=current_week_end,
            rest_dates=rest_dates, holiday_dates=holiday_dates,
            leaves_by_date=leaves_by_date,
            hourly_leave_minutes_by_date={},
            mission_dates=mission_dates,
            hourly_mission_minutes_by_date={},
        )
        week_duty_hours = required / 60
        week_balance = week_hours - week_duty_hours
        if week_duty_days > 0:
            weeks += 1
            if week_balance >= 0:
                overtime += week_balance
            else:
                deficit += abs(week_balance)
        current_week_start += timedelta(days=7)
    return overtime, deficit, weeks


# ---------------------------------------------------------------------------
# ۱. قبل/بعد: روز به روز + جمع‌های ماهانه
# ---------------------------------------------------------------------------
class TestAdminUserAttendanceBeforeAfter:
    def test_route_matches_pre_migration_pipeline(self, db, client, make_user,
                                                  monkeypatch):
        admin, target = _seed_target(db, make_user)
        uid = target['user_id']
        try:
            login_as(client, admin['national_code'])
            ctx, html = _capture_admin_context(client, monkeypatch, uid)

            # ---- reference: منطق قبل از migration ----
            expected_days, holiday_dates, leaves_by_date = _reference_days(db, uid)

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
                assert act['work_hours_display'] == \
                    format_hours_hhmm(exp['work_hours']), exp['date']

            # ---- monthly work hours (actual از موتور مرکزی) ----
            ref_total = sum(d['work_hours'] for d in expected_days)
            assert ctx['total_work_hours_month'] == pytest.approx(ref_total)
            assert ctx['total_work_hours_display'] == format_hours_hhmm(ref_total)

            # ---- monthly duty (Policy) + balance ----
            month_start_g, month_end_g = _month_bounds()
            emp = db.query(Employee).filter(Employee.user_id == uid).first()
            required_minutes = compute_required_minutes_for_range(
                db=db, employee=emp,
                start_date=month_start_g, end_date=month_end_g,
                rest_dates={REST_DATE}, holiday_dates=holiday_dates,
                leaves_by_date=leaves_by_date,
                hourly_leave_minutes_by_date={},
                mission_dates={MISSION_DATE},
                hourly_mission_minutes_by_date={},
            )
            duty_hours = required_minutes / 60
            assert ctx['monthly_duty_display'] == format_hours_hhmm(duty_hours)
            assert ctx['monthly_balance'] == pytest.approx(ref_total - duty_hours)
            # ماه گذشته → reference_date = آخرین روز ⇒ instant == monthly
            assert ctx['instant_duty_display'] == ctx['monthly_duty_display']
            assert ctx['instant_balance'] == pytest.approx(ctx['monthly_balance'])

            # ---- میانگین روزانه از همان روزها ----
            days_with_work = [d for d in expected_days if d['work_hours'] > 0]
            assert ctx['daily_avg_days'] == len(days_with_work)
            if days_with_work:
                assert ctx['daily_avg_hours_display'] == format_hours_hhmm(
                    ref_total / len(days_with_work))

            # ---- dump اختیاری برای مقایسه before/after کل context ----
            dump_path = os.getenv('ADMIN_CTX_DUMP')
            if dump_path:
                with open(dump_path, 'w', encoding='utf-8') as fh:
                    json.dump(_normalize_admin_ctx(ctx), fh,
                              ensure_ascii=False, indent=2, sort_keys=True)

            # ---- sanity: UI بدون تغییر (labelها در HTML هستند) ----
            assert '🌙 شیفت شب' in html
            assert '🌴 مرخصی استحقاقی' in html
            assert '✅ کامل' in html
        finally:
            _cleanup_holiday(db)

    def test_expected_status_matrix_and_warnings(self, db, client, make_user,
                                                 monkeypatch):
        """وضعیت/هشدارها/پرچم‌های Policy هر روز seedشده — عین رفتار قبل."""
        admin, target = _seed_target(db, make_user)
        uid = target['user_id']
        try:
            login_as(client, admin['national_code'])
            ctx, _ = _capture_admin_context(client, monkeypatch, uid)
            by_date = {d['date']: d for d in ctx['days']}

            for d, expected in EXPECTED_STATUS.items():
                assert by_date[d]['status']['main_status'] == expected, d

            # شب‌های مرز ماه با حاشیه fetch
            assert by_date[G_START]['work_hours'] == pytest.approx(6.0)
            assert by_date[G_START]['first_enter'] == datetime(2024, 3, 20, 0, 0, 0)
            assert by_date[G_END]['work_hours'] == pytest.approx(7199 / 3600)

            # مرخصی با الگوی شب: وضعیت leave ولی کارکرد غیرشب (fallback رفتار قبلی)
            assert by_date[date(2024, 4, 7)]['work_hours'] == 0.0
            assert by_date[date(2024, 4, 6)]['work_hours'] == pytest.approx(9.0)

            # flagهای Policy (مأموریت/استراحت) دست‌نخورده
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
# ۲. Source of Truth: route مستقیم از Central Engine استفاده می‌کند
# ---------------------------------------------------------------------------
def test_admin_route_source_of_truth(db, client, make_user, monkeypatch):
    import web.routes.admin as route_mod
    import core.attendance_calculator as engine_mod

    if not hasattr(route_mod, 'compute_day_attendance'):
        pytest.fail('Phase 4: compute_day_attendance باید مستقیم در admin.py باشد')

    # وابستگی مستقیم admin → core (نه از طریق attendance.py)
    assert route_mod.compute_day_attendance is engine_mod.compute_day_attendance

    # analyze_day_status دیگر توسط این ماژول استفاده/import نمی‌شود
    assert not hasattr(route_mod, 'analyze_day_status')

    # ---- منبع کد route هدف ----
    src = inspect.getsource(route_mod.admin_user_attendance)
    assert 'compute_day_attendance(' in src
    assert 'analyze_day_status(' not in src
    # pairing سفارشی ممنوع
    assert 'punch ==' not in src
    # ساعت موظفی ثابت ممنوع
    for hard in ('7.20', '7.33', '7:20', 'DAILY_DUTY_HOURS'):
        assert hard not in src, hard

    # ---- شمارش صداها هنگام GET واقعی ----
    admin, target = _seed_target(db, make_user)
    uid = target['user_id']
    try:
        login_as(client, admin['national_code'])

        calls = {'engine': 0, 'days': []}
        real_engine = route_mod.compute_day_attendance

        def engine_spy(*args, **kwargs):
            calls['engine'] += 1
            day = kwargs.get('day') if kwargs else None
            if day is None and args:
                day = args[0]
            calls['days'].append(day)
            return real_engine(*args, **kwargs)

        wh_calls = {'n': 0}
        real_wh = route_mod.calculate_work_hours

        def wh_spy(*args, **kwargs):
            wh_calls['n'] += 1
            return real_wh(*args, **kwargs)

        monkeypatch.setattr(route_mod, 'compute_day_attendance', engine_spy)
        monkeypatch.setattr(route_mod, 'calculate_work_hours', wh_spy)

        _capture_admin_context(client, monkeypatch, uid)

        # موتور مرکزی برای همه روزهای ماه (بدون استثنا)
        month_days = (G_END - G_START).days + 1
        assert calls['engine'] == month_days
        assert all(d is not None and G_START <= d <= G_END
                   for d in calls['days'])

        # calculate_work_hours فقط به عنوان fallbackِ اورراید مرخصیِ شب
        # (در داده‌های seed فقط 2024-04-07 شب است و leave می‌شود)
        assert wh_calls['n'] == 1
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۳. محاسبات هفتگی: ورودی از روزهای مرکزی، منطق موجود دست‌نخورده
# ---------------------------------------------------------------------------
def test_weekly_calculations_from_central_days(db, client, make_user,
                                               monkeypatch):
    admin, target = _seed_target(db, make_user)
    uid = target['user_id']
    try:
        login_as(client, admin['national_code'])
        ctx, _ = _capture_admin_context(client, monkeypatch, uid)

        ref_days, holiday_dates, leaves_by_date = _reference_days(db, uid)
        emp = db.query(Employee).filter(Employee.user_id == uid).first()

        # ماه گذشته → کارت‌های اضافه/کسر هفتگی فعال
        assert ctx['show_weekly_balance_cards'] is True
        assert ctx['show_this_week_card'] is False
        assert ctx['show_prev_week_card'] is False

        overtime, deficit, weeks = _weekly_reference(
            db, emp, ref_days, holiday_dates, leaves_by_date)

        assert ctx['weeks_count'] == weeks
        assert ctx['weekly_overtime_total_display'] == format_hours_hhmm(overtime)
        assert ctx['weekly_deficit_total_display'] == format_hours_hhmm(deficit)

        # progress از همان جمع و همان موظفی
        month_start_g, month_end_g = _month_bounds()
        required = compute_required_minutes_for_range(
            db=db, employee=emp,
            start_date=month_start_g, end_date=month_end_g,
            rest_dates={REST_DATE}, holiday_dates=holiday_dates,
            leaves_by_date=leaves_by_date,
            hourly_leave_minutes_by_date={},
            mission_dates={MISSION_DATE},
            hourly_mission_minutes_by_date={},
        )
        duty = required / 60
        ref_total = sum(d['work_hours'] for d in ref_days)
        expected_progress = min(100, round((ref_total / duty) * 100, 1)) \
            if duty > 0 else 0
        assert ctx['progress_percent'] == expected_progress
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۴. فیلتر بازه تاریخ + فیلتر وضعیت: semantics حفظ شده
# ---------------------------------------------------------------------------
def test_date_range_and_status_filters_preserved(db, client, make_user,
                                                 monkeypatch):
    admin, target = _seed_target(db, make_user)
    uid = target['user_id']
    try:
        login_as(client, admin['national_code'])

        # 1403/01/04 → 2024-03-23   |   1403/01/09 → 2024-03-28 (inclusive)
        lo, hi = date(2024, 3, 23), date(2024, 3, 28)
        ctx, _ = _capture_admin_context(
            client, monkeypatch, uid,
            extra_query='&from_date=1403/01/04&to_date=1403/01/09')

        dates = [d['date'] for d in ctx['days']]
        assert len(dates) == 6
        assert min(dates) == lo and max(dates) == hi
        assert all(lo <= d <= hi for d in dates)
        # روزهای خارج از بازه در جدول/جمع نیستند
        assert date(2024, 4, 1) not in dates          # روز ۷-ترددی خارج
        assert G_START not in dates                   # شب مرز ماه خارج

        # to_date شامل خودش است (ترددهای 2024-03-28 داخل بازه)
        day_28 = next(d for d in ctx['days'] if d['date'] == date(2024, 3, 28))
        assert len(day_28['records']) == 2

        # جمع بر اساس همان روزهای فیلترشده
        filtered_total = sum(d['work_hours'] for d in ctx['days'])
        assert ctx['total_work_hours_month'] == pytest.approx(filtered_total)
        assert ctx['total_records'] == sum(len(d['records'])
                                           for d in ctx['days'])

        # بدون فیلتر → کل ماه
        ctx_full, _ = _capture_admin_context(client, monkeypatch, uid)
        assert len(ctx_full['days']) == 31

        # فیلتر وضعیت (شب) همچنان روی status فیلتر می‌کند
        ctx_night, _ = _capture_admin_context(
            client, monkeypatch, uid, extra_query='&filter=night_shift')
        night_dates = {d['date'] for d in ctx_night['days']}
        assert night_dates == {d for d, s in EXPECTED_STATUS.items()
                               if s == STATUS_NIGHT_SHIFT}
        assert all(d['status']['main_status'] == STATUS_NIGHT_SHIFT
                   for d in ctx_night['days'])

        # کارت‌های خلاصه با فیلتر وضعیت تغییر نمی‌کنند (فقط جدول محدود می‌شود)
        assert ctx_night['total_work_hours_month'] == pytest.approx(
            ctx_full['total_work_hours_month'])
        assert ctx_night['monthly_balance'] == pytest.approx(
            ctx_full['monthly_balance'])
        assert ctx_night['instant_balance'] == pytest.approx(
            ctx_full['instant_balance'])
        night_table_total = sum(d['work_hours'] for d in ctx_night['days'])
        assert ctx_night['displayed_work_hours'] == pytest.approx(night_table_total)
        assert abs(ctx_night['total_work_hours_month'] - night_table_total) > 1e-9
    finally:
        _cleanup_holiday(db)


def test_status_filter_preserves_admin_monthly_summary(db, client, make_user,
                                                       monkeypatch):
    """فیلتر وضعیت در admin فقط جدول را محدود می‌کند."""
    admin, target = _seed_target(db, make_user)
    uid = target['user_id']
    try:
        login_as(client, admin['national_code'])
        ctx_all, _ = _capture_admin_context(client, monkeypatch, uid)
        for status_filter in ('complete', 'issues', 'leave'):
            ctx_f, _ = _capture_admin_context(
                client, monkeypatch, uid,
                extra_query=f'&filter={status_filter}')
            assert len(ctx_f['days']) < len(ctx_all['days'])
            assert ctx_f['total_work_hours_month'] == pytest.approx(
                ctx_all['total_work_hours_month'])
            assert ctx_f['monthly_balance'] == pytest.approx(
                ctx_all['monthly_balance'])
            assert ctx_f['instant_balance'] == pytest.approx(
                ctx_all['instant_balance'])
            assert ctx_f['daily_avg_days'] == ctx_all['daily_avg_days']
    finally:
        _cleanup_holiday(db)


def test_date_range_plus_status_filter_totals_follow_range_only(
        db, client, make_user, monkeypatch):
    """بازه تاریخ جمع خلاصه را محدود می‌کند؛ فیلتر وضعیت فقط جدول را."""
    admin, target = _seed_target(db, make_user)
    uid = target['user_id']
    try:
        login_as(client, admin['national_code'])
        range_q = '&from_date=1403/01/04&to_date=1403/01/09'
        ctx_range, _ = _capture_admin_context(
            client, monkeypatch, uid, extra_query=range_q)
        ctx_both, _ = _capture_admin_context(
            client, monkeypatch, uid,
            extra_query=range_q + '&filter=complete')

        assert ctx_both['total_work_hours_month'] == pytest.approx(
            ctx_range['total_work_hours_month'])
        assert len(ctx_both['days']) < len(ctx_range['days'])
        assert all(d['status']['main_status'] == STATUS_COMPLETE
                   for d in ctx_both['days'])
        # جمع خلاصه = همه روزهای بازه (بدون فیلتر وضعیت)
        assert ctx_both['total_work_hours_month'] == pytest.approx(
            sum(d['work_hours'] for d in ctx_range['days']))
    finally:
        _cleanup_holiday(db)


# ---------------------------------------------------------------------------
# ۵. ساعت موظفی فرد/گروه: Actual از موتور، Required از Policy
# ---------------------------------------------------------------------------
def test_group_schedule_required_differs_not_actual(db, client, make_user,
                                                    monkeypatch):
    """دو نفر با دو برنامه کاری متفاوت (Admin route):
         Employee A → Required = X | Employee B → Required = Y  (X != Y)
       در حالی که Actual Work هر دو از Central Engine و یکسان است.
    """
    admin = make_user(role='admin', department='9')
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

    try:
        login_as(client, admin['national_code'])
        results = {}
        for creds in (a, b):
            ctx, _ = _capture_admin_context(client, monkeypatch,
                                            creds['user_id'])
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
        assert ra['duty'] == format_hours_hhmm(31 * 360 / 60)
        assert rb['duty'] == format_hours_hhmm(31 * 480 / 60)
        assert ra['duty'] != format_hours_hhmm(31 * 440 / 60)  # نه fallback

        # Balance = Actual − Required − late/early (Admin route formula).
        # Punches 08:00–17:00 vs A policy 07:00–13:00 → 60m late × 4 days.
        # B policy 09:00–17:00 with same punches → no late/early.
        assert ra['balance'] == pytest.approx(
            ra['actual'] - 31 * 360 / 60 - (4 * 60 / 60.0)
        )
        assert rb['balance'] == pytest.approx(rb['actual'] - 31 * 480 / 60)
    finally:
        _cleanup_policy(db, a['user_id'], b['user_id'])
