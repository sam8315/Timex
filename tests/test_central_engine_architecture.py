"""
Phase 8 — نگهبان‌های معماری (static / source-level).

هدف: جلوگیری از اینکه در آینده دوباره یک موتور دوم برای Actual Attendance
ساخته شود، یا لایه‌ها دوباره به هم وابسته شوند. این تست‌ها عمداً **سورس** را
می‌خوانند، چون لازمه‌ی قرارداد معماری همین است.

پوشش:
  8.2  Central Engine = Actual-only (بدون Policy/Required/Duty)
  8.3  Central Engine بدون ساعت موظفی hard-code
  8.4  هیچ `core -> web` تازه‌ای اضافه نشود
  8.4  هیچ `web.services -> web.routes` وابستگی‌ای نباشد
  8.5  re-exportهای legacy در `web/routes/attendance.py` حفظ شوند
  8.16 لایه‌ی export چیزی را دوباره حساب نکند
"""
import ast
import re
from pathlib import Path

import pytest

import core.attendance_calculator as engine_mod
import web.routes.attendance as attendance_route_mod

ROOT = Path(engine_mod.__file__).resolve().parents[1]
ENGINE = Path(engine_mod.__file__)
CORE_DIR = ROOT / 'core'
WEB_SERVICES_DIR = ROOT / 'web' / 'services'
ROUTE_MODULE = Path(attendance_route_mod.__file__)

EXPORTERS = [
    ROOT / 'core' / 'excel_detailed_export_v2.py',
    ROOT / 'core' / 'pdf_detailed_export_v2.py',
]


def _imports(path: Path):
    """نام ماژول‌های import شده در سطح بالا و داخل تابع."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    top, nested = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            (top if isinstance(getattr(node, 'parent', None), type(None))
             else nested).append(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.append(node.module or '')
    # ast.walk ندارد parent؛ ساده‌تر: کل importها
    return [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]


def _top_level_imports(path: Path):
    """فقط importهای سطح ماژول (نه داخل تابع) — برای تشخیص coupling."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = []
    for node in tree.body:  # فقط بدنه‌ی سطحی
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or '')
    return out


# ============================================================
# 8.2 — Central Engine = Actual-only
# ============================================================
# توکن‌هایی که اگر *کد* (نه کامنت/دکسترینگ) به آن‌ها اشاره کند یعنی
# Central Engine دارد Policy/Required را محاسبه می‌کند.
FORBIDDEN_IN_ENGINE_CODE = {
    'compute_required_minutes',
    'compute_required_minutes_for_range',
    'resolve_policy',
    'compute_effective_required_minutes_for_day',
    'DAILY_DUTY_HOURS',
    'DEFAULT_REQUIRED_MINUTES',
    'DAILY_REQUIRED_HOURS',
    'WEEKLY_REQUIRED_HOURS',
}


def _code_without_comments_and_strings(path: Path) -> str:
    """سورس با حذف کامنت‌ها و رشته‌ها — فقط کد واقعی باقی می‌ماند."""
    source = path.read_text(encoding='utf-8')
    out, i, n = [], 0, len(source)
    while i < n:
        ch = source[i]
        if ch == '#':
            while i < n and source[i] != '\n':
                i += 1
        elif source.startswith('"""', i) or source.startswith("'''", i):
            quote = source[i:i + 3]
            i += 3
            while i < n and not source.startswith(quote, i):
                i += 1
            i += 3
            out.append('""')
        elif ch in '"\'':
            i += 1
            while i < n and source[i] != ch:
                if source[i] == '\\':
                    i += 1
                i += 1
            i += 1
            out.append('""')
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def test_engine_does_not_compute_required_work():
    code = _code_without_comments_and_strings(ENGINE)
    for token in FORBIDDEN_IN_ENGINE_CODE:
        assert token not in code, \
            f'Central Engine نباید {token} را داشته باشد'


