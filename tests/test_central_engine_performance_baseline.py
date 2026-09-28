"""
Phase 8 — performance audit: *اندازه‌گیری* منشأ N+1 در گزارش ماهانه.

این تست evidence تولید می‌کند (و عدد را pin می‌کند) بدون آنکه در این Phase
بهینه‌سازی انجام دهد؛ طبق 8.17 بهینه‌سازی فقط با evidence و خارج از محدوده
لایه‌ی Policy است.
"""
import re
from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import event

from core.detailed_monthly_report_v2 import DetailedMonthlyReportGeneratorV2
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

# baseline اندازه‌گیری‌شده در Phase 8 (اگر این عدد تغییر کرد باید بدانیم)
MEASURED_QUERY_COUNT = 100
MONTH_DAYS = (G_END - G_START).days + 1


class StatementCounter:
    def __init__(self, session):
        self.engine = session.get_bind()
        self.n = 0
        self.shapes = Counter()
        self._fn = self._on_execute
        event.listen(self.engine, 'before_cursor_execute', self._fn)

    def _on_execute(self, conn, cursor, statement, params, context, executemany):
        self.n += 1
        shape = re.sub(r'\s+', ' ', statement.strip())[:90]
        self.shapes[shape] += 1

    def stop(self):
        event.remove(self.engine, 'before_cursor_execute', self._fn)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


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
    _seed_punches(db, created['user_id'])
    try:
        yield created['user_id']
    finally:
        _cleanup_holiday(db)


def test_measure_monthly_report_query_shapes(gen, seeded):
    session = TestingSessionLocal()
    try:
        with StatementCounter(session) as counter:
            _make_report(gen, seeded, J_YEAR, J_MONTH)
    finally:
        session.close()

    # گزارش evidence برای مرور انسانی
    print(f'\nTOTAL QUERIES = {counter.n} for {MONTH_DAYS} days')
    for shape, count in counter.shapes.most_common(12):
        print(f'  {count:>4}x  {shape.encode("ascii", "backslashreplace").decode()}')

    # عدد pin می‌شود: تغییر ناگهانی باید دیده شود (نه اینکه بی‌صدا عوض شود)
    assert counter.n == MEASURED_QUERY_COUNT, (
        f'تعداد query گزارش ماهانه از {MEASURED_QUERY_COUNT} تغییر کرده به '
        f'{counter.n}. اگر عمدی است، عدد baseline را به‌روزرسانی کن و '
        'دلیلش را در docs بنویس.')


def test_n_plus_one_origin_is_policy_layer_not_central_engine():
    """
    منشأ N+1 باید *Policy* باشد (resolve_policy در هر روز)، نه موتور مرکزی.

    موتور صفر query دارد (در test_central_engine_performance اثبات شده)،
    پس این تست صرفاً انتظار را صریح می‌کند تا کسی منشأ را اشتباه نگیرد.
    """
    from pathlib import Path

    import core.attendance_calculator as engine_mod
    import core.detailed_monthly_report_v2 as monthly_mod

    engine_src = Path(engine_mod.__file__).read_text(encoding='utf-8')
    assert 'query' not in engine_src.replace('before_cursor_execute', '')

    monthly_src = Path(monthly_mod.__file__).read_text(encoding='utf-8')
    # policy در حلقه‌ی روزها صدا زده می‌شود → منشأ N+1
    assert 'resolve_policy' in monthly_src or 'resolve_effective' in monthly_src, (
        'گزارش ماهانه باید policy را از لایه‌ی Policy بگیرد')
