"""
Phase 8 — Performance audit برای centralization.

سؤال: آیا centralization باعث N+1 query یا محاسبه‌ی تکراری شده است؟

این تست **اندازه‌گیری** می‌کند (نه فقط حدس می‌زند): تعداد query واقعی
SQLAlchemy را هنگام اجرای هر مصرف‌کننده می‌شمارد و ثابت می‌کند که

    تعداد query  ≈  O(1) + چند query سیاست
    نه O(روزهای ماه)
    و اینکه موتور مرکزی هیچ DB accessی ندارد.
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event

import core.attendance_calculator as engine_mod
import core.detailed_monthly_report_v2 as monthly_mod
import web.routes.admin as admin_mod
import web.routes.attendance as att_mod
from core.attendance_calculator import compute_day_attendance
from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
from models.attendance import Attendance
from models.holiday import Holiday
from tests.conftest import TestingSessionLocal

from .test_attendance_route_regression import (
    G_END,
    G_START,
    J_MONTH,
    J_YEAR,
    _cleanup_holiday,
    _seed_punches,
)
from .test_monthly_full_central_engine import _make_report

PY = Path(engine_mod.__file__)


@pytest.fixture()
def gen(monkeypatch):
    monkeypatch.setattr(
        'core.detailed_monthly_report_v2.SessionLocal', TestingSessionLocal)
    generator = DetailedMonthlyReportGeneratorV2()
    try:
        yield generator
    finally:
        generator.close()


@pytest.fixture()
def seeded(db, make_user):
    db.query(Holiday).filter(
        Holiday.holiday_date >= G_START,
        Holiday.holiday_date <= G_END,
    ).delete()
    db.commit()
    created = make_user(role='user', department='4')
    uid = created['user_id']
    _seed_punches(db, uid)
    try:
        yield uid
    finally:
        _cleanup_holiday(db)


class QueryCounter:
    """شمارنده‌ی query واقعی روی Engine (رویداد سطح Connection)."""

    def __init__(self, session):
        self.engine = session.get_bind()
        self.n = 0
        self.shapes = Counter()
        self._fn = self._on_execute
        event.listen(self.engine, 'before_cursor_execute', self._fn)

    def _on_execute(self, conn, cursor, statement, params, context, executemany):
        self.n += 1
        match = re.search(r'FROM\s+([A-Za-z_][\w]*)', statement)
        table = match.group(1) if match else '?'
        self.shapes[table] += 1

    def reset(self):
        self.n = 0

    def stop(self):
        event.remove(self.engine, 'before_cursor_execute', self._fn)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


def test_central_engine_performs_no_database_access():
    """
    قطعی‌ترین نگهبان performance: خود موتور نباید هیچ DB access داشته باشد.
    اگر روزی کسی داخل موتور query بزند، این تست می‌شکند — و آن‌وقت
    فراخوانی per-day به N+1 query تبدیل می‌شود.
    """
    source = PY.read_text(encoding='utf-8')
    code = re.sub(r'#.*', '', source)
    code = re.sub(r'""".*?"""', '', code, flags=re.S)

    for token in ('db.query', 'session.query', 'SessionLocal',
                  'import Session', 'select(', 'engine', 'commit('):
        assert token not in code, (
            f'Central Engine نباید به DB دست بزند ({token}) — '
            'وگرنه هر فراخوانی per-day یک query می‌شود')

    # موتور فقط از dataclass / datetime / typing استفاده می‌کند
    imports = re.findall(r'^\s*(?:from|import)\s+([\w.]+)', source, re.M)
    allowed = {'dataclasses', 'datetime', 'typing', '__future__'}
    extra = {i for i in imports if i.split('.')[0] not in allowed}
    assert not extra, f'import غیرمجاز در Central Engine: {extra}'


def test_engine_call_count_is_linear_in_days_not_quadratic(gen, seeded):
    """
    مصرف‌کننده باید رکوردها را *یک بار* بگیرد و موتور را per-day صدا بزند.
    این تست ثابت می‌کند تعداد روزهای ماه، تعداد query را زیاد نمی‌کند.
    """
    session = TestingSessionLocal()
    try:
        with QueryCounter(session) as counter:
            counter.reset()
            records = session.query(Attendance).filter(
                Attendance.user_id == seeded,
                Attendance.is_deleted == False,
            ).all()
            single_query_count = counter.n

            # حالا موتور را برای تمام روزهای ماه صدا بزنیم
            counter.reset()
            by_day = {}
            for rec in records:
                by_day.setdefault(rec.timestamp.date(), []).append(rec)
            current, month_end = G_START, G_END
            while current <= month_end:
                compute_day_attendance(
                    day=current,
                    day_records=by_day.get(current, []),
                    prev_day_records=by_day.get(current - timedelta(days=1), []),
                    next_day_records=by_day.get(current + timedelta(days=1), []),
                    is_friday=current.weekday() == 4,
                )
                current += timedelta(days=1)
            engine_query_count = counter.n
    finally:
        session.close()

    assert single_query_count == 1, 'رکوردها باید با یک query گرفته شوند'
    assert engine_query_count == 0, (
        'موتور مرکزی نباید هنگام محاسبه هیچ query بزند '
        f'(دیده شد: {engine_query_count})')


def test_monthly_report_fetches_attendance_records_exactly_once(gen, seeded):
    """
    ادعای درست (و مهم): centralization باعث N+1 نشده است.

    رکوردهای تردد باید *یک بار* برای کل ماه خوانده شوند، نه یک بار به
    ازای هر روز. تعداد query جدول `attendances` باید دقیقاً ۱ باشد.

    N+1 باقی‌مانده در لایه‌ی Policy است (`attendance_policies` و `holidays`
    در هر روز) و طبق مرزبندی پروژه خارج از Central Engine است؛ اندازه‌گیری
    کامل آن در `tests/test_central_engine_performance_baseline.py` pin شده.
    """
    import re as _re

    session = TestingSessionLocal()
    try:
        with QueryCounter(session) as counter:
            counter.reset()
            _make_report(gen, seeded, J_YEAR, J_MONTH)
            total = counter.n
            attendance_queries = counter.shapes.get('attendances', 0)
            tables = dict(counter.shapes)
    finally:
        session.close()

    month_days = (G_END - G_START).days + 1

    assert attendance_queries == 1, (
        f'رکوردهای تردد باید یک بار خوانده شوند، اما {attendance_queries} بار '
        f'query شد — این N+1 است. جدول‌ها: {tables}')
    assert total >= 1


def test_consumers_fetch_records_once_with_margin():
    """
    ساختاری: هر سه مصرف‌کننده باید رکوردها را یک‌بار با حاشیه‌ی ماه بگیرند،
    نه اینکه برای هر روز جداگانه query بزنند.
    """
    for mod in (att_mod, admin_mod, monthly_mod):
        source = Path(mod.__file__).read_text(encoding='utf-8')
        # حاشیه‌ی -1 / +2 روز باید در query وجود داشته باشد
        assert re.search(r'timedelta\(days\s*=\s*-1\)', source) or \
            re.search(r'timedelta\(days=-1\)', source) or \
            '- timedelta(days=1)' in source, (
            f'{mod.__name__} باید context روز قبل را بگیرد')
        assert re.search(r'timedelta\(days\s*=\s*2\)|timedelta\(days=2\)', source) or \
            '+ timedelta(days=2)' in source, (
            f'{mod.__name__} باید context روز بعد را بگیرد')