def test_engine_does_not_import_policy_or_web():
    """Central Engine نباید هیچ Policy/Web/DB وابستگی‌ای داشته باشد."""
    for name in _top_level_imports(ENGINE):
        assert not name.startswith('web'), f'engine -> web: {name}'
        assert not name.startswith('models'), f'engine -> models: {name}'
        assert not name.startswith('database'), f'engine -> database: {name}'

    tree = ast.parse(ENGINE.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('web'):
            pytest.fail(f'engine -> web (nested import) در خط {node.lineno}')


def test_engine_does_not_query_holidays_or_leave_tables():
    """تعطیلی/مرخصی از بیرون داده می‌شود، نه از DB."""
    code = _code_without_comments_and_strings(ENGINE)
    for token in ('db.query', 'session.query', 'select(', 'LeaveRequest',
                  'Holiday', 'DailyStatus', 'Employee'):
        assert token not in code, \
            f'Central Engine نباید {token} را داشته باشد (Actual-only)'


def test_holiday_and_friday_are_inputs_not_computed():
    """تعطیلی/جمعه پاسر داده می‌شوند؛ موتور خودش تقویم نمی‌خواند."""
    code = _code_without_comments_and_strings(ENGINE)
    assert 'jdatetime' not in code, 'موتور نباید تقویم/تاریخ شمسی بسازد'
    assert 'def ' in code  # sanity


# ============================================================
# 8.3 — بدون ساعت موظفی hard-code
# ============================================================
HARD_CODED_DUTY = [
    (r'7:20', '7:20'),
    (r'\b7\.20\b', '7.20'),
    (r'\b7\.33\b', '7.33'),
    (r'\b440\b', '440'),
    (r'DAILY_DUTY_HOURS', 'DAILY_DUTY_HOURS'),
    (r'compute_required_minutes', 'compute_required_minutes'),
]


@pytest.mark.parametrize('pattern, label', HARD_CODED_DUTY)
def test_engine_has_no_hardcoded_duty(pattern, label):
    code = _code_without_comments_and_strings(ENGINE)
    assert not re.search(pattern, code), \
        f'Central Engine نباید ساعت موظفی ثابت {label} داشته باشد'


def test_engine_schedule_context_is_passive_only():
    """
    `WorkScheduleContext` مجاز است، ولی نباید روی محاسبه اثر بگذارد.
    این تست تضمین می‌کند context فقط نگه داشته/برگردانده می‌شود.
    """
    from core.attendance_calculator import WorkScheduleContext

    a = WorkScheduleContext(effective_work_minutes=100,
                            schedule_code='X', scheduled_start=1, scheduled_end=2)
    b = WorkScheduleContext(effective_work_minutes=999,
                            schedule_code='Y', scheduled_start=9, scheduled_end=9)

    # context تغییری در رفتار موتور ایجاد نکند
    from datetime import date, datetime

    class Rec:
        def __init__(self, ts, punch):
            self.timestamp = ts
            self.punch = punch

    day = date(2024, 5, 15)
    records = [Rec(datetime(2024, 5, 15, 8, 0, 0), 0),
               Rec(datetime(2024, 5, 15, 17, 0, 0), 1)]

    r1 = engine_mod.compute_day_attendance(day=day, day_records=records,
                                           schedule_context=a)
    r2 = engine_mod.compute_day_attendance(day=day, day_records=records,
                                           schedule_context=b)
    r3 = engine_mod.compute_day_attendance(day=day, day_records=records)

    assert r1.work_hours == r2.work_hours == r3.work_hours
    assert r1.main_status == r2.main_status == r3.main_status
    assert r1.first_enter == r3.first_enter and r1.last_exit == r3.last_exit
    # context فقط برگردانده می‌شود
    assert r1.schedule_context is a and r2.schedule_context is b
    assert r3.schedule_context is None


# ============================================================
# 8.4 — جهت وابستگی
# ============================================================
# استثناهای *پیشین* که باید pin شوند تا بی‌سروصدا بزرگ نشوند.
KNOWN_CORE_TO_WEB = {
    'detailed_monthly_report_v2.py',   # از web.services.policy/HL/HM
    'raw_report.py',                   # از web.services.hourly_mission/travel_leave
}


def test_no_core_module_imports_web_except_known_exceptions():
    offenders = set()
    for path in sorted(CORE_DIR.glob('*.py')):
        for name in _imports(path):
            if name == 'web' or name.startswith('web.'):
                offenders.add(path.name)
    assert offenders <= KNOWN_CORE_TO_WEB, (
        f'وابستگی core -> web تازه اضافه شده: {offenders - KNOWN_CORE_TO_WEB}')


def test_central_engine_never_imports_web_even_transitively():
    for name in _imports(ENGINE):
        assert not (name == 'web' or name.startswith('web.')), \
            f'core/attendance_calculator.py -> {name}'


def test_web_services_never_import_web_routes():
    """لایه‌ی services نباید به لایه‌ی routes وابسته باشد (Phase 8 اصلاح شد)."""
    offenders = []
    for path in sorted(WEB_SERVICES_DIR.glob('*.py')):
        code = _code_without_comments_and_strings(path)
        if 'web.routes' in code:
            offenders.append(path.name)
    assert not offenders, f'web.services -> web.routes در: {offenders}'


# ============================================================
# 8.5 — re-exportهای legacy حفظ می‌شوند
# ============================================================
def test_legacy_reexports_are_identity_and_must_stay():
    """
    `web/routes/attendance.py` عمداً `analyze_day_status` و
    `calculate_work_hours` را re-export می‌کند (backwards compatibility).
    هویت تابع باید حفظ شود — مصرف‌کننده‌های قدیمی به همین اسم‌ها وابسته‌اند.
    """
    assert (attendance_route_mod.analyze_day_status
            is engine_mod.analyze_day_status)
    assert (attendance_route_mod.calculate_work_hours
            is engine_mod.calculate_work_hours)


def test_routes_actually_call_the_central_engine():
    """هر دو route اصلی باید مستقیماً همان تابع موتور را صدا بزنند."""
    import web.routes.admin as admin_mod
    import core.detailed_monthly_report_v2 as monthly_mod

    assert attendance_route_mod.compute_day_attendance is engine_mod.compute_day_attendance
    assert admin_mod.compute_day_attendance is engine_mod.compute_day_attendance
    assert monthly_mod.compute_day_attendance is engine_mod.compute_day_attendance


# ============================================================
# 8.16 — لایه‌ی export نباید چیزی را دوباره حساب کند
# ============================================================
@pytest.mark.parametrize('path', EXPORTERS, ids=lambda p: p.name)
def test_exporters_do_not_recompute_attendance(path: Path):
    code = _code_without_comments_and_strings(path)
    assert '/ 3600' not in code and '/3600' not in code, \
        f'{path.name} نباید ساعت کارکرد را حساب کند'
    for token in ('compute_day_attendance', 'calculate_work_hours',
                  'total_seconds', 'Attendance', 'query('):
        assert token not in code, \
            f'{path.name} نباید به تردد/DB دست بزند ({token})'


@pytest.mark.parametrize('path', EXPORTERS, ids=lambda p: p.name)
def test_exporters_are_pure_formatters(path: Path):
    """باید فقط `report: Dict` بگیرند و رشته برگردانند."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    exported = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith('export')
    ]
    assert exported, f'{path.name} تابع export ندارد'
    for fn in exported:
        args = [a.arg for a in fn.args.args if a.arg not in ('self', 'cls')]
        assert args, f'{fn.name} هیچ ورودی‌ای نمی‌گیرد'
        # ورودی اول باید دیکشنری/لیست گزارش باشد
        assert args[0] in ('report', 'reports'), (
            f'{fn.name} ورودی اول {args[0]} است')
